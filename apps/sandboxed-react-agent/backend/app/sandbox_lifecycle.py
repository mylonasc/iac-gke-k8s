"""Lifecycle orchestration for reusable sandbox executions.

This module introduces a lease abstraction on top of sandbox execution so the
application can reuse sandboxes for multi-step workflows. The initial policy is
session-scoped reuse, while the data model is general enough for future
scope types (for example named or user-scoped leases).
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from k8s_agent_sandbox import SandboxClient

from .repositories.sandbox_lease_repository import SandboxLeaseRepository
from .sandbox_manager import SandboxExecutionResult, SandboxManager


logger = logging.getLogger(__name__)


class WorkspaceNotReadyError(RuntimeError):
    """Raised when a sandbox workspace has not finished provisioning yet."""


class WorkspaceProvisioningError(RuntimeError):
    """Raised when the sandbox workspace provisioning state is terminal/error."""


def _now_utc() -> datetime:
    """Return current UTC timestamp as an aware datetime."""
    return datetime.now(UTC)


def _to_iso(value: datetime) -> str:
    """Serialize an aware datetime into an ISO-8601 string."""
    return value.isoformat()


def _from_iso(value: str) -> datetime:
    """Parse an ISO-8601 datetime string into an aware UTC datetime."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@dataclass
class SandboxLease:
    """Durable metadata record for an active or historical sandbox lease."""

    lease_id: str
    scope_type: str
    scope_key: str
    status: str
    claim_name: str | None
    template_name: str
    namespace: str
    metadata: dict[str, Any]
    created_at: str
    last_used_at: str
    expires_at: str
    released_at: str | None = None
    last_error: str | None = None

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "SandboxLease":
        """Build a lease object from a persistence record."""
        return cls(
            lease_id=record["lease_id"],
            scope_type=record["scope_type"],
            scope_key=record["scope_key"],
            status=record["status"],
            claim_name=record.get("claim_name"),
            template_name=record["template_name"],
            namespace=record["namespace"],
            metadata=record.get("metadata") or {},
            created_at=record["created_at"],
            last_used_at=record["last_used_at"],
            expires_at=record["expires_at"],
            released_at=record.get("released_at"),
            last_error=record.get("last_error"),
        )

    def as_record(self) -> dict[str, Any]:
        """Serialize lease state for database upsert."""
        return {
            "lease_id": self.lease_id,
            "scope_type": self.scope_type,
            "scope_key": self.scope_key,
            "status": self.status,
            "claim_name": self.claim_name,
            "template_name": self.template_name,
            "namespace": self.namespace,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "expires_at": self.expires_at,
            "released_at": self.released_at,
            "last_error": self.last_error,
        }


@dataclass
class _LeaseRuntime:
    """In-memory runtime handle for a lease-backed sandbox client."""

    lease: SandboxLease
    client: SandboxClient
    lock: threading.RLock = field(default_factory=threading.RLock)


class SandboxLifecycleService:
    """Coordinates lease acquisition/reuse/release for sandbox execution."""

    def __init__(
        self,
        sandbox_manager: SandboxManager,
        sandbox_lease_repository: SandboxLeaseRepository,
        get_user_id_for_session: Callable[[str], str | None] | None = None,
        get_workspace_for_user: Callable[[str], dict[str, Any] | None] | None = None,
        ensure_workspace_async_for_user: Callable[..., tuple[dict[str, Any], bool]]
        | None = None,
        bind_workspace_claim_for_session: Callable[[str, str | None, str | None], None]
        | None = None,
    ) -> None:
        """Initialize lifecycle orchestration dependencies.

        Args:
            sandbox_manager: Low-level sandbox execution manager.
            sandbox_lease_repository: Persistence adapter for lease records.
            get_user_id_for_session: Optional resolver from session id to user id.
            get_workspace_for_user: Optional resolver for workspace snapshot lookup.
            ensure_workspace_async_for_user: Optional async workspace ensure callback.
            bind_workspace_claim_for_session: Optional callback to sync claim binding.
        """
        self.sandbox_manager = sandbox_manager
        self.sandbox_lease_repository = sandbox_lease_repository
        self.get_user_id_for_session = get_user_id_for_session
        self.get_workspace_for_user = get_workspace_for_user
        self.ensure_workspace_async_for_user = ensure_workspace_async_for_user
        self.bind_workspace_claim_for_session = bind_workspace_claim_for_session

        self.execution_model = (
            os.getenv("SANDBOX_EXECUTION_MODEL", "session").strip().lower()
        )
        if self.execution_model not in {"ephemeral", "session"}:
            self.execution_model = "session"

        self.session_idle_ttl_seconds = int(
            os.getenv("SANDBOX_SESSION_IDLE_TTL_SECONDS", "1800")
        )
        self.max_lease_ttl_seconds = int(
            os.getenv("SANDBOX_MAX_LEASE_TTL_SECONDS", "21600")
        )

        self._state_lock = threading.RLock()
        self._scope_lock_by_scope: dict[tuple[str, str], threading.Lock] = {}
        self._runtime_by_lease_id: dict[str, _LeaseRuntime] = {}
        self._lease_id_by_scope: dict[tuple[str, str], str] = {}
        self._load_active_scope_index()

        logger.info(
            "sandbox.lifecycle.initialized",
            extra={
                "event": "sandbox.lifecycle.initialized",
                "sandbox_execution_model": self.execution_model,
                "session_idle_ttl_seconds": self.session_idle_ttl_seconds,
                "max_lease_ttl_seconds": self.max_lease_ttl_seconds,
            },
        )

    def get_config(self) -> dict[str, int | str]:
        """Return lifecycle-related runtime configuration.

        Returns:
            Lifecycle configuration values used by runtime and toolkit defaults.
        """
        return {
            "execution_model": self.execution_model,
            "session_idle_ttl_seconds": self.session_idle_ttl_seconds,
            "max_lease_ttl_seconds": self.max_lease_ttl_seconds,
        }

    def update_config(
        self,
        *,
        execution_model: str | None = None,
        session_idle_ttl_seconds: int | None = None,
    ) -> None:
        """Update lifecycle execution settings at runtime.

        Args:
            execution_model: Execution model (``ephemeral`` or ``session``).
            session_idle_ttl_seconds: Session lease idle TTL in seconds.

        Raises:
            ValueError: If any supplied value is invalid.
        """
        if execution_model is not None:
            normalized = execution_model.strip().lower()
            if normalized not in {"ephemeral", "session"}:
                raise ValueError(
                    "sandbox_execution_model must be 'ephemeral' or 'session'"
                )
            self.execution_model = normalized

        if session_idle_ttl_seconds is not None:
            if session_idle_ttl_seconds <= 0:
                raise ValueError("sandbox_session_idle_ttl_seconds must be > 0")
            self.session_idle_ttl_seconds = session_idle_ttl_seconds

    def _load_active_scope_index(self) -> None:
        """Build in-memory scope index from persisted active leases."""
        for record in self.sandbox_lease_repository.list_active():
            lease = SandboxLease.from_record(record)
            self._lease_id_by_scope[(lease.scope_type, lease.scope_key)] = (
                lease.lease_id
            )

    def _scope_lock_for(self, scope_type: str, scope_key: str) -> threading.Lock:
        scope = (scope_type, scope_key)
        with self._state_lock:
            lock = self._scope_lock_by_scope.get(scope)
            if lock is None:
                lock = threading.Lock()
                self._scope_lock_by_scope[scope] = lock
            return lock

    def _runtime_for_lease(self, lease_id: str) -> _LeaseRuntime | None:
        with self._state_lock:
            return self._runtime_by_lease_id.get(lease_id)

    def _register_runtime(self, runtime: _LeaseRuntime) -> None:
        with self._state_lock:
            self._runtime_by_lease_id[runtime.lease.lease_id] = runtime
            self._lease_id_by_scope[
                (runtime.lease.scope_type, runtime.lease.scope_key)
            ] = runtime.lease.lease_id

    def _remove_runtime_index(self, lease: SandboxLease) -> None:
        with self._state_lock:
            self._runtime_by_lease_id.pop(lease.lease_id, None)
            self._lease_id_by_scope.pop((lease.scope_type, lease.scope_key), None)

    def _ttl_bounds(self) -> tuple[datetime, datetime]:
        """Calculate keepalive and hard-expiry bounds.

        Returns:
            Tuple of idle-expiry and hard-expiry timestamps.
        """
        now = _now_utc()
        return (
            now + timedelta(seconds=self.session_idle_ttl_seconds),
            now + timedelta(seconds=self.max_lease_ttl_seconds),
        )

    def _effective_runtime(
        self, runtime_config: dict[str, object] | None
    ) -> dict[str, object]:
        """Resolve effective runtime values from defaults and request overrides.

        Args:
            runtime_config: Optional partial runtime overrides.

        Returns:
            Effective runtime dictionary.
        """
        defaults: dict[str, object] = {
            "mode": self.sandbox_manager.mode,
            "profile": "persistent_workspace",
            "api_url": self.sandbox_manager.api_url,
            "template_name": self.sandbox_manager.template_name,
            "namespace": self.sandbox_manager.namespace,
            "server_port": self.sandbox_manager.server_port,
            "sandbox_ready_timeout": self.sandbox_manager.sandbox_ready_timeout,
            "gateway_ready_timeout": self.sandbox_manager.gateway_ready_timeout,
            "max_output_chars": self.sandbox_manager.max_output_chars,
            "local_timeout_seconds": self.sandbox_manager.local_timeout_seconds,
            "execution_model": self.execution_model,
            "session_idle_ttl_seconds": self.session_idle_ttl_seconds,
            "max_lease_ttl_seconds": self.max_lease_ttl_seconds,
        }
        if not isinstance(runtime_config, dict):
            return defaults
        merged = dict(defaults)
        for key in defaults:
            if runtime_config.get(key) is not None:
                merged[key] = runtime_config[key]
        return merged

    def _workspace_runtime_overrides(
        self, session_id: str, effective: dict[str, object]
    ) -> dict[str, object]:
        """Apply workspace-aware runtime routing for persistent profile.

        Args:
            session_id: Session identifier.
            effective: Effective runtime dictionary.

        Returns:
            Updated runtime dictionary.

        Raises:
            WorkspaceNotReadyError: If workspace is provisioning/reconciling.
            WorkspaceProvisioningError: If workspace is in terminal error state.
        """
        mode = str(effective["mode"])
        if mode == "local":
            return effective

        profile = (
            str(effective.get("profile") or "persistent_workspace").strip().lower()
        )
        if profile == "transient":
            return effective

        if self.get_user_id_for_session is None:
            return effective

        user_id = str(self.get_user_id_for_session(session_id) or "").strip()
        if not user_id:
            return effective

        workspace = None
        if self.get_workspace_for_user is not None:
            workspace = self.get_workspace_for_user(user_id)

        if workspace is None and self.ensure_workspace_async_for_user is not None:
            workspace, started = self._ensure_workspace_async_for_user(
                user_id,
                reconcile_ready=False,
            )
            if workspace and str(workspace.get("status") or "") == "ready":
                pass
            elif started:
                raise WorkspaceNotReadyError(
                    "Workspace provisioning started. Retry in a few seconds."
                )

        if not workspace:
            return effective

        status = str(workspace.get("status") or "")
        if status == "ready":
            updated = dict(effective)
            template_name = str(workspace.get("derived_template_name") or "").strip()
            namespace = str(workspace.get("claim_namespace") or "").strip()
            if template_name:
                updated["template_name"] = template_name
            if namespace:
                updated["namespace"] = namespace

            resolved_template = str(updated.get("template_name") or "").strip()
            resolved_namespace = str(updated.get("namespace") or "").strip()
            if (
                resolved_template
                and resolved_namespace
                and not self._sandbox_template_exists(
                    namespace=resolved_namespace,
                    template_name=resolved_template,
                )
            ):
                logger.warning(
                    "workspace.template_missing",
                    extra={
                        "event": "workspace.template_missing",
                        "user_id": user_id,
                        "workspace_id": workspace.get("workspace_id"),
                        "template_name": resolved_template,
                        "namespace": resolved_namespace,
                    },
                )
                if self.ensure_workspace_async_for_user is not None:
                    _, started = self._ensure_workspace_async_for_user(
                        user_id,
                        reconcile_ready=True,
                    )
                    if started:
                        logger.info(
                            "workspace.reconcile.started",
                            extra={
                                "event": "workspace.reconcile.started",
                                "user_id": user_id,
                                "workspace_id": workspace.get("workspace_id"),
                                "template_name": resolved_template,
                                "namespace": resolved_namespace,
                            },
                        )
                        raise WorkspaceNotReadyError(
                            "Workspace template missing. Reconciliation started; retry in a few seconds."
                        )
                    logger.warning(
                        "workspace.reconcile.not_started",
                        extra={
                            "event": "workspace.reconcile.not_started",
                            "user_id": user_id,
                            "workspace_id": workspace.get("workspace_id"),
                            "template_name": resolved_template,
                            "namespace": resolved_namespace,
                        },
                    )
                    raise WorkspaceNotReadyError(
                        "Workspace template missing. Reconciliation in progress; retry in a few seconds."
                    )
                raise WorkspaceProvisioningError(
                    f"Workspace template '{resolved_template}' not found in namespace '{resolved_namespace}'."
                )
            return updated

        if status in {"pending", "reconciling"}:
            reason = str(workspace.get("status_reason") or "").strip()
            reason_suffix = f" (reason={reason})" if reason else ""
            raise WorkspaceNotReadyError(
                f"Workspace is still provisioning. Retry in a few seconds.{reason_suffix}"
            )

        if status == "error":
            detail = str(workspace.get("last_error") or "unknown error")
            reason = str(workspace.get("status_reason") or "unknown_error")
            raise WorkspaceProvisioningError(
                f"Workspace provisioning failed ({reason}): {detail}"
            )

        return effective

    def _ensure_workspace_async_for_user(
        self, user_id: str, *, reconcile_ready: bool
    ) -> tuple[dict[str, Any], bool]:
        """Call workspace async ensure callback with compatibility fallback.

        Args:
            user_id: User identifier.
            reconcile_ready: Whether reconcile should run for ready workspace.

        Returns:
            Tuple of workspace snapshot and started flag.
        """
        if self.ensure_workspace_async_for_user is None:
            return {}, False
        try:
            return self.ensure_workspace_async_for_user(
                user_id,
                reconcile_ready=reconcile_ready,
            )
        except TypeError:
            return self.ensure_workspace_async_for_user(user_id)

    def _sandbox_template_exists(self, *, namespace: str, template_name: str) -> bool:
        """Check whether a SandboxTemplate exists in Kubernetes.

        The method fails open for non-404 API errors to avoid false negatives
        during transient control-plane issues.

        Args:
            namespace: Kubernetes namespace.
            template_name: SandboxTemplate name.

        Returns:
            ``True`` when template exists or lookup is inconclusive, ``False`` on
            authoritative 404.
        """
        try:
            from kubernetes import client, config

            try:
                config.load_incluster_config()
            except Exception:
                config.load_kube_config()

            api = client.CustomObjectsApi()
            try:
                api.get_namespaced_custom_object(
                    group="extensions.agents.x-k8s.io",
                    version="v1alpha1",
                    namespace=namespace,
                    plural="sandboxtemplates",
                    name=template_name,
                )
                return True
            except client.exceptions.ApiException as exc:
                if getattr(exc, "status", None) == 404:
                    return False
                logger.warning(
                    "workspace.template_lookup_failed",
                    extra={
                        "event": "workspace.template_lookup_failed",
                        "template_name": template_name,
                        "namespace": namespace,
                        "status": getattr(exc, "status", None),
                        "error": str(exc),
                    },
                )
                return True
        except Exception as exc:
            logger.warning(
                "workspace.template_lookup_failed",
                extra={
                    "event": "workspace.template_lookup_failed",
                    "template_name": template_name,
                    "namespace": namespace,
                    "error": str(exc),
                },
            )
            return True

    def _sync_workspace_claim_binding(
        self, scope_type: str, scope_key: str, lease: SandboxLease | None
    ) -> None:
        """Synchronize claim metadata back to workspace/session view.

        Args:
            scope_type: Lease scope type.
            scope_key: Lease scope key.
            lease: Lease object or ``None`` when clearing binding.
        """
        if scope_type != "session" or self.bind_workspace_claim_for_session is None:
            return
        self.bind_workspace_claim_for_session(
            scope_key,
            lease.claim_name if lease else None,
            lease.namespace if lease and lease.claim_name else None,
        )

    def _touch_lease(
        self, lease: SandboxLease, *, session_idle_ttl_seconds: int | None = None
    ) -> SandboxLease:
        """Refresh lease activity timestamps and persist update.

        Args:
            lease: Lease to refresh.
            session_idle_ttl_seconds: Optional per-call idle TTL override.

        Returns:
            Updated lease.
        """
        now = _now_utc()
        idle_ttl = (
            int(session_idle_ttl_seconds)
            if session_idle_ttl_seconds is not None
            else self.session_idle_ttl_seconds
        )
        idle_expiry = now + timedelta(seconds=idle_ttl)
        hard_expiry = now + timedelta(seconds=self.max_lease_ttl_seconds)

        created = _from_iso(lease.created_at)
        created_cap = created + timedelta(seconds=self.max_lease_ttl_seconds)
        lease.last_used_at = _to_iso(now)
        lease.expires_at = _to_iso(min(idle_expiry, hard_expiry, created_cap))
        self.sandbox_lease_repository.upsert(lease.as_record())
        return lease

    def _build_fresh_lease(
        self,
        scope_type: str,
        scope_key: str,
        *,
        template_name: str,
        namespace: str,
        session_idle_ttl_seconds: int,
    ) -> SandboxLease:
        """Create a fresh lease model before runtime acquisition.

        Args:
            scope_type: Scope type (for example ``session``).
            scope_key: Scope key.
            template_name: Template name to use for claim acquisition.
            namespace: Namespace for claim.
            session_idle_ttl_seconds: Initial idle TTL.

        Returns:
            New lease object in pending state.
        """
        now = _now_utc()
        idle_expiry = now + timedelta(seconds=session_idle_ttl_seconds)
        return SandboxLease(
            lease_id=f"lease-{uuid.uuid4().hex}",
            scope_type=scope_type,
            scope_key=scope_key,
            status="pending",
            claim_name=None,
            template_name=template_name,
            namespace=namespace,
            metadata={},
            created_at=_to_iso(now),
            last_used_at=_to_iso(now),
            expires_at=_to_iso(idle_expiry),
            released_at=None,
            last_error=None,
        )

    def _create_runtime(
        self,
        lease: SandboxLease,
        *,
        api_url: str,
        server_port: int,
        sandbox_ready_timeout: int,
        gateway_ready_timeout: int,
        session_idle_ttl_seconds: int,
    ) -> _LeaseRuntime:
        """Create and enter a sandbox client for provided lease.

        Args:
            lease: Lease metadata object.
            api_url: Sandbox router URL.
            server_port: Sandbox runtime server port.
            sandbox_ready_timeout: Sandbox readiness timeout.
            gateway_ready_timeout: Gateway readiness timeout.
            session_idle_ttl_seconds: Lease idle TTL for keepalive updates.

        Returns:
            Runtime wrapper with entered sandbox client.
        """
        logger.info(
            "lease.acquire.start",
            extra={
                "event": "lease.acquire.start",
                "lease_id": lease.lease_id,
                "scope_type": lease.scope_type,
                "scope_key": lease.scope_key,
                "template_name": lease.template_name,
                "namespace": lease.namespace,
            },
        )

        client = SandboxClient(
            template_name=lease.template_name,
            api_url=api_url,
            namespace=lease.namespace,
            server_port=server_port,
            sandbox_ready_timeout=sandbox_ready_timeout,
            gateway_ready_timeout=gateway_ready_timeout,
        )
        try:
            client.__enter__()
        except Exception as exc:
            claim_name = getattr(client, "claim_name", None)
            if claim_name:
                lease.claim_name = claim_name
                logger.warning(
                    "lease.acquire.watch_failed",
                    extra={
                        "event": "lease.acquire.watch_failed",
                        "lease_id": lease.lease_id,
                        "scope_type": lease.scope_type,
                        "scope_key": lease.scope_key,
                        "claim_name": claim_name,
                        "error": str(exc),
                    },
                )
                if self._wait_for_claim_ready(
                    lease, timeout_seconds=sandbox_ready_timeout
                ):
                    self._cleanup_attach_client(client)
                    return self._attach_runtime(
                        lease,
                        api_url=api_url,
                        server_port=server_port,
                        sandbox_ready_timeout=sandbox_ready_timeout,
                        gateway_ready_timeout=gateway_ready_timeout,
                        session_idle_ttl_seconds=session_idle_ttl_seconds,
                    )
            self._cleanup_attach_client(client)
            raise

        lease.claim_name = getattr(client, "claim_name", None)
        lease.status = "ready"
        lease.last_error = None
        self._touch_lease(lease, session_idle_ttl_seconds=session_idle_ttl_seconds)

        runtime = _LeaseRuntime(lease=lease, client=client)
        self._register_runtime(runtime)
        self._sync_workspace_claim_binding(lease.scope_type, lease.scope_key, lease)

        logger.info(
            "lease.acquire.end",
            extra={
                "event": "lease.acquire.end",
                "lease_id": lease.lease_id,
                "scope_type": lease.scope_type,
                "scope_key": lease.scope_key,
                "claim_name": lease.claim_name,
            },
        )
        return runtime

    def _cleanup_attach_client(self, client: SandboxClient) -> None:
        """Best-effort cleanup for partially attached sandbox client.

        Args:
            client: Sandbox client instance.
        """
        port_forward_process = getattr(client, "port_forward_process", None)
        if port_forward_process is None:
            return
        try:
            port_forward_process.terminate()
            try:
                port_forward_process.wait(timeout=2)
            except Exception:
                port_forward_process.kill()
        except Exception:
            logger.debug("lease.attach.cleanup_failed", exc_info=True)

    def _claim_exists(self, lease: SandboxLease) -> bool:
        """Check whether lease claim still exists in cluster.

        Args:
            lease: Lease metadata.

        Returns:
            ``True`` when claim lookup succeeds.
        """
        if not lease.claim_name:
            return False
        try:
            from kubernetes import client, config

            try:
                config.load_incluster_config()
            except Exception:
                config.load_kube_config()

            api = client.CustomObjectsApi()
            api.get_namespaced_custom_object(
                group="extensions.agents.x-k8s.io",
                version="v1alpha1",
                namespace=lease.namespace,
                plural="sandboxclaims",
                name=lease.claim_name,
            )
            return True
        except Exception:
            return False

    def _wait_for_claim_ready(
        self, lease: SandboxLease, *, timeout_seconds: int
    ) -> bool:
        """Poll claim conditions until Ready=True or timeout.

        Args:
            lease: Lease metadata containing claim name.
            timeout_seconds: Poll timeout seconds.

        Returns:
            ``True`` when claim becomes ready.
        """
        if not lease.claim_name:
            return False
        try:
            from kubernetes import client, config

            try:
                config.load_incluster_config()
            except Exception:
                config.load_kube_config()

            api = client.CustomObjectsApi()
            deadline = time.monotonic() + max(1, timeout_seconds)
            while time.monotonic() < deadline:
                claim = api.get_namespaced_custom_object(
                    group="extensions.agents.x-k8s.io",
                    version="v1alpha1",
                    namespace=lease.namespace,
                    plural="sandboxclaims",
                    name=lease.claim_name,
                )
                status = claim.get("status") or {}
                for condition in list(status.get("conditions") or []):
                    if (
                        condition.get("type") == "Ready"
                        and condition.get("status") == "True"
                    ):
                        return True
                time.sleep(2)
        except Exception:
            logger.debug("lease.claim_ready_poll_failed", exc_info=True)
        return False

    def _attach_runtime(
        self,
        lease: SandboxLease,
        *,
        api_url: str,
        server_port: int,
        sandbox_ready_timeout: int,
        gateway_ready_timeout: int,
        session_idle_ttl_seconds: int,
    ) -> _LeaseRuntime:
        """Attach runtime client to an existing claim-backed lease.

        Args:
            lease: Existing persisted lease with claim name.
            api_url: Sandbox router URL.
            server_port: Sandbox runtime server port.
            sandbox_ready_timeout: Sandbox readiness timeout.
            gateway_ready_timeout: Gateway readiness timeout.
            session_idle_ttl_seconds: Lease idle TTL.

        Returns:
            Runtime wrapper with attached client.

        Raises:
            RuntimeError: If claim metadata is missing or claim no longer exists.
        """
        if not lease.claim_name:
            raise RuntimeError("cannot attach runtime without claim_name")
        if not self._claim_exists(lease):
            raise RuntimeError(f"sandbox claim {lease.claim_name} no longer exists")

        logger.info(
            "lease.attach.start",
            extra={
                "event": "lease.attach.start",
                "lease_id": lease.lease_id,
                "scope_type": lease.scope_type,
                "scope_key": lease.scope_key,
                "claim_name": lease.claim_name,
                "template_name": lease.template_name,
                "namespace": lease.namespace,
            },
        )

        client = SandboxClient(
            template_name=lease.template_name,
            api_url=api_url,
            namespace=lease.namespace,
            server_port=server_port,
            sandbox_ready_timeout=sandbox_ready_timeout,
            gateway_ready_timeout=gateway_ready_timeout,
        )
        client.claim_name = lease.claim_name

        try:
            client._wait_for_sandbox_ready()
            if client.base_url:
                pass
            elif client.gateway_name:
                client._wait_for_gateway_ip()
            else:
                client._start_and_wait_for_port_forward()
        except Exception:
            self._cleanup_attach_client(client)
            raise

        lease.status = "ready"
        lease.last_error = None
        self._touch_lease(lease, session_idle_ttl_seconds=session_idle_ttl_seconds)

        runtime = _LeaseRuntime(lease=lease, client=client)
        self._register_runtime(runtime)
        self._sync_workspace_claim_binding(lease.scope_type, lease.scope_key, lease)

        logger.info(
            "lease.attach.end",
            extra={
                "event": "lease.attach.end",
                "lease_id": lease.lease_id,
                "scope_type": lease.scope_type,
                "scope_key": lease.scope_key,
                "claim_name": lease.claim_name,
            },
        )
        return runtime

    def _lookup_scope_lease(
        self, scope_type: str, scope_key: str
    ) -> SandboxLease | None:
        """Resolve persisted active lease for scope.

        Args:
            scope_type: Scope type.
            scope_key: Scope key.

        Returns:
            Active lease object if found.
        """
        with self._state_lock:
            cached_id = self._lease_id_by_scope.get((scope_type, scope_key))
        if cached_id:
            record = self.sandbox_lease_repository.get(cached_id)
            if record and record.get("status") in {"pending", "ready"}:
                return SandboxLease.from_record(record)

        record = self.sandbox_lease_repository.get_active_for_scope(
            scope_type, scope_key
        )
        if not record:
            return None
        lease = SandboxLease.from_record(record)
        with self._state_lock:
            self._lease_id_by_scope[(scope_type, scope_key)] = lease.lease_id
        return lease

    def _is_expired(self, lease: SandboxLease) -> bool:
        """Determine whether lease expiry has passed.

        Args:
            lease: Lease metadata.

        Returns:
            ``True`` if lease is expired.
        """
        return _from_iso(lease.expires_at) <= _now_utc()

    def _release_runtime_handle(
        self, runtime: _LeaseRuntime, *, status: str, error_text: str | None = None
    ) -> None:
        """Close runtime handle and mark lease terminal.

        Args:
            runtime: Active runtime wrapper.
            status: Terminal lease status.
            error_text: Optional error text to persist.
        """
        lease = runtime.lease
        released_at = _to_iso(_now_utc())
        try:
            runtime.client.__exit__(None, None, None)
        except Exception as exc:
            logger.exception(
                "lease.release.error",
                extra={
                    "event": "lease.release.error",
                    "lease_id": lease.lease_id,
                    "claim_name": lease.claim_name,
                    "error": str(exc),
                },
            )
            error_text = error_text or str(exc)

        self.sandbox_lease_repository.mark_released(
            lease.lease_id,
            released_at=released_at,
            status=status,
            last_error=error_text,
        )
        self._remove_runtime_index(lease)
        self._sync_workspace_claim_binding(lease.scope_type, lease.scope_key, None)

        logger.info(
            "lease.release",
            extra={
                "event": "lease.release",
                "lease_id": lease.lease_id,
                "scope_type": lease.scope_type,
                "scope_key": lease.scope_key,
                "claim_name": lease.claim_name,
                "status": status,
                "error": error_text,
            },
        )

    def _delete_claim_best_effort(self, lease: SandboxLease) -> None:
        """Best-effort deletion of claim for detached persisted leases.

        Args:
            lease: Lease metadata.
        """
        if not lease.claim_name:
            return
        try:
            from kubernetes import client, config

            try:
                config.load_incluster_config()
            except Exception:
                config.load_kube_config()

            api = client.CustomObjectsApi()
            api.delete_namespaced_custom_object(
                group="extensions.agents.x-k8s.io",
                version="v1alpha1",
                namespace=lease.namespace,
                plural="sandboxclaims",
                name=lease.claim_name,
            )
        except Exception as exc:
            logger.warning(
                "lease.claim_delete_failed",
                extra={
                    "event": "lease.claim_delete_failed",
                    "lease_id": lease.lease_id,
                    "claim_name": lease.claim_name,
                    "namespace": lease.namespace,
                    "error": str(exc),
                },
            )

    def acquire_scope_lease(
        self,
        scope_type: str,
        scope_key: str,
        *,
        runtime_config: dict[str, object] | None = None,
    ) -> _LeaseRuntime:
        """Acquire or reuse a lease runtime for a logical scope.

        Args:
            scope_type: Scope type (for example ``session``).
            scope_key: Scope key.
            runtime_config: Optional runtime override map.

        Returns:
            Lease runtime wrapper containing active sandbox client.
        """
        effective = self._effective_runtime(runtime_config)
        template_name = str(effective["template_name"])
        namespace = str(effective["namespace"])
        api_url = str(effective["api_url"])
        server_port = int(effective["server_port"])
        sandbox_ready_timeout = int(effective["sandbox_ready_timeout"])
        gateway_ready_timeout = int(effective["gateway_ready_timeout"])
        session_idle_ttl_seconds = int(effective["session_idle_ttl_seconds"])
        scope_lock = self._scope_lock_for(scope_type, scope_key)
        with scope_lock:
            existing_lease = self._lookup_scope_lease(scope_type, scope_key)
            if existing_lease and self._is_expired(existing_lease):
                runtime = self._runtime_for_lease(existing_lease.lease_id)
                if runtime:
                    self._release_runtime_handle(runtime, status="expired")
                else:
                    self._delete_claim_best_effort(existing_lease)
                    self.sandbox_lease_repository.mark_released(
                        existing_lease.lease_id,
                        released_at=_to_iso(_now_utc()),
                        status="expired",
                    )
                    self._remove_runtime_index(existing_lease)
                    self._sync_workspace_claim_binding(scope_type, scope_key, None)
                existing_lease = None

            if existing_lease and (
                existing_lease.template_name != template_name
                or existing_lease.namespace != namespace
            ):
                runtime = self._runtime_for_lease(existing_lease.lease_id)
                if runtime:
                    self._release_runtime_handle(runtime, status="released")
                else:
                    self._delete_claim_best_effort(existing_lease)
                    self.sandbox_lease_repository.mark_released(
                        existing_lease.lease_id,
                        released_at=_to_iso(_now_utc()),
                        status="released",
                    )
                    self._remove_runtime_index(existing_lease)
                    self._sync_workspace_claim_binding(scope_type, scope_key, None)
                existing_lease = None

            if existing_lease:
                runtime = self._runtime_for_lease(existing_lease.lease_id)
                if runtime:
                    self._touch_lease(
                        runtime.lease,
                        session_idle_ttl_seconds=session_idle_ttl_seconds,
                    )
                    logger.info(
                        "lease.reuse",
                        extra={
                            "event": "lease.reuse",
                            "lease_id": runtime.lease.lease_id,
                            "scope_type": runtime.lease.scope_type,
                            "scope_key": runtime.lease.scope_key,
                            "claim_name": runtime.lease.claim_name,
                        },
                    )
                    return runtime

                if existing_lease.claim_name:
                    try:
                        return self._attach_runtime(
                            existing_lease,
                            api_url=api_url,
                            server_port=server_port,
                            sandbox_ready_timeout=sandbox_ready_timeout,
                            gateway_ready_timeout=gateway_ready_timeout,
                            session_idle_ttl_seconds=session_idle_ttl_seconds,
                        )
                    except Exception as exc:
                        logger.warning(
                            "lease.attach.failed",
                            extra={
                                "event": "lease.attach.failed",
                                "lease_id": existing_lease.lease_id,
                                "scope_type": existing_lease.scope_type,
                                "scope_key": existing_lease.scope_key,
                                "claim_name": existing_lease.claim_name,
                                "error": str(exc),
                            },
                        )
                        self._delete_claim_best_effort(existing_lease)
                        self.sandbox_lease_repository.mark_released(
                            existing_lease.lease_id,
                            released_at=_to_iso(_now_utc()),
                            status="released",
                            last_error=str(exc),
                        )
                        self._remove_runtime_index(existing_lease)
                        self._sync_workspace_claim_binding(scope_type, scope_key, None)
                        existing_lease = None

            lease = existing_lease or self._build_fresh_lease(
                scope_type,
                scope_key,
                template_name=template_name,
                namespace=namespace,
                session_idle_ttl_seconds=session_idle_ttl_seconds,
            )
            self.sandbox_lease_repository.upsert(lease.as_record())
            return self._create_runtime(
                lease,
                api_url=api_url,
                server_port=server_port,
                sandbox_ready_timeout=sandbox_ready_timeout,
                gateway_ready_timeout=gateway_ready_timeout,
                session_idle_ttl_seconds=session_idle_ttl_seconds,
            )

    def release_scope(self, scope_type: str, scope_key: str) -> bool:
        """Release active lease for a scope.

        Args:
            scope_type: Scope type.
            scope_key: Scope key.

        Returns:
            ``True`` if a lease existed and was released.
        """
        scope_lock = self._scope_lock_for(scope_type, scope_key)
        with scope_lock:
            lease = self._lookup_scope_lease(scope_type, scope_key)
            if not lease:
                return False

            runtime = self._runtime_for_lease(lease.lease_id)
            if runtime:
                self._release_runtime_handle(runtime, status="released")
            else:
                self._delete_claim_best_effort(lease)
                self.sandbox_lease_repository.mark_released(
                    lease.lease_id,
                    released_at=_to_iso(_now_utc()),
                    status="released",
                )
                self._remove_runtime_index(lease)
                self._sync_workspace_claim_binding(scope_type, scope_key, None)
            return True

    def get_active_scope_lease(
        self, scope_type: str, scope_key: str
    ) -> dict[str, Any] | None:
        """Return active lease metadata for scope when available.

        Args:
            scope_type: Scope type.
            scope_key: Scope key.

        Returns:
            Active lease record or ``None``.
        """
        scope_lock = self._scope_lock_for(scope_type, scope_key)
        acquired = scope_lock.acquire(blocking=False)
        if not acquired:
            lease = self._lookup_scope_lease(scope_type, scope_key)
            if not lease:
                return None

            return lease.as_record()

        try:
            lease = self._lookup_scope_lease(scope_type, scope_key)
            if not lease:
                return None

            if self._is_expired(lease):
                runtime = self._runtime_for_lease(lease.lease_id)
                if runtime:
                    self._release_runtime_handle(runtime, status="expired")
                else:
                    self._delete_claim_best_effort(lease)
                    self.sandbox_lease_repository.mark_released(
                        lease.lease_id,
                        released_at=_to_iso(_now_utc()),
                        status="expired",
                    )
                    self._remove_runtime_index(lease)
                    self._sync_workspace_claim_binding(scope_type, scope_key, None)
                return None

            return lease.as_record()
        finally:
            scope_lock.release()

    def reap_expired_leases(self) -> int:
        """Release expired leases.

        Returns:
            Number of leases released during this call.
        """
        now_iso = _to_iso(_now_utc())
        expired = self.sandbox_lease_repository.list_expired(now_iso)
        released_count = 0
        for record in expired:
            lease = SandboxLease.from_record(record)
            scope_lock = self._scope_lock_for(lease.scope_type, lease.scope_key)
            with scope_lock:
                latest = self.sandbox_lease_repository.get(lease.lease_id)
                if not latest or latest.get("status") not in {"pending", "ready"}:
                    continue

                latest_lease = SandboxLease.from_record(latest)
                if not self._is_expired(latest_lease):
                    continue

                runtime = self._runtime_for_lease(latest_lease.lease_id)
                if runtime:
                    self._release_runtime_handle(runtime, status="expired")
                else:
                    self._delete_claim_best_effort(latest_lease)
                    self.sandbox_lease_repository.mark_released(
                        latest_lease.lease_id,
                        released_at=now_iso,
                        status="expired",
                    )
                    self._remove_runtime_index(latest_lease)
                    self._sync_workspace_claim_binding(
                        latest_lease.scope_type, latest_lease.scope_key, None
                    )
                released_count += 1
        return released_count

    def exec_python(
        self,
        session_id: str,
        code: str,
        *,
        runtime_config: dict[str, object] | None = None,
    ) -> SandboxExecutionResult:
        """Execute Python according to lifecycle policy.

        Args:
            session_id: Session identifier.
            code: Python source code.
            runtime_config: Optional runtime override map.

        Returns:
            Normalized sandbox execution result.
        """
        effective = self._effective_runtime(runtime_config)
        try:
            effective = self._workspace_runtime_overrides(session_id, effective)
        except (WorkspaceNotReadyError, WorkspaceProvisioningError) as exc:
            return SandboxExecutionResult(
                tool_name="sandbox_exec_python",
                ok=False,
                stdout="",
                stderr="",
                exit_code=None,
                error=str(exc),
            )
        mode = str(effective["mode"])
        execution_model = str(effective["execution_model"])
        self.reap_expired_leases()
        if mode == "local":
            return self.sandbox_manager.exec_python(code, runtime_config=effective)
        if execution_model == "ephemeral":
            return self.sandbox_manager.exec_python(code, runtime_config=effective)

        runtime = self.acquire_scope_lease(
            "session", session_id, runtime_config=effective
        )
        with runtime.lock:
            self._touch_lease(
                runtime.lease,
                session_idle_ttl_seconds=int(effective["session_idle_ttl_seconds"]),
            )
            return self.sandbox_manager.exec_python_with_sandbox(
                code,
                sandbox=runtime.client,
                lease_id=runtime.lease.lease_id,
                claim_name=runtime.lease.claim_name,
                runtime_config=effective,
            )

    def exec_shell(
        self,
        session_id: str,
        command: str,
        *,
        runtime_config: dict[str, object] | None = None,
    ) -> SandboxExecutionResult:
        """Execute shell command according to lifecycle policy.

        Args:
            session_id: Session identifier.
            command: Shell command string.
            runtime_config: Optional runtime override map.

        Returns:
            Normalized sandbox execution result.
        """
        effective = self._effective_runtime(runtime_config)
        try:
            effective = self._workspace_runtime_overrides(session_id, effective)
        except (WorkspaceNotReadyError, WorkspaceProvisioningError) as exc:
            return SandboxExecutionResult(
                tool_name="sandbox_exec_shell",
                ok=False,
                stdout="",
                stderr="",
                exit_code=None,
                error=str(exc),
            )
        mode = str(effective["mode"])
        execution_model = str(effective["execution_model"])
        self.reap_expired_leases()
        if mode == "local":
            return self.sandbox_manager.exec_shell(command, runtime_config=effective)
        if execution_model == "ephemeral":
            return self.sandbox_manager.exec_shell(command, runtime_config=effective)

        runtime = self.acquire_scope_lease(
            "session", session_id, runtime_config=effective
        )
        with runtime.lock:
            self._touch_lease(
                runtime.lease,
                session_idle_ttl_seconds=int(effective["session_idle_ttl_seconds"]),
            )
            return self.sandbox_manager.exec_shell_with_sandbox(
                command,
                sandbox=runtime.client,
                lease_id=runtime.lease.lease_id,
                claim_name=runtime.lease.claim_name,
                runtime_config=effective,
            )

    def list_sandboxes(self) -> list[dict[str, Any]]:
        """Return active lease records.

        Returns:
            Active lease dictionaries.
        """
        return self.sandbox_lease_repository.list_active()

    def list_all_sandboxes(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return active and historical lease records.

        Args:
            limit: Optional row limit.

        Returns:
            Lease dictionaries ordered by recency.
        """
        return self.sandbox_lease_repository.list_all(limit=limit)

    def get_sandbox(self, lease_id: str) -> dict[str, Any] | None:
        """Return a single lease record.

        Args:
            lease_id: Lease identifier.

        Returns:
            Lease record if found, otherwise ``None``.
        """
        return self.sandbox_lease_repository.get(lease_id)

    def release_sandbox(self, lease_id: str) -> bool:
        """Release lease by identifier.

        Args:
            lease_id: Lease identifier.

        Returns:
            ``True`` when active lease existed and was released.
        """
        with self._state_lock:
            record = self.sandbox_lease_repository.get(lease_id)
            if not record or record.get("status") not in {"pending", "ready"}:
                return False
            lease = SandboxLease.from_record(record)
            runtime = self._runtime_for_lease(lease.lease_id)
            if runtime:
                self._release_runtime_handle(runtime, status="released")
            else:
                self._delete_claim_best_effort(lease)
                self.sandbox_lease_repository.mark_released(
                    lease.lease_id,
                    released_at=_to_iso(_now_utc()),
                    status="released",
                )
                self._remove_runtime_index(lease)
                self._sync_workspace_claim_binding(
                    lease.scope_type, lease.scope_key, None
                )
            return True
