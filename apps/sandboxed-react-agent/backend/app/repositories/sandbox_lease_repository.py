from typing import Any

from ..session_store import SessionStore


class SandboxLeaseRepository:
    """Persistence adapter for sandbox lease records.

    This repository isolates lifecycle orchestration from the concrete SQLite
    implementation exposed by ``SessionStore``.
    """

    def __init__(self, session_store: SessionStore) -> None:
        """Initialize the repository.

        Args:
            session_store: Shared persistence facade used by the application.
        """
        self.session_store = session_store

    def list_active(self) -> list[dict[str, Any]]:
        """List active leases.

        Returns:
            A list of active lease records in storage format.
        """
        return self.session_store.list_active_sandbox_leases()

    def list_all(self, limit: int | None = None) -> list[dict[str, Any]]:
        """List active and historical leases.

        Args:
            limit: Optional maximum number of rows to return.

        Returns:
            Lease records ordered by recency.
        """
        return self.session_store.list_sandbox_leases(limit=limit)

    def upsert(self, lease: dict[str, Any]) -> None:
        """Insert or update a lease record.

        Args:
            lease: Lease payload in storage schema.
        """
        self.session_store.upsert_sandbox_lease(lease)

    def get(self, lease_id: str) -> dict[str, Any] | None:
        """Fetch a lease by identifier.

        Args:
            lease_id: Lease identifier.

        Returns:
            The lease record when found, otherwise ``None``.
        """
        return self.session_store.get_sandbox_lease(lease_id)

    def get_active_for_scope(
        self, scope_type: str, scope_key: str
    ) -> dict[str, Any] | None:
        """Fetch the active lease for a logical scope.

        Args:
            scope_type: Scope category (for example ``session``).
            scope_key: Scope identifier within the category.

        Returns:
            The active lease if one exists, otherwise ``None``.
        """
        return self.session_store.get_active_sandbox_lease(scope_type, scope_key)

    def list_expired(self, now_iso: str) -> list[dict[str, Any]]:
        """List leases that are expired at the provided timestamp.

        Args:
            now_iso: Current timestamp in ISO-8601 format.

        Returns:
            Expired active-lease records.
        """
        return self.session_store.list_expired_sandbox_leases(now_iso)

    def mark_released(
        self,
        lease_id: str,
        *,
        released_at: str,
        status: str = "released",
        last_error: str | None = None,
    ) -> None:
        """Mark a lease terminal and store optional error context.

        Args:
            lease_id: Lease identifier.
            released_at: Release timestamp in ISO-8601 format.
            status: Terminal status value.
            last_error: Optional error text for diagnostics.
        """
        self.session_store.mark_sandbox_lease_released(
            lease_id,
            released_at=released_at,
            status=status,
            last_error=last_error,
        )
