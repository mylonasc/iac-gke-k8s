from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.services.sandbox_terminal_service import (
    SandboxTerminalService,
    TerminalConfigurationError,
    TerminalSessionNotFoundError,
    TerminalTokenError,
)


@dataclass
class _FakeLease:
    lease_id: str
    claim_name: str
    namespace: str


@dataclass
class _FakeRuntime:
    lease: _FakeLease


class _FakeLifecycle:
    def __init__(self, *, runtime: dict[str, object] | None = None) -> None:
        self.runtime = runtime or {
            "mode": "cluster",
            "execution_model": "session",
            "namespace": "alt-default",
            "template_name": "python-runtime-template-small",
            "session_idle_ttl_seconds": 1800,
        }
        self.acquire_calls: list[tuple[str, str, dict[str, object] | None]] = []

    def resolve_runtime_for_session(self, session_id, *, runtime_config=None):
        return dict(self.runtime), None

    def acquire_scope_lease(self, scope_type, scope_key, *, runtime_config=None):
        self.acquire_calls.append((scope_type, scope_key, runtime_config))
        return _FakeRuntime(
            lease=_FakeLease(
                lease_id="lease-1",
                claim_name="sandbox-claim-1",
                namespace="alt-default",
            )
        )


class _FailingLifecycle(_FakeLifecycle):
    def acquire_scope_lease(self, scope_type, scope_key, *, runtime_config=None):
        raise RuntimeError("boom")


class _FakeCustomObjectsApi:
    def get_namespaced_custom_object(self, *, group, version, namespace, plural, name):
        if plural == "sandboxclaims":
            return {"status": {"sandboxName": "sandbox-1"}}
        if plural == "sandboxes":
            return {"status": {"podName": "sandbox-pod-1"}}
        raise AssertionError(f"unexpected plural {plural}")

    def list_namespaced_custom_object(self, *, group, version, namespace, plural):
        if plural != "sandboxes":
            raise AssertionError(f"unexpected plural {plural}")
        return {"items": []}


class _FakeCoreV1Api:
    def connect_get_namespaced_pod_exec(self):
        raise AssertionError("stream factory should intercept this call")

    def list_namespaced_pod(self, namespace):
        return type("_Pods", (), {"items": []})()


class _FakeStreamClient:
    def __init__(self) -> None:
        self.open = True
        self.stdout_chunks: list[str] = ["hello from sandbox\n"]
        self.stderr_chunks: list[str] = []
        self.stdin_writes: list[str] = []
        self.resize_writes: list[tuple[int, str]] = []

    def is_open(self):
        return self.open

    def update(self, timeout=0):
        return None

    def peek_stdout(self):
        return bool(self.stdout_chunks)

    def read_stdout(self):
        return self.stdout_chunks.pop(0)

    def peek_stderr(self):
        return bool(self.stderr_chunks)

    def read_stderr(self):
        return self.stderr_chunks.pop(0)

    def write_stdin(self, data):
        self.stdin_writes.append(data)

    def write_channel(self, channel, payload):
        self.resize_writes.append((channel, payload))

    def close(self):
        self.open = False


def test_terminal_service_opens_and_connects_token_once() -> None:
    fake_stream = _FakeStreamClient()
    service = SandboxTerminalService(
        sandbox_lifecycle=_FakeLifecycle(),
        custom_objects_api=_FakeCustomObjectsApi(),
        core_v1_api=_FakeCoreV1Api(),
        stream_factory=lambda *args, **kwargs: fake_stream,
    )

    opened = service.open_terminal(
        session_id="session-1",
        user_id="user-1",
        runtime_config={"toolkits": {"sandbox": {"runtime": {"mode": "cluster"}}}},
    )

    assert opened["terminal_id"]
    assert opened["connect_token"]
    assert opened["pod_name"] == "sandbox-pod-1"

    connected = service.consume_connect_token(
        session_id="session-1",
        terminal_id=opened["terminal_id"],
        token_value=opened["connect_token"],
    )
    assert connected["terminal_id"] == opened["terminal_id"]

    with pytest.raises(TerminalTokenError):
        service.consume_connect_token(
            session_id="session-1",
            terminal_id=opened["terminal_id"],
            token_value=opened["connect_token"],
        )


def test_terminal_service_reads_writes_and_closes() -> None:
    fake_stream = _FakeStreamClient()
    service = SandboxTerminalService(
        sandbox_lifecycle=_FakeLifecycle(),
        custom_objects_api=_FakeCustomObjectsApi(),
        core_v1_api=_FakeCoreV1Api(),
        stream_factory=lambda *args, **kwargs: fake_stream,
    )
    opened = service.open_terminal(
        session_id="session-2",
        user_id="user-2",
        runtime_config={"toolkits": {"sandbox": {"runtime": {"mode": "cluster"}}}},
    )
    terminal_id = opened["terminal_id"]

    service.write_input(
        session_id="session-2",
        terminal_id=terminal_id,
        data="pwd\n",
    )
    chunks = service.read_output(session_id="session-2", terminal_id=terminal_id)
    assert chunks[0]["type"] == "stdout"
    assert "hello from sandbox" in chunks[0]["data"]

    service.resize_terminal(
        session_id="session-2",
        terminal_id=terminal_id,
        cols=120,
        rows=30,
    )
    assert fake_stream.stdin_writes == ["pwd\n"]
    assert fake_stream.resize_writes

    assert service.close_terminal(session_id="session-2", terminal_id=terminal_id)
    with pytest.raises(TerminalSessionNotFoundError):
        service.read_output(session_id="session-2", terminal_id=terminal_id)


def test_terminal_service_rejects_unsupported_runtime() -> None:
    service = SandboxTerminalService(
        sandbox_lifecycle=_FakeLifecycle(
            runtime={
                "mode": "cluster",
                "execution_model": "ephemeral",
                "namespace": "alt-default",
                "template_name": "python-runtime-template-small",
            }
        ),
        custom_objects_api=_FakeCustomObjectsApi(),
        core_v1_api=_FakeCoreV1Api(),
        stream_factory=lambda *args, **kwargs: _FakeStreamClient(),
    )

    with pytest.raises(TerminalConfigurationError):
        service.open_terminal(
            session_id="session-3",
            user_id="user-3",
            runtime_config={},
        )


def test_terminal_connect_token_expires() -> None:
    fake_stream = _FakeStreamClient()
    now_ref = {"value": datetime(2026, 1, 1, tzinfo=UTC)}

    def _now() -> datetime:
        return now_ref["value"]

    service = SandboxTerminalService(
        sandbox_lifecycle=_FakeLifecycle(),
        token_ttl_seconds=5,
        now=_now,
        custom_objects_api=_FakeCustomObjectsApi(),
        core_v1_api=_FakeCoreV1Api(),
        stream_factory=lambda *args, **kwargs: fake_stream,
    )
    opened = service.open_terminal(
        session_id="session-4",
        user_id="user-4",
        runtime_config={},
    )

    now_ref["value"] = now_ref["value"] + timedelta(seconds=6)
    with pytest.raises(TerminalTokenError):
        service.consume_connect_token(
            session_id="session-4",
            terminal_id=opened["terminal_id"],
            token_value=opened["connect_token"],
        )


def test_terminal_service_wraps_runtime_bootstrap_errors() -> None:
    service = SandboxTerminalService(
        sandbox_lifecycle=_FailingLifecycle(),
        custom_objects_api=_FakeCustomObjectsApi(),
        core_v1_api=_FakeCoreV1Api(),
        stream_factory=lambda *args, **kwargs: _FakeStreamClient(),
    )

    with pytest.raises(TerminalConfigurationError) as exc_info:
        service.open_terminal(
            session_id="session-5",
            user_id="user-5",
            runtime_config={},
        )

    assert "Failed to initialize terminal sandbox" in str(exc_info.value)
