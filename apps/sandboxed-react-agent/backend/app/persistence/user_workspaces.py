from typing import Any, Callable


class SQLiteUserWorkspaceStore:
    def __init__(self, connect: Callable[[], object]) -> None:
        self.connect = connect

    def _to_record(self, row: Any) -> dict[str, Any]:
        return {
            "workspace_id": row["workspace_id"],
            "user_id": row["user_id"],
            "status": row["status"],
            "status_reason": row["status_reason"]
            if "status_reason" in row.keys()
            else None,
            "bucket_name": row["bucket_name"],
            "managed_folder_path": row["managed_folder_path"],
            "gsa_email": row["gsa_email"],
            "ksa_name": row["ksa_name"],
            "derived_template_name": row["derived_template_name"],
            "claim_name": row["claim_name"],
            "claim_namespace": row["claim_namespace"],
            "last_provisioned_at": row["last_provisioned_at"],
            "last_verified_at": row["last_verified_at"],
            "last_error": row["last_error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "deleted_at": row["deleted_at"],
        }

    def upsert_user_workspace(self, workspace: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO user_workspaces (
                    workspace_id,
                    user_id,
                    status,
                    status_reason,
                    bucket_name,
                    managed_folder_path,
                    gsa_email,
                    ksa_name,
                    derived_template_name,
                    claim_name,
                    claim_namespace,
                    last_provisioned_at,
                    last_verified_at,
                    last_error,
                    created_at,
                    updated_at,
                    deleted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET
                    user_id=excluded.user_id,
                    status=excluded.status,
                    status_reason=excluded.status_reason,
                    bucket_name=excluded.bucket_name,
                    managed_folder_path=excluded.managed_folder_path,
                    gsa_email=excluded.gsa_email,
                    ksa_name=excluded.ksa_name,
                    derived_template_name=excluded.derived_template_name,
                    claim_name=excluded.claim_name,
                    claim_namespace=excluded.claim_namespace,
                    last_provisioned_at=excluded.last_provisioned_at,
                    last_verified_at=excluded.last_verified_at,
                    last_error=excluded.last_error,
                    updated_at=excluded.updated_at,
                    deleted_at=excluded.deleted_at
                """,
                (
                    workspace["workspace_id"],
                    workspace["user_id"],
                    workspace["status"],
                    workspace.get("status_reason"),
                    workspace["bucket_name"],
                    workspace["managed_folder_path"],
                    workspace["gsa_email"],
                    workspace["ksa_name"],
                    workspace["derived_template_name"],
                    workspace.get("claim_name"),
                    workspace.get("claim_namespace"),
                    workspace.get("last_provisioned_at"),
                    workspace.get("last_verified_at"),
                    workspace.get("last_error"),
                    workspace["created_at"],
                    workspace["updated_at"],
                    workspace.get("deleted_at"),
                ),
            )

    def get_user_workspace(self, user_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM user_workspaces WHERE user_id = ? LIMIT 1", (user_id,)
            ).fetchone()
        return self._to_record(row) if row else None

    def get_user_workspace_by_id(self, workspace_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM user_workspaces WHERE workspace_id = ? LIMIT 1",
                (workspace_id,),
            ).fetchone()
        return self._to_record(row) if row else None

    def list_user_workspaces(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM user_workspaces ORDER BY updated_at DESC"
            ).fetchall()
        return [self._to_record(row) for row in rows]
