from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def stable_suffix(value: str, *, length: int = 12) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return digest[:length]


def normalize_dns_label(prefix: str, value: str, *, max_length: int = 63) -> str:
    cleaned = re.sub(r"[^a-z0-9-]+", "-", value.lower())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    if not cleaned:
        cleaned = stable_suffix(value, length=10)
    base = f"{prefix}-{cleaned}"
    if len(base) <= max_length:
        return base
    suffix = stable_suffix(value, length=10)
    trimmed = cleaned[: max_length - len(prefix) - len(suffix) - 2].rstrip("-")
    return f"{prefix}-{trimmed}-{suffix}".strip("-")[:max_length]


@dataclass
class WorkspaceRecord:
    workspace_id: str
    user_id: str
    status: str
    bucket_name: str
    managed_folder_path: str
    gsa_email: str
    ksa_name: str
    derived_template_name: str
    claim_name: str | None
    claim_namespace: str | None
    last_provisioned_at: str | None
    last_verified_at: str | None
    last_error: str | None
    created_at: str
    updated_at: str
    deleted_at: str | None = None

    @classmethod
    def from_record(cls, record: dict[str, object]) -> "WorkspaceRecord":
        return cls(
            workspace_id=str(record["workspace_id"]),
            user_id=str(record["user_id"]),
            status=str(record["status"]),
            bucket_name=str(record["bucket_name"]),
            managed_folder_path=str(record["managed_folder_path"]),
            gsa_email=str(record["gsa_email"]),
            ksa_name=str(record["ksa_name"]),
            derived_template_name=str(record["derived_template_name"]),
            claim_name=str(record["claim_name"]) if record.get("claim_name") else None,
            claim_namespace=(
                str(record["claim_namespace"])
                if record.get("claim_namespace")
                else None
            ),
            last_provisioned_at=(
                str(record["last_provisioned_at"])
                if record.get("last_provisioned_at")
                else None
            ),
            last_verified_at=(
                str(record["last_verified_at"])
                if record.get("last_verified_at")
                else None
            ),
            last_error=str(record["last_error"]) if record.get("last_error") else None,
            created_at=str(record["created_at"]),
            updated_at=str(record["updated_at"]),
            deleted_at=str(record["deleted_at"]) if record.get("deleted_at") else None,
        )

    def as_record(self) -> dict[str, object]:
        return {
            "workspace_id": self.workspace_id,
            "user_id": self.user_id,
            "status": self.status,
            "bucket_name": self.bucket_name,
            "managed_folder_path": self.managed_folder_path,
            "gsa_email": self.gsa_email,
            "ksa_name": self.ksa_name,
            "derived_template_name": self.derived_template_name,
            "claim_name": self.claim_name,
            "claim_namespace": self.claim_namespace,
            "last_provisioned_at": self.last_provisioned_at,
            "last_verified_at": self.last_verified_at,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }


@dataclass(frozen=True)
class WorkspaceInfraConfig:
    project_id: str
    bucket_prefix: str
    namespace: str
    base_template_name: str
    gsa_account_prefix: str = "sandbox-user"
    ksa_prefix: str = "sandbox-user"
    template_prefix: str = "python-runtime-template-user"

    def bucket_name(self, user_id: str) -> str:
        return normalize_dns_label(self.bucket_prefix, user_id)

    def managed_folder_path(self, user_id: str) -> str:
        return ""

    def gsa_account_id(self, user_id: str) -> str:
        return normalize_dns_label(self.gsa_account_prefix, user_id, max_length=30)

    def gsa_email(self, user_id: str) -> str:
        return (
            f"{self.gsa_account_id(user_id)}@{self.project_id}.iam.gserviceaccount.com"
        )

    def ksa_name(self, user_id: str) -> str:
        return normalize_dns_label(self.ksa_prefix, user_id)

    def template_name(self, user_id: str) -> str:
        return normalize_dns_label(self.template_prefix, user_id)


def build_pending_workspace(
    user_id: str, infra: WorkspaceInfraConfig
) -> WorkspaceRecord:
    timestamp = now_iso()
    return WorkspaceRecord(
        workspace_id=f"ws-{uuid.uuid4().hex}",
        user_id=user_id,
        status="pending",
        bucket_name=infra.bucket_name(user_id),
        managed_folder_path=infra.managed_folder_path(user_id),
        gsa_email=infra.gsa_email(user_id),
        ksa_name=infra.ksa_name(user_id),
        derived_template_name=infra.template_name(user_id),
        claim_name=None,
        claim_namespace=infra.namespace,
        last_provisioned_at=None,
        last_verified_at=None,
        last_error=None,
        created_at=timestamp,
        updated_at=timestamp,
        deleted_at=None,
    )
