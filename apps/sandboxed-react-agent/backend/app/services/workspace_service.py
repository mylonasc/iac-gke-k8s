from __future__ import annotations

from .workspace_async_service import WorkspaceAsyncService
from .workspace_models import WorkspaceRecord
from .workspace_provisioning_service import WorkspaceProvisioningService
from ..repositories.user_workspace_repository import UserWorkspaceRepository


class WorkspaceService:
    """High-level application service for user workspace operations."""

    def __init__(
        self,
        *,
        workspace_provisioning_service: WorkspaceProvisioningService,
        user_workspace_repository: UserWorkspaceRepository | None = None,
        workspace_async_service: WorkspaceAsyncService | None = None,
    ) -> None:
        """Initialize workspace service dependencies.

        Args:
            workspace_provisioning_service: Synchronous provisioning service.
            user_workspace_repository: Optional workspace repository for claim binding.
            workspace_async_service: Optional async orchestration service.
        """
        self.workspace_provisioning_service = workspace_provisioning_service
        self.user_workspace_repository = user_workspace_repository
        self.workspace_async_service = workspace_async_service

    def get_or_create_user_workspace(self, user_id: str) -> WorkspaceRecord:
        """Provision (or retrieve) a user workspace synchronously.

        Args:
            user_id: User identifier.

        Returns:
            Ready workspace record.
        """
        return self.workspace_provisioning_service.ensure_workspace_for_user(user_id)

    def get_workspace_for_user(self, user_id: str) -> WorkspaceRecord | None:
        """Fetch current workspace state for a user.

        Args:
            user_id: User identifier.

        Returns:
            Workspace record if it exists, otherwise ``None``.
        """
        return self.workspace_provisioning_service.get_workspace_for_user(user_id)

    def delete_workspace_for_user(self, user_id: str, *, delete_data: bool) -> bool:
        """Deprovision a user workspace.

        Args:
            user_id: User identifier.
            delete_data: Whether bucket contents should also be deleted.

        Returns:
            ``True`` when a workspace existed and was deprovisioned.
        """
        return self.workspace_provisioning_service.deprovision_workspace(
            user_id,
            delete_data=delete_data,
        )

    def ensure_workspace_async(
        self, user_id: str, *, reconcile_ready: bool = False
    ) -> tuple[WorkspaceRecord, bool]:
        """Ensure workspace asynchronously when async service is configured.

        Args:
            user_id: User identifier.
            reconcile_ready: Whether ready workspaces should still be reconciled.

        Returns:
            Tuple of workspace snapshot and a flag indicating if work was started.
        """
        if self.workspace_async_service is None:
            return self.get_or_create_user_workspace(user_id), False
        return self.workspace_async_service.ensure_workspace_async(
            user_id,
            reconcile_ready=reconcile_ready,
        )

    def bind_claim_for_user(
        self, user_id: str, *, claim_name: str | None, claim_namespace: str | None
    ) -> bool:
        """Attach active sandbox claim metadata to a user's workspace.

        Args:
            user_id: User identifier.
            claim_name: Active claim name or ``None``.
            claim_namespace: Claim namespace or ``None``.

        Returns:
            ``True`` when workspace metadata was updated.
        """
        if self.user_workspace_repository is None:
            return False
        return self.user_workspace_repository.update_claim_binding(
            user_id,
            claim_name=claim_name,
            claim_namespace=claim_namespace,
        )

    def is_workspace_pending(self, user_id: str) -> bool:
        """Report whether workspace work is currently pending.

        Args:
            user_id: User identifier.

        Returns:
            ``True`` when there is active async job/future work.
        """
        if self.workspace_async_service is None:
            return False
        return self.workspace_async_service.is_pending(user_id)

    def resolve_derived_template_name(
        self, user_id: str, *, requested_template_name: str | None
    ) -> str:
        """Resolve the user-scoped derived template for requested base template.

        Args:
            user_id: User identifier.
            requested_template_name: Requested base template.

        Returns:
            Derived template name.
        """
        return self.workspace_provisioning_service.resolve_derived_template_name(
            user_id=user_id,
            requested_template_name=requested_template_name,
        )

    def workspace_base_template_names(self) -> list[str]:
        """Return configured base templates for persistent workspace mode."""
        return self.workspace_provisioning_service.workspace_base_template_names()
