from __future__ import annotations

import sys
import threading
from types import SimpleNamespace

from app.sandbox_lifecycle import SandboxLease, SandboxLifecycleService
from app.sandbox_manager import SandboxExecutionResult


class FakeSandboxManager:
    def __init__(self) -> None:
        self.mode = "cluster"
        self.api_url = "http://sandbox-router"
        self.template_name = "python-runtime-template-small"
        self.namespace = "alt-default"
        self.server_port = 8888
        self.sandbox_ready_timeout = 420
        self.gateway_ready_timeout = 180
        self.max_output_chars = 6000
        self.local_timeout_seconds = 20
        self.exec_python_with_sandbox_calls: list[dict[str, object]] = []

    def exec_python(self, code: str, runtime_config=None):  # pragma: no cover
        return SandboxExecutionResult(
            tool_name="sandbox_exec_python",
            ok=True,
            stdout=code,
            stderr="",
            exit_code=0,
        )

    def exec_shell(self, command: str, runtime_config=None):  # pragma: no cover
        return SandboxExecutionResult(
            tool_name="sandbox_exec_shell",
            ok=True,
            stdout=command,
            stderr="",
            exit_code=0,
        )

    def exec_python_with_sandbox(
        self, code: str, *, sandbox, lease_id, claim_name, runtime_config
    ):
        self.exec_python_with_sandbox_calls.append(
            {
                "code": code,
                "sandbox": sandbox,
                "lease_id": lease_id,
                "claim_name": claim_name,
                "runtime_config": dict(runtime_config),
            }
        )
        return SandboxExecutionResult(
            tool_name="sandbox_exec_python",
            ok=True,
            stdout="ok",
            stderr="",
            exit_code=0,
            lease_id=lease_id,
            claim_name=claim_name,
        )

    def exec_shell_with_sandbox(
        self, command: str, *, sandbox, lease_id, claim_name, runtime_config
    ):
        return SandboxExecutionResult(
            tool_name="sandbox_exec_shell",
            ok=True,
            stdout="ok",
            stderr="",
            exit_code=0,
            lease_id=lease_id,
            claim_name=claim_name,
        )


class FakeSandboxLeaseRepository:
    def __init__(self, active_lease=None):
        self.active_lease = active_lease
        self.upserts = []
        self.releases = []

    def list_active(self):
        return [self.active_lease] if self.active_lease else []

    def upsert(self, lease):
        self.upserts.append(dict(lease))
        self.active_lease = dict(lease)
        return None

    def get(self, lease_id):
        if self.active_lease and self.active_lease.get("lease_id") == lease_id:
            return dict(self.active_lease)
        return None

    def get_active_for_scope(self, scope_type, scope_key):
        if (
            self.active_lease
            and self.active_lease.get("scope_type") == scope_type
            and self.active_lease.get("scope_key") == scope_key
            and self.active_lease.get("status") in {"pending", "ready"}
        ):
            return dict(self.active_lease)
        return None

    def list_expired(self, now_iso):
        return []

    def mark_released(
        self, lease_id, *, released_at, status="released", last_error=None
    ):
        self.releases.append(
            {
                "lease_id": lease_id,
                "released_at": released_at,
                "status": status,
                "last_error": last_error,
            }
        )
        if self.active_lease and self.active_lease.get("lease_id") == lease_id:
            self.active_lease["status"] = status
        return None


def _runtime(lease_id: str = "lease-1"):
    lease = SandboxLease(
        lease_id=lease_id,
        scope_type="session",
        scope_key="session-1",
        status="ready",
        claim_name="claim-1",
        template_name="python-runtime-template-user",
        namespace="alt-default",
        metadata={},
        created_at="2026-01-01T00:00:00+00:00",
        last_used_at="2026-01-01T00:00:00+00:00",
        expires_at="2099-01-01T00:00:00+00:00",
    )

    class Runtime:
        def __init__(self) -> None:
            self.lease = lease
            self.client = object()
            self.lock = threading.RLock()

    return Runtime()


def test_exec_python_starts_workspace_provisioning_when_missing(monkeypatch) -> None:
    monkeypatch.setenv("SANDBOX_PERSISTENT_AUTO_FALLBACK_ENABLED", "0")
    manager = FakeSandboxManager()
    service = SandboxLifecycleService(
        sandbox_manager=manager,
        sandbox_lease_repository=FakeSandboxLeaseRepository(),
        get_user_id_for_session=lambda session_id: "user-1",
        get_workspace_for_user=lambda user_id: None,
        ensure_workspace_async_for_user=lambda user_id: (
            {"workspace_id": "ws-1", "user_id": user_id, "status": "pending"},
            True,
        ),
    )

    acquire_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        service,
        "acquire_scope_lease",
        lambda scope_type, scope_key, runtime_config=None: acquire_calls.append(
            (scope_type, scope_key)
        ),
    )

    result = service.exec_python("session-1", "print('hello')")

    assert result.ok is False
    assert result.error == "Workspace provisioning started. Retry in a few seconds."
    assert acquire_calls == []


def test_exec_python_returns_pending_workspace_error(monkeypatch) -> None:
    monkeypatch.setenv("SANDBOX_PERSISTENT_AUTO_FALLBACK_ENABLED", "0")
    manager = FakeSandboxManager()
    service = SandboxLifecycleService(
        sandbox_manager=manager,
        sandbox_lease_repository=FakeSandboxLeaseRepository(),
        get_user_id_for_session=lambda session_id: "user-1",
        get_workspace_for_user=lambda user_id: {
            "workspace_id": "ws-1",
            "user_id": user_id,
            "status": "pending",
        },
        ensure_workspace_async_for_user=lambda user_id: (
            {"workspace_id": "ws-1", "user_id": user_id, "status": "pending"},
            False,
        ),
    )

    result = service.exec_python("session-1", "print('hello')")

    assert result.ok is False
    assert result.error == "Workspace is still provisioning. Retry in a few seconds."


def test_exec_python_returns_workspace_error(monkeypatch) -> None:
    monkeypatch.setenv("SANDBOX_PERSISTENT_AUTO_FALLBACK_ENABLED", "0")
    manager = FakeSandboxManager()
    service = SandboxLifecycleService(
        sandbox_manager=manager,
        sandbox_lease_repository=FakeSandboxLeaseRepository(),
        get_user_id_for_session=lambda session_id: "user-1",
        get_workspace_for_user=lambda user_id: {
            "workspace_id": "ws-1",
            "user_id": user_id,
            "status": "error",
            "last_error": "iam failed",
        },
        ensure_workspace_async_for_user=None,
    )

    result = service.exec_python("session-1", "print('hello')")

    assert result.ok is False
    assert result.error == "Workspace provisioning failed (unknown_error): iam failed"


def test_exec_python_uses_ready_workspace_template(monkeypatch) -> None:
    manager = FakeSandboxManager()
    service = SandboxLifecycleService(
        sandbox_manager=manager,
        sandbox_lease_repository=FakeSandboxLeaseRepository(),
        get_user_id_for_session=lambda session_id: "user-1",
        get_workspace_for_user=lambda user_id: {
            "workspace_id": "ws-1",
            "user_id": user_id,
            "status": "ready",
            "derived_template_name": "python-runtime-template-user-a",
            "claim_namespace": "alt-default",
        },
        ensure_workspace_async_for_user=None,
    )
    monkeypatch.setattr(service, "reap_expired_leases", lambda: 0)
    monkeypatch.setattr(service, "_sandbox_template_exists", lambda **kwargs: True)
    monkeypatch.setattr(
        service, "_touch_lease", lambda lease, session_idle_ttl_seconds=None: lease
    )
    monkeypatch.setattr(
        service,
        "acquire_scope_lease",
        lambda scope_type, scope_key, runtime_config=None: _runtime(),
    )

    result = service.exec_python("session-1", "print('hello')")

    assert result.ok is True
    assert manager.exec_python_with_sandbox_calls
    runtime_config = manager.exec_python_with_sandbox_calls[0]["runtime_config"]
    assert runtime_config["template_name"] == "python-runtime-template-user-a"
    assert runtime_config["namespace"] == "alt-default"


def test_exec_python_maps_requested_base_template_to_user_derived_template(
    monkeypatch,
) -> None:
    manager = FakeSandboxManager()
    service = SandboxLifecycleService(
        sandbox_manager=manager,
        sandbox_lease_repository=FakeSandboxLeaseRepository(),
        get_user_id_for_session=lambda session_id: "user-1",
        get_workspace_for_user=lambda user_id: {
            "workspace_id": "ws-1",
            "user_id": user_id,
            "status": "ready",
            "derived_template_name": "python-runtime-template-user-primary",
            "claim_namespace": "alt-default",
        },
        resolve_workspace_template_for_user=lambda user_id, requested_template_name: (
            "python-runtime-template-user-large"
            if requested_template_name == "python-runtime-template-large"
            else "python-runtime-template-user-primary"
        ),
        ensure_workspace_async_for_user=None,
    )
    monkeypatch.setattr(service, "reap_expired_leases", lambda: 0)
    monkeypatch.setattr(service, "_sandbox_template_exists", lambda **kwargs: True)
    monkeypatch.setattr(
        service, "_touch_lease", lambda lease, session_idle_ttl_seconds=None: lease
    )
    monkeypatch.setattr(
        service,
        "acquire_scope_lease",
        lambda scope_type, scope_key, runtime_config=None: _runtime(),
    )

    result = service.exec_python(
        "session-1",
        "print('hello')",
        runtime_config={
            "profile": "persistent_workspace",
            "template_name": "python-runtime-template-large",
            "namespace": "alt-default",
        },
    )

    assert result.ok is True
    runtime_config = manager.exec_python_with_sandbox_calls[0]["runtime_config"]
    assert runtime_config["template_name"] == "python-runtime-template-user-large"


def test_exec_python_transient_profile_skips_workspace_resolution(monkeypatch) -> None:
    manager = FakeSandboxManager()
    service = SandboxLifecycleService(
        sandbox_manager=manager,
        sandbox_lease_repository=FakeSandboxLeaseRepository(),
        get_user_id_for_session=lambda session_id: "user-1",
        get_workspace_for_user=lambda user_id: (_ for _ in ()).throw(
            AssertionError("workspace lookup should be skipped for transient profile")
        ),
        ensure_workspace_async_for_user=lambda user_id, reconcile_ready=False: (
            _ for _ in ()
        ).throw(
            AssertionError("workspace ensure should be skipped for transient profile")
        ),
    )
    monkeypatch.setattr(service, "reap_expired_leases", lambda: 0)
    monkeypatch.setattr(
        service, "_touch_lease", lambda lease, session_idle_ttl_seconds=None: lease
    )

    acquire_runtime_config: list[dict[str, object]] = []
    monkeypatch.setattr(
        service,
        "acquire_scope_lease",
        lambda scope_type, scope_key, runtime_config=None: (
            acquire_runtime_config.append(dict(runtime_config or {})) or _runtime()
        ),
    )

    result = service.exec_python(
        "session-1",
        "print('hello')",
        runtime_config={
            "profile": "transient",
            "template_name": "python-runtime-template-small",
            "namespace": "alt-default",
        },
    )

    assert result.ok is True
    assert acquire_runtime_config
    assert acquire_runtime_config[0]["profile"] == "transient"
    runtime_config = manager.exec_python_with_sandbox_calls[0]["runtime_config"]
    assert runtime_config["profile"] == "transient"
    assert runtime_config["template_name"] == "python-runtime-template-small"


def test_exec_python_auto_fallbacks_to_transient_when_workspace_not_ready(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SANDBOX_PERSISTENT_AUTO_FALLBACK_ENABLED", "1")
    manager = FakeSandboxManager()
    service = SandboxLifecycleService(
        sandbox_manager=manager,
        sandbox_lease_repository=FakeSandboxLeaseRepository(),
        get_user_id_for_session=lambda session_id: "user-1",
        get_workspace_for_user=lambda user_id: None,
        ensure_workspace_async_for_user=lambda user_id, reconcile_ready=False: (
            {"workspace_id": "ws-1", "user_id": user_id, "status": "pending"},
            True,
        ),
    )
    monkeypatch.setattr(service, "reap_expired_leases", lambda: 0)
    monkeypatch.setattr(
        service, "_touch_lease", lambda lease, session_idle_ttl_seconds=None: lease
    )
    monkeypatch.setattr(
        service,
        "acquire_scope_lease",
        lambda scope_type, scope_key, runtime_config=None: _runtime(),
    )

    result = service.exec_python("session-1", "print('hello')")

    assert result.ok is True
    assert manager.exec_python_with_sandbox_calls
    runtime_config = manager.exec_python_with_sandbox_calls[0]["runtime_config"]
    assert runtime_config["profile"] == "transient"

    resolution = service.get_session_runtime_resolution("session-1")
    assert resolution is not None
    assert resolution["fallback_active"] is True
    assert resolution["transition"] == "fallback_started"


def test_exec_python_reconciles_when_ready_workspace_template_missing(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SANDBOX_PERSISTENT_AUTO_FALLBACK_ENABLED", "0")
    manager = FakeSandboxManager()
    ensure_calls: list[tuple[str, bool]] = []
    service = SandboxLifecycleService(
        sandbox_manager=manager,
        sandbox_lease_repository=FakeSandboxLeaseRepository(),
        get_user_id_for_session=lambda session_id: "user-1",
        get_workspace_for_user=lambda user_id: {
            "workspace_id": "ws-1",
            "user_id": user_id,
            "status": "ready",
            "derived_template_name": "python-runtime-template-user-missing",
            "claim_namespace": "alt-default",
        },
        ensure_workspace_async_for_user=lambda user_id, reconcile_ready=False: (
            ensure_calls.append((user_id, reconcile_ready))
            or ({"workspace_id": "ws-1", "user_id": user_id, "status": "ready"}, True)
        ),
    )
    monkeypatch.setattr(service, "_sandbox_template_exists", lambda **kwargs: False)

    result = service.exec_python("session-1", "print('hello')")

    assert result.ok is False
    assert (
        result.error
        == "Workspace template missing. Reconciliation started; retry in a few seconds."
    )
    assert ensure_calls == [("user-1", True)]


def test_sandbox_template_exists_returns_false_for_404(monkeypatch) -> None:
    manager = FakeSandboxManager()
    service = SandboxLifecycleService(
        sandbox_manager=manager,
        sandbox_lease_repository=FakeSandboxLeaseRepository(),
    )

    class _ApiException(Exception):
        def __init__(self, status: int, reason: str = "") -> None:
            super().__init__(reason)
            self.status = status

    class _CustomObjectsApi:
        def get_namespaced_custom_object(self, **kwargs):
            raise _ApiException(status=404, reason="not found")

    fake_kubernetes = SimpleNamespace(
        client=SimpleNamespace(
            CustomObjectsApi=lambda: _CustomObjectsApi(),
            exceptions=SimpleNamespace(ApiException=_ApiException),
        ),
        config=SimpleNamespace(
            load_incluster_config=lambda: None,
            load_kube_config=lambda: None,
        ),
    )
    monkeypatch.setitem(sys.modules, "kubernetes", fake_kubernetes)

    exists = service._sandbox_template_exists(
        namespace="alt-default", template_name="python-runtime-template-user-a"
    )

    assert exists is False


def test_sandbox_template_exists_fails_open_for_lookup_errors(monkeypatch) -> None:
    manager = FakeSandboxManager()
    service = SandboxLifecycleService(
        sandbox_manager=manager,
        sandbox_lease_repository=FakeSandboxLeaseRepository(),
    )

    class _ApiException(Exception):
        def __init__(self, status: int, reason: str = "") -> None:
            super().__init__(reason)
            self.status = status

    class _CustomObjectsApi:
        def get_namespaced_custom_object(self, **kwargs):
            raise _ApiException(status=500, reason="api unavailable")

    fake_kubernetes = SimpleNamespace(
        client=SimpleNamespace(
            CustomObjectsApi=lambda: _CustomObjectsApi(),
            exceptions=SimpleNamespace(ApiException=_ApiException),
        ),
        config=SimpleNamespace(
            load_incluster_config=lambda: None,
            load_kube_config=lambda: None,
        ),
    )
    monkeypatch.setitem(sys.modules, "kubernetes", fake_kubernetes)

    exists = service._sandbox_template_exists(
        namespace="alt-default", template_name="python-runtime-template-user-a"
    )

    assert exists is True


def test_acquire_scope_lease_reattaches_existing_claim(monkeypatch) -> None:
    manager = FakeSandboxManager()
    lease = SandboxLease(
        lease_id="lease-1",
        scope_type="session",
        scope_key="session-1",
        status="ready",
        claim_name="claim-1",
        template_name="python-runtime-template-user-a",
        namespace="alt-default",
        metadata={},
        created_at="2026-01-01T00:00:00+00:00",
        last_used_at="2026-01-01T00:00:00+00:00",
        expires_at="2099-01-01T00:00:00+00:00",
    )
    repo = FakeSandboxLeaseRepository(active_lease=lease.as_record())
    service = SandboxLifecycleService(
        sandbox_manager=manager,
        sandbox_lease_repository=repo,
    )
    attached_runtime = _runtime("lease-1")
    attach_calls = []
    create_calls = []

    monkeypatch.setattr(service, "_is_expired", lambda current: False)
    monkeypatch.setattr(
        service,
        "_attach_runtime",
        lambda current, **kwargs: (
            attach_calls.append((current.lease_id, current.claim_name))
            or attached_runtime
        ),
    )
    monkeypatch.setattr(
        service,
        "_create_runtime",
        lambda *args, **kwargs: create_calls.append(True) or attached_runtime,
    )

    runtime = service.acquire_scope_lease(
        "session",
        "session-1",
        runtime_config={
            "template_name": "python-runtime-template-user-a",
            "namespace": "alt-default",
        },
    )

    assert runtime is attached_runtime
    assert attach_calls == [("lease-1", "claim-1")]
    assert create_calls == []


def test_acquire_scope_lease_falls_back_when_attach_fails(monkeypatch) -> None:
    manager = FakeSandboxManager()
    lease = SandboxLease(
        lease_id="lease-1",
        scope_type="session",
        scope_key="session-1",
        status="ready",
        claim_name="claim-1",
        template_name="python-runtime-template-user-a",
        namespace="alt-default",
        metadata={},
        created_at="2026-01-01T00:00:00+00:00",
        last_used_at="2026-01-01T00:00:00+00:00",
        expires_at="2099-01-01T00:00:00+00:00",
    )
    repo = FakeSandboxLeaseRepository(active_lease=lease.as_record())
    service = SandboxLifecycleService(
        sandbox_manager=manager,
        sandbox_lease_repository=repo,
    )
    created_runtime = _runtime("lease-2")
    delete_calls = []

    monkeypatch.setattr(service, "_is_expired", lambda current: False)
    monkeypatch.setattr(
        service,
        "_attach_runtime",
        lambda current, **kwargs: (_ for _ in ()).throw(RuntimeError("attach failed")),
    )
    monkeypatch.setattr(
        service,
        "_delete_claim_best_effort",
        lambda current: delete_calls.append(current.claim_name),
    )
    monkeypatch.setattr(
        service, "_create_runtime", lambda lease, **kwargs: created_runtime
    )

    runtime = service.acquire_scope_lease(
        "session",
        "session-1",
        runtime_config={
            "template_name": "python-runtime-template-user-a",
            "namespace": "alt-default",
        },
    )

    assert runtime is created_runtime
    assert delete_calls == ["claim-1"]
    assert repo.releases
    assert repo.releases[0]["lease_id"] == "lease-1"


def test_workspace_claim_binding_is_updated_on_runtime_lifecycle(monkeypatch) -> None:
    manager = FakeSandboxManager()
    bound = []
    service = SandboxLifecycleService(
        sandbox_manager=manager,
        sandbox_lease_repository=FakeSandboxLeaseRepository(),
        bind_workspace_claim_for_session=lambda session_id, claim_name, namespace: (
            bound.append((session_id, claim_name, namespace))
        ),
    )
    runtime = _runtime("lease-1")

    service._sync_workspace_claim_binding("session", "session-1", runtime.lease)
    service._sync_workspace_claim_binding("session", "session-1", None)

    assert bound == [
        ("session-1", "claim-1", "alt-default"),
        ("session-1", None, None),
    ]
