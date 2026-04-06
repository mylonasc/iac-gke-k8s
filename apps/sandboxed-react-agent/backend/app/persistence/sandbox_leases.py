import json
from typing import Any, Callable


class SQLiteSandboxLeaseStore:
    def __init__(self, connect: Callable[[], object]) -> None:
        self.connect = connect

    def _to_record(self, row: Any) -> dict[str, Any]:
        return {
            "lease_id": row["lease_id"],
            "scope_type": row["scope_type"],
            "scope_key": row["scope_key"],
            "status": row["status"],
            "claim_name": row["claim_name"],
            "template_name": row["template_name"],
            "namespace": row["namespace"],
            "metadata": json.loads(row["metadata_json"]),
            "created_at": row["created_at"],
            "last_used_at": row["last_used_at"],
            "expires_at": row["expires_at"],
            "released_at": row["released_at"],
            "last_error": row["last_error"],
        }

    def upsert_sandbox_lease(self, lease: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO sandbox_leases (
                    lease_id,
                    scope_type,
                    scope_key,
                    status,
                    claim_name,
                    template_name,
                    namespace,
                    metadata_json,
                    created_at,
                    last_used_at,
                    expires_at,
                    released_at,
                    last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lease_id) DO UPDATE SET
                    status=excluded.status,
                    claim_name=excluded.claim_name,
                    template_name=excluded.template_name,
                    namespace=excluded.namespace,
                    metadata_json=excluded.metadata_json,
                    last_used_at=excluded.last_used_at,
                    expires_at=excluded.expires_at,
                    released_at=excluded.released_at,
                    last_error=excluded.last_error
                """,
                (
                    lease["lease_id"],
                    lease["scope_type"],
                    lease["scope_key"],
                    lease["status"],
                    lease.get("claim_name"),
                    lease["template_name"],
                    lease["namespace"],
                    json.dumps(lease.get("metadata") or {}, ensure_ascii=True),
                    lease["created_at"],
                    lease["last_used_at"],
                    lease["expires_at"],
                    lease.get("released_at"),
                    lease.get("last_error"),
                ),
            )

    def get_sandbox_lease(self, lease_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sandbox_leases WHERE lease_id = ?", (lease_id,)
            ).fetchone()
        return self._to_record(row) if row else None

    def get_active_sandbox_lease(
        self, scope_type: str, scope_key: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM sandbox_leases
                WHERE scope_type = ?
                  AND scope_key = ?
                  AND status IN ('pending', 'ready')
                ORDER BY last_used_at DESC
                LIMIT 1
                """,
                (scope_type, scope_key),
            ).fetchone()
        return self._to_record(row) if row else None

    def list_active_sandbox_leases(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM sandbox_leases
                WHERE status IN ('pending', 'ready')
                ORDER BY last_used_at DESC
                """
            ).fetchall()
        return [self._to_record(row) for row in rows]

    def list_expired_sandbox_leases(self, now_iso: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM sandbox_leases
                WHERE status IN ('pending', 'ready')
                  AND expires_at <= ?
                ORDER BY expires_at ASC
                """,
                (now_iso,),
            ).fetchall()
        return [self._to_record(row) for row in rows]

    def mark_sandbox_lease_released(
        self,
        lease_id: str,
        *,
        released_at: str,
        status: str = "released",
        last_error: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE sandbox_leases
                SET status = ?, released_at = ?, last_error = ?
                WHERE lease_id = ?
                """,
                (status, released_at, last_error, lease_id),
            )
