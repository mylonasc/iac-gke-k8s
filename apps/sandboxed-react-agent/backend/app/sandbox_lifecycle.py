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
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from k8s_agent_sandbox import SandboxClient

from .repositories.sandbox_lease_repository import SandboxLeaseRepository
from .sandbox_manager import SandboxExecutionResult, SandboxManager


logger = logging.getLogger(__name__)


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
    ) -> None:
        self.sandbox_manager = sandbox_manager
        self.sandbox_lease_repository = sandbox_lease_repository

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
        """Return lifecycle-related runtime configuration."""
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
        """Update lifecycle execution settings at runtime with validation."""
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

    def _ttl_bounds(self) -> tuple[datetime, datetime]:
        """Calculate current keepalive expiry and hard max expiry bounds."""
        now = _now_utc()
        return (
            now + timedelta(seconds=self.session_idle_ttl_seconds),
            now + timedelta(seconds=self.max_lease_ttl_seconds),
        )

    def _effective_runtime(
        self, runtime_config: dict[str, object] | None
    ) -> dict[str, object]:
        """Return effective sandbox runtime values with optional request overrides."""
        defaults: dict[str, object] = {
            "mode": self.sandbox_manager.mode,
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

    def _touch_lease(
        self, lease: SandboxLease, *, session_idle_ttl_seconds: int | None = None
    ) -> SandboxLease:
        """Refresh lease activity timestamps and persist the update."""
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
        """Create a new lease model using current sandbox defaults."""
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
        """Create and enter a sandbox client for the provided lease."""
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
        client.__enter__()

        lease.claim_name = getattr(client, "claim_name", None)
        lease.status = "ready"
        lease.last_error = None
        self._touch_lease(lease, session_idle_ttl_seconds=session_idle_ttl_seconds)

        runtime = _LeaseRuntime(lease=lease, client=client)
        self._runtime_by_lease_id[lease.lease_id] = runtime
        self._lease_id_by_scope[(lease.scope_type, lease.scope_key)] = lease.lease_id

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

    def _lookup_scope_lease(
        self, scope_type: str, scope_key: str
    ) -> SandboxLease | None:
        """Resolve persisted lease metadata for a scope if one exists."""
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
        self._lease_id_by_scope[(scope_type, scope_key)] = lease.lease_id
        return lease

    def _is_expired(self, lease: SandboxLease) -> bool:
        """Return True if a lease is past its expiry timestamp."""
        return _from_iso(lease.expires_at) <= _now_utc()

    def _release_runtime_handle(
        self, runtime: _LeaseRuntime, *, status: str, error_text: str | None = None
    ) -> None:
        """Close an active runtime handle and mark the lease terminal."""
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
        self._runtime_by_lease_id.pop(lease.lease_id, None)
        self._lease_id_by_scope.pop((lease.scope_type, lease.scope_key), None)

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
        """Best-effort deletion path for persisted leases without in-memory clients."""
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
        """Acquire or reuse a lease runtime for the provided logical scope."""
        effective = self._effective_runtime(runtime_config)
        template_name = str(effective["template_name"])
        namespace = str(effective["namespace"])
        api_url = str(effective["api_url"])
        server_port = int(effective["server_port"])
        sandbox_ready_timeout = int(effective["sandbox_ready_timeout"])
        gateway_ready_timeout = int(effective["gateway_ready_timeout"])
        session_idle_ttl_seconds = int(effective["session_idle_ttl_seconds"])
        with self._state_lock:
            existing_lease = self._lookup_scope_lease(scope_type, scope_key)
            if existing_lease and self._is_expired(existing_lease):
                runtime = self._runtime_by_lease_id.get(existing_lease.lease_id)
                if runtime:
                    self._release_runtime_handle(runtime, status="expired")
                else:
                    self._delete_claim_best_effort(existing_lease)
                    self.sandbox_lease_repository.mark_released(
                        existing_lease.lease_id,
                        released_at=_to_iso(_now_utc()),
                        status="expired",
                    )
                    self._lease_id_by_scope.pop((scope_type, scope_key), None)
                existing_lease = None

            if existing_lease and (
                existing_lease.template_name != template_name
                or existing_lease.namespace != namespace
            ):
                runtime = self._runtime_by_lease_id.get(existing_lease.lease_id)
                if runtime:
                    self._release_runtime_handle(runtime, status="released")
                else:
                    self._delete_claim_best_effort(existing_lease)
                    self.sandbox_lease_repository.mark_released(
                        existing_lease.lease_id,
                        released_at=_to_iso(_now_utc()),
                        status="released",
                    )
                    self._lease_id_by_scope.pop((scope_type, scope_key), None)
                existing_lease = None

            if existing_lease:
                runtime = self._runtime_by_lease_id.get(existing_lease.lease_id)
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
        """Release an active lease for a scope and return whether one existed."""
        with self._state_lock:
            lease = self._lookup_scope_lease(scope_type, scope_key)
            if not lease:
                return False

            runtime = self._runtime_by_lease_id.get(lease.lease_id)
            if runtime:
                self._release_runtime_handle(runtime, status="released")
            else:
                self._delete_claim_best_effort(lease)
                self.sandbox_lease_repository.mark_released(
                    lease.lease_id,
                    released_at=_to_iso(_now_utc()),
                    status="released",
                )
                self._lease_id_by_scope.pop((scope_type, scope_key), None)
            return True

    def get_active_scope_lease(
        self, scope_type: str, scope_key: str
    ) -> dict[str, Any] | None:
        """Return active lease metadata for a scope when available."""
        with self._state_lock:
            lease = self._lookup_scope_lease(scope_type, scope_key)
            if not lease:
                return None

            if self._is_expired(lease):
                runtime = self._runtime_by_lease_id.get(lease.lease_id)
                if runtime:
                    self._release_runtime_handle(runtime, status="expired")
                else:
                    self._delete_claim_best_effort(lease)
                    self.sandbox_lease_repository.mark_released(
                        lease.lease_id,
                        released_at=_to_iso(_now_utc()),
                        status="expired",
                    )
                    self._lease_id_by_scope.pop((scope_type, scope_key), None)
                return None

            return lease.as_record()

    def reap_expired_leases(self) -> int:
        """Release all currently expired leases and return the release count."""
        now_iso = _to_iso(_now_utc())
        expired = self.sandbox_lease_repository.list_expired(now_iso)
        released_count = 0
        with self._state_lock:
            for record in expired:
                lease = SandboxLease.from_record(record)
                runtime = self._runtime_by_lease_id.get(lease.lease_id)
                if runtime:
                    self._release_runtime_handle(runtime, status="expired")
                else:
                    self._delete_claim_best_effort(lease)
                    self.sandbox_lease_repository.mark_released(
                        lease.lease_id,
                        released_at=now_iso,
                        status="expired",
                    )
                    self._lease_id_by_scope.pop(
                        (lease.scope_type, lease.scope_key), None
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
        """Execute Python code under current lifecycle execution policy."""
        effective = self._effective_runtime(runtime_config)
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
        """Execute a shell command under current lifecycle execution policy."""
        effective = self._effective_runtime(runtime_config)
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
        """Return all active leases for API inspection endpoints."""
        return self.sandbox_lease_repository.list_active()

    def get_sandbox(self, lease_id: str) -> dict[str, Any] | None:
        """Return a single lease record by id."""
        return self.sandbox_lease_repository.get(lease_id)

    def release_sandbox(self, lease_id: str) -> bool:
        """Release a lease by id for manual lifecycle operations."""
        with self._state_lock:
            record = self.sandbox_lease_repository.get(lease_id)
            if not record or record.get("status") not in {"pending", "ready"}:
                return False
            lease = SandboxLease.from_record(record)
            runtime = self._runtime_by_lease_id.get(lease.lease_id)
            if runtime:
                self._release_runtime_handle(runtime, status="released")
            else:
                self._delete_claim_best_effort(lease)
                self.sandbox_lease_repository.mark_released(
                    lease.lease_id,
                    released_at=_to_iso(_now_utc()),
                    status="released",
                )
                self._lease_id_by_scope.pop((lease.scope_type, lease.scope_key), None)
            return True
