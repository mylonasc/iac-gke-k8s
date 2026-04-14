from __future__ import annotations

import json
import logging
import secrets
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes.stream import stream as kubernetes_stream

from ..sandbox_lifecycle import SandboxLifecycleService


logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(UTC)


class TerminalServiceError(RuntimeError):
    """Base terminal service error."""


class TerminalSessionNotFoundError(TerminalServiceError):
    """Raised when terminal session is not found."""


class TerminalTokenError(TerminalServiceError):
    """Raised when terminal token is invalid or expired."""


class TerminalConfigurationError(TerminalServiceError):
    """Raised when runtime/session configuration cannot support terminal."""


@dataclass
class _TerminalConnectToken:
    token: str
    terminal_id: str
    session_id: str
    user_id: str
    created_at: datetime
    expires_at: datetime
    used: bool = False


@dataclass
class _TerminalSession:
    terminal_id: str
    session_id: str
    user_id: str
    lease_id: str | None
    claim_name: str | None
    namespace: str
    pod_name: str
    runtime_config: dict[str, Any]
    stream_client: Any
    created_at: datetime
    updated_at: datetime
    connected: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock)


class SandboxTerminalService:
    """Manages interactive terminal sessions bound to sandbox leases."""

    def __init__(
        self,
        *,
        sandbox_lifecycle: SandboxLifecycleService,
        token_ttl_seconds: int = 45,
        idle_ttl_seconds: int = 900,
        shell_command: list[str] | None = None,
        now: Callable[[], datetime] = _now_utc,
        custom_objects_api: Any | None = None,
        core_v1_api: Any | None = None,
        stream_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.sandbox_lifecycle = sandbox_lifecycle
        self.token_ttl_seconds = max(5, int(token_ttl_seconds))
        self.idle_ttl_seconds = max(30, int(idle_ttl_seconds))
        self.shell_command = list(shell_command or ["/bin/sh"])
        self.now = now
        self._custom_objects_api = custom_objects_api
        self._core_v1_api = core_v1_api
        self._stream_factory = stream_factory or kubernetes_stream
        self._kube_config_loaded = False

        self._state_lock = threading.RLock()
        self._terminal_by_id: dict[str, _TerminalSession] = {}
        self._token_by_value: dict[str, _TerminalConnectToken] = {}

    def open_terminal(
        self,
        *,
        session_id: str,
        user_id: str,
        runtime_config: dict[str, Any],
    ) -> dict[str, Any]:
        """Open terminal runtime and mint a one-time websocket token."""
        self.reap_idle_terminals()

        effective, runtime_error = self.sandbox_lifecycle.resolve_runtime_for_session(
            session_id,
            runtime_config=runtime_config,
        )
        if runtime_error:
            raise TerminalConfigurationError(runtime_error)
        if effective is None:
            raise TerminalConfigurationError("Unable to resolve sandbox runtime")

        mode = str(effective.get("mode") or "cluster").strip().lower()
        execution_model = (
            str(effective.get("execution_model") or "session").strip().lower()
        )
        if mode != "cluster":
            raise TerminalConfigurationError(
                "Interactive terminal currently supports only cluster runtime mode"
            )
        if execution_model != "session":
            raise TerminalConfigurationError(
                "Interactive terminal requires sandbox execution model 'session'"
            )

        try:
            runtime = self.sandbox_lifecycle.acquire_scope_lease(
                "session",
                session_id,
                runtime_config=effective,
            )

            claim_name = str(runtime.lease.claim_name or "").strip()
            namespace = str(runtime.lease.namespace or "").strip()
            if not claim_name or not namespace:
                raise TerminalConfigurationError(
                    "Active sandbox lease is missing claim metadata"
                )

            pod_name = self._discover_pod_name(
                claim_name=claim_name,
                namespace=namespace,
            )
            stream_client = self._open_exec_stream(
                namespace=namespace,
                pod_name=pod_name,
            )
        except TerminalConfigurationError:
            raise
        except Exception as exc:  # pragma: no cover - defensive normalization
            api_exception_cls = getattr(
                getattr(k8s_client, "exceptions", object()),
                "ApiException",
                None,
            )
            if api_exception_cls and isinstance(exc, api_exception_cls):
                status = int(getattr(exc, "status", 0) or 0)
                if status in {401, 403}:
                    raise TerminalConfigurationError(
                        "Sandbox cluster access is denied. Check kube authentication and RBAC for sandboxclaims and pods/exec."
                    ) from exc
                reason = str(getattr(exc, "reason", "") or "").strip()
                if reason:
                    raise TerminalConfigurationError(
                        f"Failed to initialize terminal sandbox: {reason}"
                    ) from exc
            raise TerminalConfigurationError(
                f"Failed to initialize terminal sandbox: {exc}"
            ) from exc

        now = self.now()
        terminal_id = str(uuid.uuid4())

        terminal = _TerminalSession(
            terminal_id=terminal_id,
            session_id=session_id,
            user_id=user_id,
            lease_id=runtime.lease.lease_id,
            claim_name=claim_name,
            namespace=namespace,
            pod_name=pod_name,
            runtime_config=dict(effective),
            stream_client=stream_client,
            created_at=now,
            updated_at=now,
        )

        token = self._mint_connect_token(
            terminal_id=terminal_id,
            session_id=session_id,
            user_id=user_id,
        )

        with self._state_lock:
            self._terminal_by_id[terminal_id] = terminal

        return {
            "terminal_id": terminal_id,
            "session_id": session_id,
            "lease_id": runtime.lease.lease_id,
            "claim_name": claim_name,
            "namespace": namespace,
            "pod_name": pod_name,
            "connect_token": token.token,
            "token_expires_at": token.expires_at.isoformat(),
        }

    def consume_connect_token(
        self,
        *,
        session_id: str,
        terminal_id: str,
        token_value: str,
    ) -> dict[str, Any]:
        self.reap_idle_terminals()
        now = self.now()
        with self._state_lock:
            token = self._token_by_value.get(token_value)
            if not token:
                raise TerminalTokenError("Terminal connect token is invalid")
            if token.used:
                raise TerminalTokenError("Terminal connect token already used")
            if now > token.expires_at:
                self._token_by_value.pop(token_value, None)
                raise TerminalTokenError("Terminal connect token expired")
            if token.session_id != session_id or token.terminal_id != terminal_id:
                raise TerminalTokenError("Terminal token/session mismatch")

            terminal = self._terminal_by_id.get(terminal_id)
            if not terminal:
                raise TerminalSessionNotFoundError("Terminal session not found")
            if terminal.connected:
                raise TerminalTokenError("Terminal session is already connected")

            token.used = True
            terminal.connected = True
            terminal.updated_at = now

            return {
                "terminal_id": terminal.terminal_id,
                "session_id": terminal.session_id,
                "user_id": terminal.user_id,
                "lease_id": terminal.lease_id,
            }

    def read_output(
        self,
        *,
        session_id: str,
        terminal_id: str,
        timeout_seconds: float = 0.2,
        max_chunks: int = 12,
    ) -> list[dict[str, str]]:
        terminal = self._require_terminal(
            terminal_id=terminal_id,
            expected_session_id=session_id,
        )
        chunks: list[dict[str, str]] = []

        with terminal.lock:
            if not terminal.stream_client.is_open():
                raise TerminalSessionNotFoundError("Terminal stream is closed")

            terminal.stream_client.update(timeout=max(0.0, timeout_seconds))

            while len(chunks) < max_chunks and terminal.stream_client.peek_stdout():
                data = terminal.stream_client.read_stdout() or ""
                if data:
                    chunks.append({"type": "stdout", "data": str(data)})

            while len(chunks) < max_chunks and terminal.stream_client.peek_stderr():
                data = terminal.stream_client.read_stderr() or ""
                if data:
                    chunks.append({"type": "stderr", "data": str(data)})

            terminal.updated_at = self.now()

        return chunks

    def write_input(
        self,
        *,
        session_id: str,
        terminal_id: str,
        data: str,
    ) -> None:
        terminal = self._require_terminal(
            terminal_id=terminal_id,
            expected_session_id=session_id,
        )
        self._touch_terminal_lease(terminal)
        with terminal.lock:
            if not terminal.stream_client.is_open():
                raise TerminalSessionNotFoundError("Terminal stream is closed")
            terminal.stream_client.write_stdin(data)
            terminal.updated_at = self.now()

    def resize_terminal(
        self,
        *,
        session_id: str,
        terminal_id: str,
        cols: int,
        rows: int,
    ) -> None:
        terminal = self._require_terminal(
            terminal_id=terminal_id,
            expected_session_id=session_id,
        )
        with terminal.lock:
            if not terminal.stream_client.is_open():
                raise TerminalSessionNotFoundError("Terminal stream is closed")
            resize_payload = json.dumps(
                {
                    "Width": max(1, int(cols)),
                    "Height": max(1, int(rows)),
                }
            )
            terminal.stream_client.write_channel(4, resize_payload)
            terminal.updated_at = self.now()

    def close_terminal(
        self,
        *,
        session_id: str,
        terminal_id: str,
    ) -> bool:
        terminal = self._require_terminal(
            terminal_id=terminal_id,
            expected_session_id=session_id,
        )
        self._close_terminal(terminal)
        return True

    def close_all(self) -> None:
        with self._state_lock:
            terminals = list(self._terminal_by_id.values())
        for terminal in terminals:
            self._close_terminal(terminal)

    def reap_idle_terminals(self) -> int:
        cutoff = self.now() - timedelta(seconds=self.idle_ttl_seconds)
        with self._state_lock:
            stale = [
                terminal
                for terminal in self._terminal_by_id.values()
                if terminal.updated_at <= cutoff
            ]
        for terminal in stale:
            self._close_terminal(terminal)
        return len(stale)

    def _touch_terminal_lease(self, terminal: _TerminalSession) -> None:
        try:
            self.sandbox_lifecycle.acquire_scope_lease(
                "session",
                terminal.session_id,
                runtime_config=terminal.runtime_config,
            )
        except Exception:
            logger.debug(
                "terminal.lease.touch_failed",
                extra={
                    "event": "terminal.lease.touch_failed",
                    "terminal_id": terminal.terminal_id,
                    "session_id": terminal.session_id,
                },
            )

    def _close_terminal(self, terminal: _TerminalSession) -> None:
        with self._state_lock:
            existing = self._terminal_by_id.pop(terminal.terminal_id, None)
            if existing is None:
                return
            token_values = [
                value
                for value, token in self._token_by_value.items()
                if token.terminal_id == terminal.terminal_id
            ]
            for value in token_values:
                self._token_by_value.pop(value, None)

        try:
            existing.stream_client.close()
        except Exception:
            return

    def _require_terminal(
        self,
        *,
        terminal_id: str,
        expected_session_id: str,
    ) -> _TerminalSession:
        with self._state_lock:
            terminal = self._terminal_by_id.get(terminal_id)
        if not terminal:
            raise TerminalSessionNotFoundError("Terminal session not found")
        if terminal.session_id != expected_session_id:
            raise TerminalSessionNotFoundError("Terminal session not found")
        return terminal

    def _mint_connect_token(
        self,
        *,
        terminal_id: str,
        session_id: str,
        user_id: str,
    ) -> _TerminalConnectToken:
        now = self.now()
        token = _TerminalConnectToken(
            token=secrets.token_urlsafe(32),
            terminal_id=terminal_id,
            session_id=session_id,
            user_id=user_id,
            created_at=now,
            expires_at=now + timedelta(seconds=self.token_ttl_seconds),
        )
        with self._state_lock:
            self._token_by_value[token.token] = token
        return token

    def _discover_pod_name(self, *, claim_name: str, namespace: str) -> str:
        sandbox_name = self._discover_sandbox_name(
            claim_name=claim_name,
            namespace=namespace,
        )
        if not sandbox_name:
            raise TerminalConfigurationError(
                f"Could not resolve sandbox for claim '{claim_name}'"
            )

        custom_api = self._custom_api()
        sandbox = custom_api.get_namespaced_custom_object(
            group="agents.x-k8s.io",
            version="v1alpha1",
            namespace=namespace,
            plural="sandboxes",
            name=sandbox_name,
        )

        status = dict(sandbox.get("status") or {})
        spec = dict(sandbox.get("spec") or {})
        metadata = dict(sandbox.get("metadata") or {})

        for key in ("podName", "runtimePodName"):
            value = status.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        pod_ref = spec.get("podRef")
        if isinstance(pod_ref, dict):
            name = pod_ref.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()

        annotations = dict(metadata.get("annotations") or {})
        for key, value in annotations.items():
            if (
                "pod-name" in str(key).lower()
                and isinstance(value, str)
                and value.strip()
            ):
                return value.strip()

        core_api = self._core_api()
        pods = core_api.list_namespaced_pod(namespace=namespace)
        for pod in list(getattr(pods, "items", []) or []):
            refs = list(
                getattr(getattr(pod, "metadata", None), "owner_references", []) or []
            )
            if any(getattr(ref, "name", None) == sandbox_name for ref in refs):
                pod_name = getattr(getattr(pod, "metadata", None), "name", None)
                if isinstance(pod_name, str) and pod_name.strip():
                    return pod_name.strip()

        raise TerminalConfigurationError(
            f"Could not resolve sandbox pod for claim '{claim_name}'"
        )

    def _discover_sandbox_name(self, *, claim_name: str, namespace: str) -> str | None:
        custom_api = self._custom_api()
        claim = custom_api.get_namespaced_custom_object(
            group="extensions.agents.x-k8s.io",
            version="v1alpha1",
            namespace=namespace,
            plural="sandboxclaims",
            name=claim_name,
        )
        status = dict(claim.get("status") or {})
        for key in ("sandboxName", "sandbox", "boundSandboxName"):
            value = status.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        payload = custom_api.list_namespaced_custom_object(
            group="agents.x-k8s.io",
            version="v1alpha1",
            namespace=namespace,
            plural="sandboxes",
        )
        for item in list(payload.get("items") or []):
            metadata = dict(item.get("metadata") or {})
            refs = list(metadata.get("ownerReferences") or [])
            if any(ref.get("name") == claim_name for ref in refs):
                name = metadata.get("name")
                if isinstance(name, str) and name.strip():
                    return name.strip()

            item_status = dict(item.get("status") or {})
            item_spec = dict(item.get("spec") or {})
            if (
                item_status.get("claimName") == claim_name
                or item_spec.get("claimName") == claim_name
            ):
                name = metadata.get("name")
                if isinstance(name, str) and name.strip():
                    return name.strip()
        return None

    def _open_exec_stream(self, *, namespace: str, pod_name: str):
        core_api = self._core_api()
        return self._stream_factory(
            core_api.connect_get_namespaced_pod_exec,
            pod_name,
            namespace,
            command=self.shell_command,
            stderr=True,
            stdin=True,
            stdout=True,
            tty=True,
            _preload_content=False,
        )

    def _load_kube_config(self) -> None:
        if self._kube_config_loaded:
            return
        try:
            k8s_config.load_incluster_config()
        except Exception:
            k8s_config.load_kube_config()
        self._kube_config_loaded = True

    def _custom_api(self):
        if self._custom_objects_api is not None:
            return self._custom_objects_api
        self._load_kube_config()
        self._custom_objects_api = k8s_client.CustomObjectsApi()
        return self._custom_objects_api

    def _core_api(self):
        if self._core_v1_api is not None:
            return self._core_v1_api
        self._load_kube_config()
        self._core_v1_api = k8s_client.CoreV1Api()
        return self._core_v1_api
