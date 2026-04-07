from __future__ import annotations

import threading

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
    assert result.error == "Workspace provisioning failed: iam failed"


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
