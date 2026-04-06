from typing import Any

from ..agents.integrations.sandbox_leases import SandboxLeaseFacade
from ..sandbox_lifecycle import SandboxLifecycleService
from ..sandbox_manager import SandboxManager


class SandboxAdminService:
    def __init__(
        self,
        *,
        sandbox_lease_facade: SandboxLeaseFacade,
        sandbox_manager: SandboxManager,
        sandbox_lifecycle: SandboxLifecycleService,
    ) -> None:
        self.sandbox_lease_facade = sandbox_lease_facade
        self.sandbox_manager = sandbox_manager
        self.sandbox_lifecycle = sandbox_lifecycle

    def list_sandboxes(self) -> list[dict[str, Any]]:
        return self.sandbox_lease_facade.list_active_leases()

    def get_sandbox(self, lease_id: str) -> dict[str, Any] | None:
        return self.sandbox_lease_facade.get_lease(lease_id)

    def release_sandbox(self, lease_id: str) -> bool:
        return self.sandbox_lease_facade.release_lease(lease_id)

    def get_session_sandbox(self, session_id: str) -> dict[str, Any]:
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
