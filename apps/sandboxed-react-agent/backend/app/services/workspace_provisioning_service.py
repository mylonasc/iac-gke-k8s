from __future__ import annotations

import logging

from ..repositories.user_repository import UserRepository
from ..repositories.user_workspace_repository import UserWorkspaceRepository
from .workspace_admin_clients import (
    GoogleWorkspaceAdminClient,
    KubernetesWorkspaceAdminClient,
)
from .workspace_models import (
    WorkspaceInfraConfig,
    WorkspaceRecord,
    build_pending_workspace,
    now_iso,
)


logger = logging.getLogger(__name__)


class WorkspaceProvisioningService:
    def __init__(
        self,
        *,
        user_repository: UserRepository,
        user_workspace_repository: UserWorkspaceRepository,
        google_admin_client: GoogleWorkspaceAdminClient,
        kubernetes_admin_client: KubernetesWorkspaceAdminClient,
        infra_config: WorkspaceInfraConfig,
    ) -> None:
        self.user_repository = user_repository
        self.user_workspace_repository = user_workspace_repository
        self.google_admin_client = google_admin_client
        self.kubernetes_admin_client = kubernetes_admin_client
        self.infra_config = infra_config

    def get_workspace_for_user(self, user_id: str) -> WorkspaceRecord | None:
        record = self.user_workspace_repository.get_by_user_id(user_id)
        if not record:
            return None
        return WorkspaceRecord.from_record(record)

    def prepare_workspace_for_user(self, user_id: str) -> WorkspaceRecord:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")

        self.user_repository.ensure_user(normalized_user_id)
        existing = self.get_workspace_for_user(normalized_user_id)
        if existing and existing.status == "ready":
            return existing

        workspace = existing or build_pending_workspace(
            normalized_user_id, self.infra_config
        )
        if existing and existing.status == "deleted":
            workspace = build_pending_workspace(normalized_user_id, self.infra_config)

        workspace.bucket_name = self.infra_config.bucket_name(normalized_user_id)
        workspace.managed_folder_path = self.infra_config.managed_folder_path(
            normalized_user_id
        )
        workspace.gsa_email = self.infra_config.gsa_email(normalized_user_id)
        workspace.ksa_name = self.infra_config.ksa_name(normalized_user_id)
        workspace.derived_template_name = self.infra_config.template_name(
            normalized_user_id
        )
        workspace.claim_namespace = self.infra_config.namespace

        workspace.status = "pending"
        workspace.last_error = None
        workspace.updated_at = now_iso()
        self.user_workspace_repository.upsert(workspace.as_record())
        return workspace

    def _provision_workspace(self, workspace: WorkspaceRecord) -> WorkspaceRecord:
        normalized_user_id = workspace.user_id
        try:
            account_id = self.infra_config.gsa_account_id(normalized_user_id)
            self.google_admin_client.ensure_bucket(bucket_name=workspace.bucket_name)
            gsa_email = self.google_admin_client.ensure_service_account(
                account_id=account_id,
                display_name=f"Sandbox workspace principal for {normalized_user_id}",
            )
            workspace.gsa_email = gsa_email
            self.kubernetes_admin_client.ensure_service_account(
                namespace=self.infra_config.namespace,
                name=workspace.ksa_name,
                annotations={"iam.gke.io/gcp-service-account": gsa_email},
            )
            self.google_admin_client.ensure_workload_identity_binding(
                gsa_email=gsa_email,
                project_id=self.infra_config.project_id,
                namespace=self.infra_config.namespace,
                ksa_name=workspace.ksa_name,
            )
            self.google_admin_client.ensure_bucket_access(
                bucket_name=workspace.bucket_name,
                gsa_email=gsa_email,
                role="roles/storage.objectUser",
            )
            self.kubernetes_admin_client.ensure_sandbox_template(
                namespace=self.infra_config.namespace,
                name=workspace.derived_template_name,
                base_template_name=self.infra_config.base_template_name,
                ksa_name=workspace.ksa_name,
                bucket_name=workspace.bucket_name,
                managed_folder_path=workspace.managed_folder_path,
                mount_path="/workspace",
                labels={
                    "managed-by": "sandbox-workspace-provisioner",
                    "workspace-id": workspace.workspace_id,
                    "user-id": normalized_user_id,
                },
            )
        except Exception as exc:
            workspace.status = "error"
            workspace.last_error = str(exc)
            workspace.updated_at = now_iso()
            self.user_workspace_repository.upsert(workspace.as_record())
            logger.exception(
                "workspace.provision.failed",
                extra={
                    "event": "workspace.provision.failed",
                    "user_id": normalized_user_id,
                    "workspace_id": workspace.workspace_id,
                    "error": str(exc),
                },
            )
            raise

        timestamp = now_iso()
        workspace.status = "ready"
        workspace.last_provisioned_at = timestamp
        workspace.last_verified_at = timestamp
        workspace.last_error = None
        workspace.deleted_at = None
        workspace.updated_at = timestamp
        self.user_workspace_repository.upsert(workspace.as_record())
        return workspace

    def ensure_workspace_for_user(self, user_id: str) -> WorkspaceRecord:
        workspace = self.prepare_workspace_for_user(user_id)
        if workspace.status == "ready":
            return self._provision_workspace(workspace)
        return self._provision_workspace(workspace)

    def provision_prepared_workspace(
        self, workspace: WorkspaceRecord
    ) -> WorkspaceRecord:
        if workspace.status == "ready":
            return self._provision_workspace(workspace)
        return self._provision_workspace(workspace)

    def deprovision_workspace(self, user_id: str, *, delete_data: bool = False) -> bool:
        workspace = self.get_workspace_for_user(user_id)
        if not workspace or workspace.status == "deleted":
            return False

        workspace.status = "deleting"
        workspace.updated_at = now_iso()
        workspace.last_error = None
        self.user_workspace_repository.upsert(workspace.as_record())

        try:
            self.kubernetes_admin_client.delete_sandbox_template(
                namespace=self.infra_config.namespace,
                name=workspace.derived_template_name,
            )
            self.kubernetes_admin_client.delete_service_account(
                namespace=self.infra_config.namespace,
                name=workspace.ksa_name,
            )
            self.google_admin_client.delete_bucket_access(
                bucket_name=workspace.bucket_name,
                gsa_email=workspace.gsa_email,
                role="roles/storage.objectUser",
            )
            self.google_admin_client.delete_workload_identity_binding(
                gsa_email=workspace.gsa_email,
                project_id=self.infra_config.project_id,
                namespace=self.infra_config.namespace,
                ksa_name=workspace.ksa_name,
            )
            self.google_admin_client.delete_bucket(
                bucket_name=workspace.bucket_name,
                delete_contents=delete_data,
            )
            self.google_admin_client.delete_service_account(
                gsa_email=workspace.gsa_email
            )
        except Exception as exc:
            workspace.status = "error"
            workspace.last_error = str(exc)
            workspace.updated_at = now_iso()
            self.user_workspace_repository.upsert(workspace.as_record())
            logger.exception(
                "workspace.deprovision.failed",
                extra={
                    "event": "workspace.deprovision.failed",
                    "user_id": user_id,
                    "workspace_id": workspace.workspace_id,
                    "error": str(exc),
                },
            )
            raise

        timestamp = now_iso()
        workspace.status = "deleted"
        workspace.deleted_at = timestamp
        workspace.last_error = None
        workspace.updated_at = timestamp
        self.user_workspace_repository.upsert(workspace.as_record())
        return True
