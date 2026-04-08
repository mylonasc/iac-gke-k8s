from __future__ import annotations

import logging

from ..repositories.user_repository import UserRepository
from ..repositories.user_workspace_repository import UserWorkspaceRepository
from .workspace_admin_clients import (
    GoogleWorkspaceAdminClient,
    KubernetesWorkspaceAdminClient,
)
from .workspace_models import (
    WORKSPACE_REASON_DEPROVISIONED,
    WORKSPACE_REASON_DEPROVISION_REQUESTED,
    WORKSPACE_REASON_PROVISIONED,
    WORKSPACE_REASON_PROVISIONING_REQUESTED,
    WORKSPACE_REASON_RECONCILE_REQUESTED,
    WORKSPACE_REASON_UNKNOWN_ERROR,
    WORKSPACE_STATUS_DELETED,
    WORKSPACE_STATUS_DELETING,
    WORKSPACE_STATUS_ERROR,
    WORKSPACE_STATUS_PENDING,
    WORKSPACE_STATUS_READY,
    WORKSPACE_STATUS_RECONCILING,
    WorkspaceInfraConfig,
    WorkspaceRecord,
    build_pending_workspace,
    now_iso,
)


logger = logging.getLogger(__name__)


class WorkspaceProvisioningService:
    """Provisions and deprovisions per-user persistent sandbox workspaces."""

    _ALLOWED_STATUS_TRANSITIONS = {
        WORKSPACE_STATUS_PENDING: {
            WORKSPACE_STATUS_PENDING,
            WORKSPACE_STATUS_READY,
            WORKSPACE_STATUS_ERROR,
            WORKSPACE_STATUS_DELETING,
        },
        WORKSPACE_STATUS_RECONCILING: {
            WORKSPACE_STATUS_RECONCILING,
            WORKSPACE_STATUS_READY,
            WORKSPACE_STATUS_ERROR,
            WORKSPACE_STATUS_DELETING,
        },
        WORKSPACE_STATUS_READY: {
            WORKSPACE_STATUS_READY,
            WORKSPACE_STATUS_RECONCILING,
            WORKSPACE_STATUS_DELETING,
            WORKSPACE_STATUS_ERROR,
        },
        WORKSPACE_STATUS_ERROR: {
            WORKSPACE_STATUS_ERROR,
            WORKSPACE_STATUS_PENDING,
            WORKSPACE_STATUS_RECONCILING,
            WORKSPACE_STATUS_DELETING,
        },
        WORKSPACE_STATUS_DELETING: {
            WORKSPACE_STATUS_DELETING,
            WORKSPACE_STATUS_DELETED,
            WORKSPACE_STATUS_ERROR,
        },
        WORKSPACE_STATUS_DELETED: {
            WORKSPACE_STATUS_DELETED,
            WORKSPACE_STATUS_PENDING,
        },
    }

    def __init__(
        self,
        *,
        user_repository: UserRepository,
        user_workspace_repository: UserWorkspaceRepository,
        google_admin_client: GoogleWorkspaceAdminClient,
        kubernetes_admin_client: KubernetesWorkspaceAdminClient,
        infra_config: WorkspaceInfraConfig,
    ) -> None:
        """Initialize provisioning dependencies.

        Args:
            user_repository: User repository used to ensure user records exist.
            user_workspace_repository: Workspace persistence adapter.
            google_admin_client: GCP-side infrastructure client.
            kubernetes_admin_client: Kubernetes-side infrastructure client.
            infra_config: Naming and target environment configuration.
        """
        self.user_repository = user_repository
        self.user_workspace_repository = user_workspace_repository
        self.google_admin_client = google_admin_client
        self.kubernetes_admin_client = kubernetes_admin_client
        self.infra_config = infra_config

    def _failure_reason(self, *, phase: str, error_text: str) -> str:
        """Map provider errors to stable workspace reason codes.

        Args:
            phase: High-level phase (``provision``, ``reconcile``, or
                ``deprovision``).
            error_text: Raw error text from providers.

        Returns:
            Normalized reason code string.
        """
        lowered = error_text.lower()
        if "unauthenticated" in lowered or "permission denied" in lowered:
            return "fuse_auth_failed"
        if "workload identity" in lowered:
            return "workload_identity_failed"
        if "service account" in lowered:
            return "service_account_failed"
        if "bucket" in lowered or "storage" in lowered:
            return "bucket_access_failed"
        if "template" in lowered:
            return "template_sync_failed"
        if phase == "deprovision":
            return "deprovision_failed"
        if phase == "reconcile":
            return "reconcile_failed"
        if phase == "provision":
            return "provision_failed"
        return WORKSPACE_REASON_UNKNOWN_ERROR

    def _assert_transition(self, current_status: str, next_status: str) -> None:
        """Validate workspace status transition.

        Args:
            current_status: Current workspace status.
            next_status: Next workspace status.

        Raises:
            RuntimeError: If transition is not allowed.
        """
        allowed = self._ALLOWED_STATUS_TRANSITIONS.get(current_status)
        if allowed is None:
            return
        if next_status in allowed:
            return
        raise RuntimeError(
            f"invalid workspace status transition: {current_status} -> {next_status}"
        )

    def get_workspace_for_user(self, user_id: str) -> WorkspaceRecord | None:
        """Fetch workspace state for a user.

        Args:
            user_id: User identifier.

        Returns:
            Workspace record if present, otherwise ``None``.
        """
        record = self.user_workspace_repository.get_by_user_id(user_id)
        if not record:
            return None
        return WorkspaceRecord.from_record(record)

    def prepare_workspace_for_user(self, user_id: str) -> WorkspaceRecord:
        """Prepare workspace metadata and persist pending state.

        This method does not perform infrastructure mutations; it only computes
        deterministic names, updates status, and persists a workspace snapshot.

        Args:
            user_id: User identifier.

        Returns:
            Prepared workspace record.

        Raises:
            ValueError: If ``user_id`` is empty.
        """
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")

        self.user_repository.ensure_user(normalized_user_id)
        existing = self.get_workspace_for_user(normalized_user_id)
        if existing and existing.status == WORKSPACE_STATUS_READY:
            return existing

        workspace = existing or build_pending_workspace(
            normalized_user_id, self.infra_config
        )
        if existing and existing.status == WORKSPACE_STATUS_DELETED:
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

        self._assert_transition(workspace.status, WORKSPACE_STATUS_PENDING)
        workspace.status = WORKSPACE_STATUS_PENDING
        workspace.status_reason = WORKSPACE_REASON_PROVISIONING_REQUESTED
        workspace.last_error = None
        workspace.updated_at = now_iso()
        self.user_workspace_repository.upsert(workspace.as_record())
        return workspace

    def _provision_workspace(self, workspace: WorkspaceRecord) -> WorkspaceRecord:
        """Apply cloud and Kubernetes resources required for workspace runtime.

        Args:
            workspace: Prepared workspace record.

        Returns:
            Workspace in ready state with refreshed timestamps.

        Raises:
            Exception: Re-raises provider exceptions after persisting error state.
        """
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
            phase = (
                "reconcile"
                if workspace.status == WORKSPACE_STATUS_RECONCILING
                else "provision"
            )
            reason = self._failure_reason(phase=phase, error_text=str(exc))
            self._assert_transition(workspace.status, WORKSPACE_STATUS_ERROR)
            workspace.status = WORKSPACE_STATUS_ERROR
            workspace.status_reason = reason
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
        self._assert_transition(workspace.status, WORKSPACE_STATUS_READY)
        workspace.status = WORKSPACE_STATUS_READY
        workspace.status_reason = WORKSPACE_REASON_PROVISIONED
        workspace.last_provisioned_at = timestamp
        workspace.last_verified_at = timestamp
        workspace.last_error = None
        workspace.deleted_at = None
        workspace.updated_at = timestamp
        self.user_workspace_repository.upsert(workspace.as_record())
        return workspace

    def ensure_workspace_for_user(self, user_id: str) -> WorkspaceRecord:
        """Synchronously provision workspace for a user.

        Args:
            user_id: User identifier.

        Returns:
            Ready workspace record.
        """
        workspace = self.prepare_workspace_for_user(user_id)
        return self._provision_workspace(workspace)

    def provision_prepared_workspace(
        self, workspace: WorkspaceRecord
    ) -> WorkspaceRecord:
        """Provision a prepared workspace, optionally as reconcile flow.

        Args:
            workspace: Workspace record that has already been prepared.

        Returns:
            Ready workspace record.
        """
        if workspace.status == WORKSPACE_STATUS_READY:
            self._assert_transition(workspace.status, WORKSPACE_STATUS_RECONCILING)
            workspace.status = WORKSPACE_STATUS_RECONCILING
            workspace.status_reason = WORKSPACE_REASON_RECONCILE_REQUESTED
            workspace.last_error = None
            workspace.updated_at = now_iso()
            self.user_workspace_repository.upsert(workspace.as_record())
        return self._provision_workspace(workspace)

    def deprovision_workspace(self, user_id: str, *, delete_data: bool = False) -> bool:
        """Delete workspace infrastructure for a user.

        Args:
            user_id: User identifier.
            delete_data: Whether to delete bucket contents.

        Returns:
            ``True`` when an existing workspace was deprovisioned.

        Raises:
            Exception: Re-raises provider exceptions after persisting error state.
        """
        workspace = self.get_workspace_for_user(user_id)
        if not workspace or workspace.status == WORKSPACE_STATUS_DELETED:
            return False

        self._assert_transition(workspace.status, WORKSPACE_STATUS_DELETING)
        workspace.status = WORKSPACE_STATUS_DELETING
        workspace.status_reason = WORKSPACE_REASON_DEPROVISION_REQUESTED
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
            reason = self._failure_reason(phase="deprovision", error_text=str(exc))
            self._assert_transition(workspace.status, WORKSPACE_STATUS_ERROR)
            workspace.status = WORKSPACE_STATUS_ERROR
            workspace.status_reason = reason
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
        self._assert_transition(workspace.status, WORKSPACE_STATUS_DELETED)
        workspace.status = WORKSPACE_STATUS_DELETED
        workspace.status_reason = WORKSPACE_REASON_DEPROVISIONED
        workspace.deleted_at = timestamp
        workspace.last_error = None
        workspace.updated_at = timestamp
        self.user_workspace_repository.upsert(workspace.as_record())
        return True
