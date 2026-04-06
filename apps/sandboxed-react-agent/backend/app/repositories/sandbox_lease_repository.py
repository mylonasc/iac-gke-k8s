from typing import Any

from ..session_store import SessionStore


class SandboxLeaseRepository:
    def __init__(self, session_store: SessionStore) -> None:
        self.session_store = session_store

    def list_active(self) -> list[dict[str, Any]]:
        return self.session_store.list_active_sandbox_leases()

    def upsert(self, lease: dict[str, Any]) -> None:
        self.session_store.upsert_sandbox_lease(lease)

    def get(self, lease_id: str) -> dict[str, Any] | None:
        return self.session_store.get_sandbox_lease(lease_id)

    def get_active_for_scope(
        self, scope_type: str, scope_key: str
    ) -> dict[str, Any] | None:
        return self.session_store.get_active_sandbox_lease(scope_type, scope_key)

    def list_expired(self, now_iso: str) -> list[dict[str, Any]]:
        return self.session_store.list_expired_sandbox_leases(now_iso)

    def mark_released(
        self,
        lease_id: str,
        *,
        released_at: str,
        status: str = "released",
        last_error: str | None = None,
    ) -> None:
        self.session_store.mark_sandbox_lease_released(
            lease_id,
            released_at=released_at,
            status=status,
            last_error=last_error,
        )
