from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from app.repositories.sandbox_lease_repository import SandboxLeaseRepository
from app.agent import SandboxedReactAgent
from app.sandbox_lifecycle import SandboxLifecycleService
from app.sandbox_manager import SandboxManager
from app.services.workspace_admin_clients import KubernetesApiWorkspaceAdminClient
from app.session_store import SessionStore


RUN_ENV_VAR = "RUN_INFRA_INTEGRATION_TESTS"
ARTIFACT_DIR_ENV_VAR = "INFRA_ITEST_ARTIFACT_DIR"


@dataclass(frozen=True)
class InfraIntegrationConfig:
    namespace: str
    base_template_name: str
    runtime_template_name: str
    api_url: str


@dataclass(frozen=True)
class ProvisionedTemplate:
    name: str
    ksa_name: str
    bucket_name: str
    mount_path: str


class K8sDiagnosticsCollector:
    def __init__(self, *, namespace: str) -> None:
        self.namespace = namespace
        default_dir = Path(__file__).resolve().parent / "artifacts"
        artifact_dir = Path(os.getenv(ARTIFACT_DIR_ENV_VAR, str(default_dir))).resolve()
        artifact_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_dir = artifact_dir

    def _event_summary(self, event: Any) -> dict[str, Any]:
        involved = getattr(event, "involved_object", None)
        return {
            "type": getattr(event, "type", None),
            "reason": getattr(event, "reason", None),
            "message": getattr(event, "message", None),
            "count": getattr(event, "count", None),
            "first_timestamp": str(getattr(event, "first_timestamp", None) or ""),
            "last_timestamp": str(getattr(event, "last_timestamp", None) or ""),
            "event_time": str(getattr(event, "event_time", None) or ""),
            "involved_object": {
                "kind": getattr(involved, "kind", None) if involved else None,
                "name": getattr(involved, "name", None) if involved else None,
                "namespace": getattr(involved, "namespace", None) if involved else None,
            },
        }

    def _safe_get_custom_object(
        self, *, plural: str, name: str
    ) -> dict[str, Any] | dict[str, str]:
        from kubernetes.client.exceptions import ApiException

        api = _custom_objects_api()
        try:
            return api.get_namespaced_custom_object(
                group="extensions.agents.x-k8s.io",
                version="v1alpha1",
                namespace=self.namespace,
                plural=plural,
                name=name,
            )
        except ApiException as exc:
            return {"error": f"{plural}/{name}: api_status={exc.status}"}
        except Exception as exc:
            return {"error": f"{plural}/{name}: {exc}"}

    def _discover_sandbox_name(self, *, claim_name: str) -> str | None:
        claim_obj = self._safe_get_custom_object(
            plural="sandboxclaims", name=claim_name
        )
        if isinstance(claim_obj, dict):
            status = dict(claim_obj.get("status") or {})
            for key in ("sandboxName", "sandbox", "boundSandboxName"):
                value = status.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        api = _custom_objects_api()
        try:
            payload = api.list_namespaced_custom_object(
                group="extensions.agents.x-k8s.io",
                version="v1alpha1",
                namespace=self.namespace,
                plural="sandboxes",
            )
        except Exception:
            return None

        for item in list(payload.get("items") or []):
            metadata = dict(item.get("metadata") or {})
            status = dict(item.get("status") or {})
            spec = dict(item.get("spec") or {})
            refs = list(metadata.get("ownerReferences") or [])
            if any(ref.get("name") == claim_name for ref in refs):
                name = metadata.get("name")
                return str(name) if name else None
            if (
                status.get("claimName") == claim_name
                or spec.get("claimName") == claim_name
            ):
                name = metadata.get("name")
                return str(name) if name else None
        return None

    def _discover_pod_name(self, *, sandbox_name: str | None) -> str | None:
        if not sandbox_name:
            return None
        sandbox_obj = self._safe_get_custom_object(
            plural="sandboxes", name=sandbox_name
        )
        if not isinstance(sandbox_obj, dict):
            return None

        metadata = dict(sandbox_obj.get("metadata") or {})
        status = dict(sandbox_obj.get("status") or {})
        spec = dict(sandbox_obj.get("spec") or {})

        candidate = status.get("podName") or status.get("runtimePodName")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

        pod_ref = spec.get("podRef")
        if isinstance(pod_ref, dict):
            name = pod_ref.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()

        annotations = dict(metadata.get("annotations") or {})
        for key, value in annotations.items():
            if "pod-name" in key and isinstance(value, str) and value.strip():
                return value.strip()

        core_api = _core_v1_api()
        try:
            pods = core_api.list_namespaced_pod(namespace=self.namespace)
        except Exception:
            return None
        for pod in list(getattr(pods, "items", []) or []):
            refs = list(
                getattr(getattr(pod, "metadata", None), "owner_references", []) or []
            )
            if any(getattr(ref, "name", None) == sandbox_name for ref in refs):
                pod_name = getattr(getattr(pod, "metadata", None), "name", None)
                if isinstance(pod_name, str) and pod_name.strip():
                    return pod_name.strip()
        return None

    def _events_for_name(self, *, object_name: str) -> list[dict[str, Any]]:
        core_api = _core_v1_api()
        try:
            events = core_api.list_namespaced_event(
                namespace=self.namespace,
                field_selector=f"involvedObject.name={object_name}",
            )
        except Exception as exc:
            return [{"error": f"events for {object_name}: {exc}"}]

        return [
            self._event_summary(item)
            for item in list(getattr(events, "items", []) or [])
        ]

    def _recent_failed_mount_events(self) -> list[dict[str, Any]]:
        core_api = _core_v1_api()
        try:
            events = core_api.list_namespaced_event(namespace=self.namespace)
        except Exception as exc:
            return [{"error": f"failed-mount event scan: {exc}"}]

        failed = []
        for item in list(getattr(events, "items", []) or []):
            reason = str(getattr(item, "reason", "") or "")
            message = str(getattr(item, "message", "") or "")
            if reason == "FailedMount" or "workspace-gcs-fuse" in message:
                failed.append(self._event_summary(item))
        return failed[-100:]

    def _pod_summary_and_logs(
        self, *, pod_name: str
    ) -> tuple[dict[str, Any], str | None]:
        core_api = _core_v1_api()
        summary: dict[str, Any]
        logs: str | None

        try:
            pod = core_api.read_namespaced_pod(name=pod_name, namespace=self.namespace)
            summary = {
                "name": pod_name,
                "phase": getattr(getattr(pod, "status", None), "phase", None),
                "conditions": [
                    {
                        "type": getattr(cond, "type", None),
                        "status": getattr(cond, "status", None),
                        "reason": getattr(cond, "reason", None),
                        "message": getattr(cond, "message", None),
                    }
                    for cond in list(
                        getattr(getattr(pod, "status", None), "conditions", []) or []
                    )
                ],
                "container_statuses": [
                    {
                        "name": getattr(cs, "name", None),
                        "ready": getattr(cs, "ready", None),
                        "restart_count": getattr(cs, "restart_count", None),
                        "state": str(getattr(cs, "state", None)),
                    }
                    for cs in list(
                        getattr(
                            getattr(pod, "status", None),
                            "container_statuses",
                            [],
                        )
                        or []
                    )
                ],
            }
        except Exception as exc:
            summary = {"error": f"pod summary {pod_name}: {exc}"}

        try:
            logs = core_api.read_namespaced_pod_log(
                name=pod_name,
                namespace=self.namespace,
                tail_lines=300,
                timestamps=True,
            )
        except Exception as exc:
            logs = f"pod logs unavailable: {exc}"

        return summary, logs

    def capture(
        self,
        *,
        test_name: str,
        claim_name: str | None = None,
        note: dict[str, Any] | None = None,
    ) -> Path:
        sandbox_name = (
            self._discover_sandbox_name(claim_name=claim_name) if claim_name else None
        )
        pod_name = self._discover_pod_name(sandbox_name=sandbox_name)

        payload: dict[str, Any] = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "namespace": self.namespace,
            "test_name": test_name,
            "note": note or {},
            "claim_name": claim_name,
            "sandbox_name": sandbox_name,
            "pod_name": pod_name,
            "recent_failed_mount_events": self._recent_failed_mount_events(),
        }

        if claim_name:
            payload["sandbox_claim"] = self._safe_get_custom_object(
                plural="sandboxclaims",
                name=claim_name,
            )
            payload["claim_events"] = self._events_for_name(object_name=claim_name)

        if sandbox_name:
            payload["sandbox"] = self._safe_get_custom_object(
                plural="sandboxes",
                name=sandbox_name,
            )
            payload["sandbox_events"] = self._events_for_name(object_name=sandbox_name)

        if pod_name:
            pod_summary, pod_logs = self._pod_summary_and_logs(pod_name=pod_name)
            payload["pod_summary"] = pod_summary
            payload["pod_events"] = self._events_for_name(object_name=pod_name)
            payload["pod_logs_tail"] = pod_logs

        safe_name = test_name.replace("/", "-").replace(" ", "-")
        path = self.artifact_dir / f"{safe_name}-{uuid.uuid4().hex[:8]}.json"
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8"
        )
        return path


def _integration_enabled() -> bool:
    return os.getenv(RUN_ENV_VAR, "0") == "1"


def _custom_objects_api():
    from kubernetes import client, config

    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()
    return client.CustomObjectsApi()


def _core_v1_api():
    from kubernetes import client, config

    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()
    return client.CoreV1Api()


def _wait_for_claim_deleted(
    *, namespace: str, claim_name: str, timeout_seconds: int
) -> None:
    from kubernetes.client.exceptions import ApiException

    api = _custom_objects_api()
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            api.get_namespaced_custom_object(
                group="extensions.agents.x-k8s.io",
                version="v1alpha1",
                namespace=namespace,
                plural="sandboxclaims",
                name=claim_name,
            )
        except ApiException as exc:
            if exc.status == 404:
                return
            raise
        time.sleep(1)
    raise AssertionError(
        f"sandbox claim '{claim_name}' was not deleted within {timeout_seconds}s"
    )


def _build_integration_agent(tmp_path, monkeypatch) -> SandboxedReactAgent:
    db_path = tmp_path / f"infra-agent-{uuid.uuid4().hex[:8]}.db"
    asset_dir = tmp_path / f"infra-agent-assets-{uuid.uuid4().hex[:8]}"
    frontend_cache_dir = tmp_path / f"infra-agent-frontend-{uuid.uuid4().hex[:8]}"
    frontend_cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SESSION_STORE_PATH", str(db_path))
    monkeypatch.setenv("ASSET_STORE_PATH", str(asset_dir))
    monkeypatch.setenv("FRONTEND_LIB_CACHE_PATH", str(frontend_cache_dir))
    monkeypatch.setenv("SANDBOX_WORKSPACE_PATH", "/tmp")
    monkeypatch.setenv("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", "test-key"))
    return SandboxedReactAgent()


def _agent_exec_python(
    *,
    agent: SandboxedReactAgent,
    user_id: str,
    session_id: str,
    code: str,
) -> dict[str, Any]:
    runtime_config = agent._runtime_context_for_session(user_id, session_id)
    payload_json, _ = agent._run_tool(
        session_id=session_id,
        tool_call_id=f"tool-{uuid.uuid4().hex[:8]}",
        name="sandbox_exec_python",
        arguments_json=json.dumps({"code": code}),
        runtime_config=runtime_config,
    )
    return json.loads(payload_json)


def _list_template_names(namespace: str) -> list[str]:
    api = _custom_objects_api()
    payload = api.list_namespaced_custom_object(
        group="extensions.agents.x-k8s.io",
        version="v1alpha1",
        namespace=namespace,
        plural="sandboxtemplates",
    )
    names: list[str] = []
    for item in list(payload.get("items") or []):
        name = str((item.get("metadata") or {}).get("name") or "").strip()
        if name:
            names.append(name)
    return sorted(set(names))


def _select_alternate_template(infra_config: InfraIntegrationConfig) -> str:
    available = _list_template_names(infra_config.namespace)
    preferred_raw = str(
        os.getenv("INFRA_ITEST_ALTERNATE_TEMPLATE_NAME", "") or ""
    ).strip()
    preferred = (
        [preferred_raw]
        if preferred_raw
        else [
            "python-runtime-template",
            "python-runtime-template-large",
            "python-runtime-template-pydata",
        ]
    )
    for name in preferred:
        if name and name != infra_config.runtime_template_name and name in available:
            return name
    for name in available:
        if name != infra_config.runtime_template_name and not name.startswith(
            "infra-itest-template-"
        ):
            return name
    pytest.skip(
        "No alternate SandboxTemplate available for policy switch test in "
        f"namespace={infra_config.namespace}; available={available}"
    )


@pytest.fixture(scope="module")
def infra_config() -> InfraIntegrationConfig:
    if not _integration_enabled():
        pytest.skip(f"set {RUN_ENV_VAR}=1 to run live Kubernetes integration tests")

    config = InfraIntegrationConfig(
        namespace=os.getenv("INFRA_ITEST_NAMESPACE", "alt-default"),
        base_template_name=os.getenv(
            "INFRA_ITEST_BASE_TEMPLATE_NAME", "python-runtime-template-small"
        ),
        runtime_template_name=os.getenv(
            "INFRA_ITEST_RUNTIME_TEMPLATE_NAME", "python-runtime-template-small"
        ),
        api_url=os.getenv(
            "INFRA_ITEST_SANDBOX_API_URL",
            "http://127.0.0.1:18080",
        ),
    )

    from kubernetes.client.exceptions import ApiException

    core_api = _core_v1_api()
    custom_api = _custom_objects_api()

    try:
        core_api.read_namespaced_service(
            name="sandbox-router-svc",
            namespace=config.namespace,
        )
    except ApiException as exc:
        pytest.skip(
            "sandbox router service prerequisite is not available: "
            f"{config.namespace}/sandbox-router-svc ({exc.status})"
        )

    try:
        custom_api.get_namespaced_custom_object(
            group="extensions.agents.x-k8s.io",
            version="v1alpha1",
            namespace=config.namespace,
            plural="sandboxtemplates",
            name=config.base_template_name,
        )
    except ApiException as exc:
        pytest.skip(
            "base SandboxTemplate prerequisite is not available: "
            f"{config.namespace}/{config.base_template_name} ({exc.status})"
        )

    try:
        custom_api.get_namespaced_custom_object(
            group="extensions.agents.x-k8s.io",
            version="v1alpha1",
            namespace=config.namespace,
            plural="sandboxtemplates",
            name=config.runtime_template_name,
        )
    except ApiException as exc:
        pytest.skip(
            "runtime SandboxTemplate prerequisite is not available: "
            f"{config.namespace}/{config.runtime_template_name} ({exc.status})"
        )

    return config


@pytest.fixture(scope="module")
def reachable_router(infra_config: InfraIntegrationConfig) -> None:
    import requests

    health_url = infra_config.api_url.rstrip("/") + "/health"
    try:
        response = requests.get(health_url, timeout=5)
        if response.status_code >= 500:
            pytest.skip(
                "sandbox router gateway is reachable but unhealthy at "
                f"{health_url} (status={response.status_code})"
            )
    except Exception as exc:
        pytest.skip(
            "sandbox router gateway is not reachable at "
            f"{health_url}. Start a port-forward or set INFRA_ITEST_SANDBOX_API_URL. "
            f"error={exc}"
        )


@pytest.fixture
def diagnostics_collector(
    infra_config: InfraIntegrationConfig,
) -> K8sDiagnosticsCollector:
    return K8sDiagnosticsCollector(namespace=infra_config.namespace)


@pytest.fixture
def provisioned_template(infra_config: InfraIntegrationConfig) -> ProvisionedTemplate:
    admin_client = KubernetesApiWorkspaceAdminClient(namespace=infra_config.namespace)
    suffix = uuid.uuid4().hex[:10]
    ksa_name = f"infra-itest-ksa-{suffix}"
    template_name = f"infra-itest-template-{suffix}"
    bucket_name = f"infra-itest-{suffix}"
    mount_path = "/workspace"

    admin_client.ensure_service_account(
        namespace=infra_config.namespace,
        name=ksa_name,
        annotations={
            "iam.gke.io/gcp-service-account": f"infra-itest-{suffix}@example.invalid"
        },
    )
    admin_client.ensure_sandbox_template(
        namespace=infra_config.namespace,
        name=template_name,
        base_template_name=infra_config.base_template_name,
        ksa_name=ksa_name,
        bucket_name=bucket_name,
        managed_folder_path="",
        mount_path=mount_path,
        labels={
            "managed-by": "infra-integration-tests",
            "suite": "sandboxed-react-agent-backend",
        },
    )

    try:
        yield ProvisionedTemplate(
            name=template_name,
            ksa_name=ksa_name,
            bucket_name=bucket_name,
            mount_path=mount_path,
        )
    finally:
        admin_client.delete_sandbox_template(
            namespace=infra_config.namespace,
            name=template_name,
        )
        admin_client.delete_service_account(
            namespace=infra_config.namespace,
            name=ksa_name,
        )


def test_workspace_admin_client_provisions_template_mount(
    infra_config: InfraIntegrationConfig,
    provisioned_template: ProvisionedTemplate,
    diagnostics_collector: K8sDiagnosticsCollector,
) -> None:
    template = _custom_objects_api().get_namespaced_custom_object(
        group="extensions.agents.x-k8s.io",
        version="v1alpha1",
        namespace=infra_config.namespace,
        plural="sandboxtemplates",
        name=provisioned_template.name,
    )

    spec = dict(template.get("spec") or {})
    pod_template = dict(spec.get("podTemplate") or {})
    pod_spec = dict(pod_template.get("spec") or {})
    volumes = list(pod_spec.get("volumes") or [])

    workspace_volume = next(
        (entry for entry in volumes if entry.get("name") == "workspace-gcs-fuse"),
        None,
    )
    assert workspace_volume is not None
    assert (
        workspace_volume.get("csi", {}).get("volumeAttributes", {}).get("bucketName")
        == provisioned_template.bucket_name
    )
    assert pod_spec.get("serviceAccountName") == provisioned_template.ksa_name

    containers = list(pod_spec.get("containers") or [])
    mount_paths = {
        mount.get("mountPath")
        for container in containers
        for mount in list(container.get("volumeMounts") or [])
        if mount.get("name") == "workspace-gcs-fuse"
    }
    assert provisioned_template.mount_path in mount_paths

    diagnostics_collector.capture(
        test_name="test_workspace_admin_client_provisions_template_mount",
        note={"provisioned_template_name": provisioned_template.name},
    )


def test_sandbox_lifecycle_reuses_single_claim_for_session(
    tmp_path,
    infra_config: InfraIntegrationConfig,
    reachable_router: None,
    diagnostics_collector: K8sDiagnosticsCollector,
) -> None:
    manager = SandboxManager()
    manager.update_config(
        mode="cluster",
        api_url=infra_config.api_url,
        template_name=infra_config.runtime_template_name,
        namespace=infra_config.namespace,
    )
    manager.workspace_path = "/"

    store = SessionStore(db_path=str(tmp_path / "infra-lifecycle.db"))
    repository = SandboxLeaseRepository(store)
    lifecycle = SandboxLifecycleService(
        sandbox_manager=manager,
        sandbox_lease_repository=repository,
    )
    lifecycle.update_config(execution_model="session", session_idle_ttl_seconds=300)

    session_id = f"infra-session-{uuid.uuid4().hex[:8]}"
    claim_name: str | None = None
    diagnostics_path: Path | None = None
    try:
        first = lifecycle.exec_python(
            session_id,
            "print('infra-python-ok')",
        )
        claim_name = first.claim_name
        diagnostics_path = diagnostics_collector.capture(
            test_name="test_sandbox_lifecycle_reuses_single_claim_for_session-pre-release",
            claim_name=claim_name,
            note={"first_ok": first.ok, "first_error": first.error},
        )
        assert first.ok is True, (
            "first lifecycle execution failed; "
            f"see diagnostics artifact: {diagnostics_path}"
        )
        assert "infra-python-ok" in first.stdout
        assert first.lease_id
        assert first.claim_name

        second = lifecycle.exec_shell(
            session_id,
            "printf infra-shell-ok",
        )
        assert second.ok is True
        assert "infra-shell-ok" in second.stdout
        assert second.lease_id == first.lease_id
        assert second.claim_name == first.claim_name

        active = repository.get_active_for_scope("session", session_id)
        assert active is not None
        assert active["claim_name"] == first.claim_name
        assert active["status"] == "ready"
    finally:
        if claim_name:
            diagnostics_collector.capture(
                test_name="test_sandbox_lifecycle_reuses_single_claim_for_session-before-release",
                claim_name=claim_name,
                note={"session_id": session_id},
            )
        released = lifecycle.release_scope("session", session_id)
        if claim_name is not None and released:
            _wait_for_claim_deleted(
                namespace=infra_config.namespace,
                claim_name=claim_name,
                timeout_seconds=120,
            )
            diagnostics_collector.capture(
                test_name="test_sandbox_lifecycle_reuses_single_claim_for_session-after-release",
                claim_name=claim_name,
                note={"session_id": session_id, "released": released},
            )


def test_sandbox_manager_cluster_exec_python_works(
    infra_config: InfraIntegrationConfig,
    reachable_router: None,
    diagnostics_collector: K8sDiagnosticsCollector,
) -> None:
    manager = SandboxManager()
    manager.workspace_path = "/"
    result = manager.exec_python(
        "print('infra-manager-ok')",
        runtime_config={
            "mode": "cluster",
            "api_url": infra_config.api_url,
            "template_name": infra_config.runtime_template_name,
            "namespace": infra_config.namespace,
        },
    )

    diagnostics_path = diagnostics_collector.capture(
        test_name="test_sandbox_manager_cluster_exec_python_works",
        note={"ok": result.ok, "error": result.error},
    )
    assert result.ok is True, (
        "sandbox manager cluster execution failed; "
        f"see diagnostics artifact: {diagnostics_path}"
    )
    assert "infra-manager-ok" in result.stdout


def test_session_policy_change_recycles_lease_and_switches_template(
    tmp_path,
    monkeypatch,
    infra_config: InfraIntegrationConfig,
    reachable_router: None,
    diagnostics_collector: K8sDiagnosticsCollector,
) -> None:
    agent = _build_integration_agent(tmp_path, monkeypatch)
    user_id = f"infra-user-{uuid.uuid4().hex[:8]}"
    session = agent.create_session(title="Infra policy recycle", user_id=user_id)
    session_id = session.session_id
    alternate_template_name = _select_alternate_template(infra_config)

    first_claim: str | None = None
    second_claim: str | None = None
    try:
        agent.update_runtime_config(
            user_id=user_id,
            toolkits={
                "sandbox": {
                    "runtime": {
                        "mode": "cluster",
                        "profile": "transient",
                        "api_url": infra_config.api_url,
                        "template_name": infra_config.runtime_template_name,
                        "namespace": infra_config.namespace,
                        "workspace_path": "/tmp",
                    },
                    "lifecycle": {
                        "execution_model": "session",
                        "session_idle_ttl_seconds": 300,
                    },
                }
            },
        )

        first = _agent_exec_python(
            agent=agent,
            user_id=user_id,
            session_id=session_id,
            code="print('infra-policy-before')",
        )
        first_claim = str(first.get("claim_name") or "") or None
        diagnostics_path = diagnostics_collector.capture(
            test_name="test_session_policy_change_recycles_lease_and_switches_template-before",
            claim_name=first_claim,
            note={"first_ok": first.get("ok"), "first_error": first.get("error")},
        )
        assert first.get("ok") is True, (
            "first execution failed before policy change; "
            f"see diagnostics artifact: {diagnostics_path}"
        )
        assert first_claim
        assert "infra-policy-before" in str(first.get("stdout") or "")

        status_before = agent.get_session_sandbox_status(session_id, user_id)
        assert (
            status_before["sandbox"]["template_name"]
            == infra_config.runtime_template_name
        )

        updated = agent.update_session_sandbox_policy(
            session_id,
            user_id,
            {
                "profile": "transient",
                "template_name": alternate_template_name,
            },
        )
        assert updated["lease_released"] is True
        assert updated["sandbox_policy"]["template_name"] == alternate_template_name

        status_after_update = agent.get_session_sandbox_status(session_id, user_id)
        assert status_after_update["sandbox"]["has_active_lease"] is False

        if first_claim:
            _wait_for_claim_deleted(
                namespace=infra_config.namespace,
                claim_name=first_claim,
                timeout_seconds=120,
            )

        second = _agent_exec_python(
            agent=agent,
            user_id=user_id,
            session_id=session_id,
            code="print('infra-policy-after')",
        )
        second_claim = str(second.get("claim_name") or "") or None
        diagnostics_path_after = diagnostics_collector.capture(
            test_name="test_session_policy_change_recycles_lease_and_switches_template-after",
            claim_name=second_claim,
            note={
                "second_ok": second.get("ok"),
                "second_error": second.get("error"),
                "first_claim": first_claim,
                "second_claim": second_claim,
                "session_policy": updated.get("sandbox_policy"),
            },
        )
        assert second.get("ok") is True, (
            "second execution failed after policy change; "
            f"see diagnostics artifact: {diagnostics_path_after}"
        )
        assert second_claim
        assert second_claim != first_claim
        assert "infra-policy-after" in str(second.get("stdout") or "")

        status_after_second = agent.get_session_sandbox_status(session_id, user_id)
        assert (
            status_after_second["sandbox"]["template_name"] == alternate_template_name
        )
        assert (
            status_after_second["effective"]["runtime"]["template_name"]
            == alternate_template_name
        )
    finally:
        released = agent.sandbox_lease_facade.release_session(session_id)
        if second_claim and released:
            _wait_for_claim_deleted(
                namespace=infra_config.namespace,
                claim_name=second_claim,
                timeout_seconds=120,
            )
            diagnostics_collector.capture(
                test_name="test_session_policy_change_recycles_lease_and_switches_template-cleanup",
                claim_name=second_claim,
                note={"released": released, "session_id": session_id},
            )
        agent.close()


def test_reconcile_workspace_action_updates_session_status(
    tmp_path,
    monkeypatch,
    infra_config: InfraIntegrationConfig,
    diagnostics_collector: K8sDiagnosticsCollector,
) -> None:
    agent = _build_integration_agent(tmp_path, monkeypatch)
    user_id = f"infra-user-{uuid.uuid4().hex[:8]}"
    session = agent.create_session(title="Infra reconcile action", user_id=user_id)
    session_id = session.session_id

    try:
        agent.update_runtime_config(
            user_id=user_id,
            toolkits={
                "sandbox": {
                    "runtime": {
                        "mode": "cluster",
                        "profile": "persistent_workspace",
                        "api_url": infra_config.api_url,
                        "template_name": infra_config.runtime_template_name,
                        "namespace": infra_config.namespace,
                    }
                }
            },
        )

        before_status = agent.get_session_sandbox_status(session_id, user_id)
        try:
            action = agent.perform_session_sandbox_action(
                session_id,
                user_id,
                action="reconcile_workspace",
                wait=False,
            )
        except RuntimeError as exc:
            error_text = str(exc)
            if "workspace admin client is not configured" in error_text:
                pytest.skip(
                    "workspace provisioning integration prerequisites are not configured"
                )
            raise

        after_status = action.get("status") or {}
        workspace_status = dict(after_status.get("workspace_status") or {})
        workspace = workspace_status.get("workspace")

        diagnostics_collector.capture(
            test_name="test_reconcile_workspace_action_updates_session_status",
            note={
                "session_id": session_id,
                "started": action.get("started"),
                "before_workspace_status": before_status.get("workspace_status"),
                "after_workspace_status": workspace_status,
            },
        )

        assert action.get("action") == "reconcile_workspace"
        assert "workspace_status" in after_status
        assert isinstance(workspace_status.get("provisioning_pending"), bool)
        assert workspace is None or str(workspace.get("status") or "") in {
            "pending",
            "reconciling",
            "ready",
            "error",
        }
    finally:
        agent.close()
