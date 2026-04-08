from typing import Any

from ..agents.integrations.sandbox_leases import SandboxLeaseFacade
from ..sandbox_lifecycle import SandboxLifecycleService
from ..sandbox_manager import SandboxManager


class SandboxAdminService:
    """Read and control interfaces for sandbox operations in admin APIs."""

    def __init__(
        self,
        *,
        sandbox_lease_facade: SandboxLeaseFacade,
        sandbox_manager: SandboxManager,
        sandbox_lifecycle: SandboxLifecycleService,
    ) -> None:
        """Initialize admin service dependencies.

        Args:
            sandbox_lease_facade: Lease facade used for list/release operations.
            sandbox_manager: Sandbox runtime manager.
            sandbox_lifecycle: Lifecycle orchestrator for sandbox leases.
        """
        self.sandbox_lease_facade = sandbox_lease_facade
        self.sandbox_manager = sandbox_manager
        self.sandbox_lifecycle = sandbox_lifecycle

    def list_sandboxes(self) -> list[dict[str, Any]]:
        """List active sandbox leases.

        Returns:
            Active lease records.
        """
        return self.sandbox_lease_facade.list_active_leases()

    def list_all_sandboxes(self, limit: int | None = None) -> list[dict[str, Any]]:
        """List active and historical sandbox leases.

        Args:
            limit: Optional row limit.

        Returns:
            Lease records ordered by recency.
        """
        return self.sandbox_lease_facade.list_all_leases(limit=limit)

    def get_sandbox(self, lease_id: str) -> dict[str, Any] | None:
        """Fetch one sandbox lease.

        Args:
            lease_id: Lease identifier.

        Returns:
            Lease record if found, otherwise ``None``.
        """
        return self.sandbox_lease_facade.get_lease(lease_id)

    def release_sandbox(self, lease_id: str) -> bool:
        """Release a sandbox lease by identifier.

        Args:
            lease_id: Lease identifier.

        Returns:
            ``True`` when the lease existed and was released.
        """
        return self.sandbox_lease_facade.release_lease(lease_id)

    def get_session_sandbox(self, session_id: str) -> dict[str, Any]:
        """Return session lease summary suitable for UI display.

        Args:
            session_id: Session identifier.

        Returns:
            Normalized session sandbox summary with claim and lease metadata.
        """
        lease = self.sandbox_lease_facade.get_session_lease(session_id)
        if not lease:
            return {
                "has_active_lease": False,
                "has_active_claim": False,
                "lease_id": None,
                "claim_name": None,
                "status": None,
                "template_name": None,
                "namespace": None,
                "created_at": None,
                "last_used_at": None,
                "expires_at": None,
            }

        claim_name = lease.get("claim_name")
        return {
            "has_active_lease": True,
            "has_active_claim": bool(claim_name),
            "lease_id": lease.get("lease_id"),
            "claim_name": claim_name,
            "status": lease.get("status"),
            "template_name": lease.get("template_name"),
            "namespace": lease.get("namespace"),
            "created_at": lease.get("created_at"),
            "last_used_at": lease.get("last_used_at"),
            "expires_at": lease.get("expires_at"),
        }
