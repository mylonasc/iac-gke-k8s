from __future__ import annotations

import threading
from dataclasses import dataclass, field

from app.repositories.user_repository import UserRepository
from app.repositories.user_workspace_repository import UserWorkspaceRepository
from app.services.workspace_async_service import WorkspaceAsyncService
from app.services.workspace_models import WorkspaceInfraConfig, normalize_dns_label
from app.services.workspace_provisioning_service import WorkspaceProvisioningService
from app.services.workspace_service import WorkspaceService
from app.session_store import SessionStore


@dataclass
class FakeGoogleAdminClient:
    created_buckets: list[str] = field(default_factory=list)
    created_service_accounts: list[tuple[str, str]] = field(default_factory=list)
    wi_bindings: list[tuple[str, str, str, str]] = field(default_factory=list)
    bucket_access: list[tuple[str, str, str]] = field(default_factory=list)
    deleted_bucket_access: list[tuple[str, str, str]] = field(default_factory=list)
    deleted_wi_bindings: list[tuple[str, str, str, str]] = field(default_factory=list)
    deleted_buckets: list[tuple[str, bool]] = field(default_factory=list)
    deleted_service_accounts: list[str] = field(default_factory=list)
    fail_on_service_account: bool = False

    def ensure_bucket(self, *, bucket_name: str) -> None:
        if bucket_name not in self.created_buckets:
            self.created_buckets.append(bucket_name)

    def ensure_service_account(self, *, account_id: str, display_name: str) -> str:
        if self.fail_on_service_account:
            raise RuntimeError("service account creation failed")
        if (account_id, display_name) not in self.created_service_accounts:
            self.created_service_accounts.append((account_id, display_name))
        return f"{account_id}@test-project.iam.gserviceaccount.com"

    def ensure_workload_identity_binding(
        self,
        *,
        gsa_email: str,
        project_id: str,
        namespace: str,
        ksa_name: str,
    ) -> None:
        binding = (gsa_email, project_id, namespace, ksa_name)
        if binding not in self.wi_bindings:
            self.wi_bindings.append(binding)

    def ensure_bucket_access(
        self,
        *,
        bucket_name: str,
        gsa_email: str,
        role: str,
    ) -> None:
        access = (bucket_name, gsa_email, role)
        if access not in self.bucket_access:
            self.bucket_access.append(access)

    def delete_bucket_access(
        self,
        *,
        bucket_name: str,
        gsa_email: str,
        role: str,
    ) -> None:
        self.deleted_bucket_access.append((bucket_name, gsa_email, role))

    def delete_workload_identity_binding(
        self,
        *,
        gsa_email: str,
        project_id: str,
        namespace: str,
        ksa_name: str,
    ) -> None:
        self.deleted_wi_bindings.append((gsa_email, project_id, namespace, ksa_name))

    def delete_bucket(self, *, bucket_name: str, delete_contents: bool) -> None:
        self.deleted_buckets.append((bucket_name, delete_contents))

    def delete_service_account(self, *, gsa_email: str) -> None:
        self.deleted_service_accounts.append(gsa_email)


@dataclass
class FakeKubernetesAdminClient:
    created_service_accounts: list[tuple[str, str, dict[str, str]]] = field(
        default_factory=list
    )
    created_templates: list[tuple[str, str, str, str, str, str, str]] = field(
        default_factory=list
    )
    deleted_service_accounts: list[tuple[str, str]] = field(default_factory=list)
    deleted_templates: list[tuple[str, str]] = field(default_factory=list)

    def ensure_service_account(
        self, *, namespace: str, name: str, annotations: dict[str, str]
    ) -> None:
        record = (namespace, name, dict(annotations))
        if record not in self.created_service_accounts:
            self.created_service_accounts.append(record)

    def ensure_sandbox_template(
        self,
        *,
        namespace: str,
        name: str,
        base_template_name: str,
        ksa_name: str,
        bucket_name: str,
        managed_folder_path: str,
        mount_path: str,
        labels: dict[str, str],
    ) -> None:
        record = (
            namespace,
            name,
            base_template_name,
            ksa_name,
            bucket_name,
            managed_folder_path,
            mount_path,
        )
        if record not in self.created_templates:
            self.created_templates.append(record)

    def delete_sandbox_template(self, *, namespace: str, name: str) -> None:
        self.deleted_templates.append((namespace, name))

    def delete_service_account(self, *, namespace: str, name: str) -> None:
        self.deleted_service_accounts.append((namespace, name))


def _build_service(tmp_path, *, fail_on_service_account: bool = False):
    store = SessionStore(db_path=str(tmp_path / "workspace.db"))
    google_client = FakeGoogleAdminClient(
        fail_on_service_account=fail_on_service_account
    )
    kubernetes_client = FakeKubernetesAdminClient()
    provisioning = WorkspaceProvisioningService(
        user_repository=UserRepository(store),
        user_workspace_repository=UserWorkspaceRepository(store),
        google_admin_client=google_client,
        kubernetes_admin_client=kubernetes_client,
        infra_config=WorkspaceInfraConfig(
            project_id="test-project",
            bucket_prefix="workspace-bucket",
            namespace="alt-default",
            base_template_name="python-runtime-template-small",
        ),
    )
    service = WorkspaceService(workspace_provisioning_service=provisioning)
    return store, provisioning, service, google_client, kubernetes_client


def test_workspace_provisioning_creates_and_persists_workspace(tmp_path) -> None:
    store, _, service, google_client, kubernetes_client = _build_service(tmp_path)

    workspace = service.get_or_create_user_workspace("user-1")

    assert workspace.status == "ready"
    assert workspace.bucket_name.startswith("workspace-bucket-")
    assert workspace.managed_folder_path == ""
    assert workspace.gsa_email.endswith("@test-project.iam.gserviceaccount.com")
    assert google_client.created_buckets == [workspace.bucket_name]
    assert google_client.bucket_access[0][2] == "roles/storage.objectUser"
    assert kubernetes_client.created_service_accounts[0][0] == "alt-default"
    stored = store.get_user_workspace("user-1")
    assert stored is not None
    assert stored["status"] == "ready"


def test_workspace_provisioning_is_idempotent_for_ready_workspace(tmp_path) -> None:
    _, _, service, google_client, kubernetes_client = _build_service(tmp_path)

    first = service.get_or_create_user_workspace("user-1")
    second = service.get_or_create_user_workspace("user-1")

    assert first.workspace_id == second.workspace_id
    assert len(google_client.created_service_accounts) == 1
    assert len(kubernetes_client.created_templates) == 1


def test_workspace_provisioning_marks_error_on_failure(tmp_path) -> None:
    store, _, service, _, _ = _build_service(tmp_path, fail_on_service_account=True)

    try:
        service.get_or_create_user_workspace("broken-user")
    except RuntimeError as exc:
        assert "service account creation failed" in str(exc)
    else:
        raise AssertionError("expected provisioning to fail")

    stored = store.get_user_workspace("broken-user")
    assert stored is not None
    assert stored["status"] == "error"
    assert stored["last_error"] == "service account creation failed"


def test_workspace_deprovisioning_tombstones_workspace(tmp_path) -> None:
    store, _, service, google_client, kubernetes_client = _build_service(tmp_path)

    workspace = service.get_or_create_user_workspace("user-1")
    deleted = service.delete_workspace_for_user("user-1", delete_data=True)

    assert deleted is True
    assert kubernetes_client.deleted_templates == [
        ("alt-default", workspace.derived_template_name)
    ]
    assert kubernetes_client.deleted_service_accounts == [
        ("alt-default", workspace.ksa_name)
    ]
    assert google_client.deleted_buckets == [(workspace.bucket_name, True)]
    stored = store.get_user_workspace("user-1")
    assert stored is not None
    assert stored["status"] == "deleted"
    assert stored["deleted_at"]


def test_workspace_delete_returns_false_when_missing(tmp_path) -> None:
    _, _, service, _, _ = _build_service(tmp_path)

    assert service.delete_workspace_for_user("missing-user", delete_data=False) is False


def test_workspace_dns_name_normalization_is_stable() -> None:
    name = normalize_dns_label("sandbox-user", "User/With Odd Chars@example.com")
    assert name.startswith("sandbox-user-")
    assert len(name) <= 63
    assert name == normalize_dns_label(
        "sandbox-user", "User/With Odd Chars@example.com"
    )


def test_workspace_async_service_starts_background_provisioning(tmp_path) -> None:
    _, provisioning, _, _, _ = _build_service(tmp_path)
    async_service = WorkspaceAsyncService(
        workspace_provisioning_service=provisioning,
        max_workers=1,
    )

    workspace, started = async_service.ensure_workspace_async("user-1")

    assert workspace.status in {"pending", "ready"}
    assert started is True
    future = async_service.get_pending_future("user-1")
    if future is not None:
        resolved = future.result(timeout=5)
        assert resolved.status == "ready"


def test_workspace_async_service_does_not_duplicate_pending_work(tmp_path) -> None:
    _, provisioning, _, _, _ = _build_service(tmp_path)
    gate = threading.Event()
    original = provisioning.provision_prepared_workspace

    def delayed_provision(workspace):
        gate.wait(timeout=5)
        return original(workspace)

    provisioning.provision_prepared_workspace = delayed_provision  # type: ignore[method-assign]
    async_service = WorkspaceAsyncService(
        workspace_provisioning_service=provisioning,
        max_workers=1,
    )

    _, started_first = async_service.ensure_workspace_async("user-1")
    _, started_second = async_service.ensure_workspace_async("user-1")
    gate.set()

    assert started_first is True
    assert started_second is False
