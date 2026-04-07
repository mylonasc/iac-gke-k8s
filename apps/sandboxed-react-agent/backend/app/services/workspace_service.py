from __future__ import annotations

from .workspace_async_service import WorkspaceAsyncService
from .workspace_models import WorkspaceRecord
from .workspace_provisioning_service import WorkspaceProvisioningService
from ..repositories.user_workspace_repository import UserWorkspaceRepository


class WorkspaceService:
    def __init__(
        self,
        *,
        workspace_provisioning_service: WorkspaceProvisioningService,
        user_workspace_repository: UserWorkspaceRepository | None = None,
        workspace_async_service: WorkspaceAsyncService | None = None,
    ) -> None:
        self.workspace_provisioning_service = workspace_provisioning_service
        self.user_workspace_repository = user_workspace_repository
        self.workspace_async_service = workspace_async_service

    def get_or_create_user_workspace(self, user_id: str) -> WorkspaceRecord:
        return self.workspace_provisioning_service.ensure_workspace_for_user(user_id)

    def get_workspace_for_user(self, user_id: str) -> WorkspaceRecord | None:
        return self.workspace_provisioning_service.get_workspace_for_user(user_id)

    def delete_workspace_for_user(self, user_id: str, *, delete_data: bool) -> bool:
        return self.workspace_provisioning_service.deprovision_workspace(
            user_id,
            delete_data=delete_data,
        )

    def ensure_workspace_async(self, user_id: str) -> tuple[WorkspaceRecord, bool]:
        if self.workspace_async_service is None:
            return self.get_or_create_user_workspace(user_id), False
        return self.workspace_async_service.ensure_workspace_async(user_id)

    def bind_claim_for_user(
        self, user_id: str, *, claim_name: str | None, claim_namespace: str | None
    ) -> bool:
        if self.user_workspace_repository is None:
            return False
        return self.user_workspace_repository.update_claim_binding(
            user_id,
            claim_name=claim_name,
            claim_namespace=claim_namespace,
        )

    def is_workspace_pending(self, user_id: str) -> bool:
        if self.workspace_async_service is None:
            return False
        return self.workspace_async_service.is_pending(user_id)
