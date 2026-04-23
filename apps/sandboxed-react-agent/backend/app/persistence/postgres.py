import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from .base import (
    UserStore,
    SessionStoreInterface,
    AssetStore,
    SandboxLeaseStore,
    UserWorkspaceStore,
    WorkspaceJobStore,
    UserConfigStore
)

logger = logging.getLogger(__name__)


def _real_dict_cursor() -> type[Any]:
    try:
        from psycopg2.extras import RealDictCursor
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "psycopg2-binary is required when DATABASE_TYPE=postgres"
        ) from exc
    return RealDictCursor


class PostgreSQLBaseStore:
    def __init__(self, connect: Callable[[], Any]) -> None:
        self.connect = connect

    def _execute(self, query: str, params: tuple[Any, ...] = ()) -> Any:
        with self.connect() as conn:
            with conn.cursor(cursor_factory=_real_dict_cursor()) as cur:
                cur.execute(query, params)
                if cur.description:
                    return cur.fetchall()
                return None


class PostgreSQLUserStore(PostgreSQLBaseStore, UserStore):
    def ensure_user(self, user_id: str) -> dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")
        now = datetime.now(timezone.utc)
        
        with self.connect() as conn:
            with conn.cursor(cursor_factory=_real_dict_cursor()) as cur:
                cur.execute(
                    """
                    INSERT INTO users (user_id, tier, created_at, updated_at)
                    VALUES (%s, 'default', %s, %s)
                    ON CONFLICT (user_id) DO NOTHING
                    RETURNING *
                    """,
                    (normalized_user_id, now, now)
                )
                row = cur.fetchone()
                if not row:
                    cur.execute("SELECT * FROM users WHERE user_id = %s", (normalized_user_id,))
                    row = cur.fetchone()
        return dict(row)

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        normalized_user_id = str(user_id or "").strip()
        rows = self._execute("SELECT * FROM users WHERE user_id = %s", (normalized_user_id,))
        return dict(rows[0]) if rows else None

    def search_users(self, query: str = "", *, limit: int = 20) -> list[dict[str, Any]]:
        normalized_query = str(query or "").strip().lower()
        safe_limit = min(max(int(limit), 1), 100)

        where_clause = ""
        params: tuple[Any, ...] = ()
        if normalized_query:
            where_clause = "WHERE LOWER(u.user_id) LIKE %s"
            params = (f"%{normalized_query}%",)

        rows = self._execute(
            f"""
            SELECT
                u.user_id,
                u.tier,
                u.created_at,
                u.updated_at,
                w.status AS workspace_status,
                w.updated_at AS workspace_updated_at,
                (
                    SELECT MAX(s.updated_at)
                    FROM sessions s
                    WHERE s.user_id = u.user_id
                ) AS last_session_at
            FROM users u
            LEFT JOIN user_workspaces w ON w.user_id = u.user_id
            {where_clause}
            ORDER BY COALESCE(
                (
                    SELECT MAX(s.updated_at)
                    FROM sessions s
                    WHERE s.user_id = u.user_id
                ),
                w.updated_at,
                u.updated_at,
                u.created_at
            ) DESC,
            u.user_id ASC
            LIMIT %s
            """,
            (*params, safe_limit)
        )
        return [dict(row) for row in rows]


class PostgreSQLSessionStore(PostgreSQLBaseStore, SessionStoreInterface):
    def _to_record(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_id": row["session_id"],
            "user_id": row["user_id"] or "",
            "created_at": row["created_at"].isoformat() if isinstance(row["created_at"], datetime) else row["created_at"],
            "updated_at": row["updated_at"].isoformat() if isinstance(row["updated_at"], datetime) else row["updated_at"],
            "title": row["title"],
            "messages": row["messages_json"] if isinstance(row["messages_json"], list) else json.loads(row["messages_json"]),
            "ui_messages": row["ui_messages_json"] if isinstance(row["ui_messages_json"], list) else json.loads(row["ui_messages_json"]),
            "tool_calls": row["tool_calls"],
            "last_error": row["last_error"],
            "share_id": row["share_id"],
            "sandbox_policy": (
                (row["sandbox_policy_json"] if isinstance(row["sandbox_policy_json"], dict) else json.loads(row["sandbox_policy_json"]))
                if row["sandbox_policy_json"]
                else {}
            ),
        }

    def upsert_session(self, session: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        self._execute(
            """
            INSERT INTO sessions (
                session_id,
                user_id,
                created_at,
                updated_at,
                title,
                messages_json,
                ui_messages_json,
                tool_calls,
                last_error,
                share_id,
                sandbox_policy_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(session_id) DO UPDATE SET
                user_id=EXCLUDED.user_id,
                updated_at=EXCLUDED.updated_at,
                title=EXCLUDED.title,
                messages_json=EXCLUDED.messages_json,
                ui_messages_json=EXCLUDED.ui_messages_json,
                tool_calls=EXCLUDED.tool_calls,
                last_error=EXCLUDED.last_error,
                share_id=COALESCE(EXCLUDED.share_id, sessions.share_id),
                sandbox_policy_json=EXCLUDED.sandbox_policy_json
            """,
            (
                session["session_id"],
                session.get("user_id") or "",
                session["created_at"],
                session["updated_at"],
                session["title"],
                json.dumps(session["messages"]),
                json.dumps(session["ui_messages"]),
                int(session["tool_calls"]),
                session.get("last_error"),
                session.get("share_id"),
                json.dumps(session.get("sandbox_policy") or {}),
            )
        )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        rows = self._execute("SELECT * FROM sessions WHERE session_id = %s", (session_id,))
        return self._to_record(rows[0]) if rows else None

    def list_sessions(self) -> list[dict[str, Any]]:
        rows = self._execute("SELECT * FROM sessions ORDER BY updated_at DESC")
        return [self._to_record(row) for row in rows]

    def list_sessions_for_user(self, user_id: str) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM sessions WHERE user_id = %s ORDER BY updated_at DESC",
            (user_id,)
        )
        return [self._to_record(row) for row in rows]

    def delete_session(self, session_id: str) -> bool:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM sessions WHERE session_id = %s", (session_id,))
                return cur.rowcount > 0

    def delete_session_for_user(self, session_id: str, user_id: str) -> bool:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM sessions WHERE session_id = %s AND user_id = %s",
                    (session_id, user_id)
                )
                return cur.rowcount > 0

    def set_share_id(self, session_id: str, share_id: str) -> None:
        self._execute(
            "UPDATE sessions SET share_id = %s WHERE session_id = %s",
            (share_id, session_id)
        )

    def set_share_id_for_user(
        self, session_id: str, user_id: str, share_id: str
    ) -> bool:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE sessions SET share_id = %s WHERE session_id = %s AND user_id = %s",
                    (share_id, session_id, user_id)
                )
                return cur.rowcount > 0

    def get_session_for_user(
        self, session_id: str, user_id: str
    ) -> dict[str, Any] | None:
        rows = self._execute(
            "SELECT * FROM sessions WHERE session_id = %s AND user_id = %s",
            (session_id, user_id)
        )
        return self._to_record(rows[0]) if rows else None

    def get_by_share_id(self, share_id: str) -> dict[str, Any] | None:
        rows = self._execute("SELECT * FROM sessions WHERE share_id = %s", (share_id,))
        return self._to_record(rows[0]) if rows else None


class PostgreSQLUserConfigStore(PostgreSQLBaseStore, UserConfigStore):
    def __init__(self, connect: Callable[[], Any], user_store: UserStore) -> None:
        super().__init__(connect)
        self.user_store = user_store

    def get_user_config(self, user_id: str) -> dict[str, Any] | None:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return None
        rows = self._execute("SELECT * FROM user_configs WHERE user_id = %s", (normalized_user_id,))
        if not rows:
            return None
        row = rows[0]
        config_json = row.get("config_json")
        if config_json:
            parsed = config_json if isinstance(config_json, dict) else json.loads(config_json)
            if isinstance(parsed, dict):
                return parsed
        return self._legacy_runtime_config_from_row(row)

    def upsert_user_config(self, user_id: str, config: dict[str, Any]) -> None:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")
        self.user_store.ensure_user(normalized_user_id)
        now = datetime.now(timezone.utc)
        legacy = self._legacy_columns_from_runtime_config(config)
        self._execute(
            """
            INSERT INTO user_configs (
                user_id,
                model,
                max_tool_calls_per_turn,
                sandbox_mode,
                sandbox_api_url,
                sandbox_template_name,
                sandbox_namespace,
                sandbox_server_port,
                sandbox_max_output_chars,
                sandbox_local_timeout_seconds,
                sandbox_execution_model,
                sandbox_session_idle_ttl_seconds,
                config_json,
                created_at,
                updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(user_id) DO UPDATE SET
                model=EXCLUDED.model,
                max_tool_calls_per_turn=EXCLUDED.max_tool_calls_per_turn,
                sandbox_mode=EXCLUDED.sandbox_mode,
                sandbox_api_url=EXCLUDED.sandbox_api_url,
                sandbox_template_name=EXCLUDED.sandbox_template_name,
                sandbox_namespace=EXCLUDED.sandbox_namespace,
                sandbox_server_port=EXCLUDED.sandbox_server_port,
                sandbox_max_output_chars=EXCLUDED.sandbox_max_output_chars,
                sandbox_local_timeout_seconds=EXCLUDED.sandbox_local_timeout_seconds,
                sandbox_execution_model=EXCLUDED.sandbox_execution_model,
                sandbox_session_idle_ttl_seconds=EXCLUDED.sandbox_session_idle_ttl_seconds,
                config_json=EXCLUDED.config_json,
                updated_at=EXCLUDED.updated_at
            """,
            (
                normalized_user_id,
                str(legacy["model"]),
                int(legacy["max_tool_calls_per_turn"]),
                str(legacy["sandbox_mode"]),
                str(legacy["sandbox_api_url"]),
                str(legacy["sandbox_template_name"]),
                str(legacy["sandbox_namespace"]),
                int(legacy["sandbox_server_port"]),
                int(legacy["sandbox_max_output_chars"]),
                int(legacy["sandbox_local_timeout_seconds"]),
                str(legacy["sandbox_execution_model"]),
                int(legacy["sandbox_session_idle_ttl_seconds"]),
                json.dumps(config),
                now,
                now,
            )
        )

    def _legacy_runtime_config_from_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "agent": {
                "model": row["model"],
                "max_tool_calls_per_turn": int(row["max_tool_calls_per_turn"]),
                "enabled_toolkits": ["sandbox"],
            },
            "toolkits": {
                "sandbox": {
                    "enabled": True,
                    "runtime": {
                        "mode": row["sandbox_mode"],
                        "api_url": row["sandbox_api_url"],
                        "template_name": row["sandbox_template_name"],
                        "namespace": row["sandbox_namespace"],
                        "server_port": int(row["sandbox_server_port"]),
                        "max_output_chars": int(row["sandbox_max_output_chars"]),
                        "local_timeout_seconds": int(
                            row["sandbox_local_timeout_seconds"]
                        ),
                    },
                    "lifecycle": {
                        "execution_model": row["sandbox_execution_model"],
                        "session_idle_ttl_seconds": int(
                            row["sandbox_session_idle_ttl_seconds"]
                        ),
                    },
                }
            },
        }

    def _legacy_columns_from_runtime_config(
        self, config: dict[str, Any]
    ) -> dict[str, Any]:
        if "agent" not in config or "toolkits" not in config:
            return {
                "model": config["model"],
                "max_tool_calls_per_turn": int(config["max_tool_calls_per_turn"]),
                "sandbox_mode": config["sandbox_mode"],
                "sandbox_api_url": config["sandbox_api_url"],
                "sandbox_template_name": config["sandbox_template_name"],
                "sandbox_namespace": config["sandbox_namespace"],
                "sandbox_server_port": int(config["sandbox_server_port"]),
                "sandbox_max_output_chars": int(config["sandbox_max_output_chars"]),
                "sandbox_local_timeout_seconds": int(
                    config["sandbox_local_timeout_seconds"]
                ),
                "sandbox_execution_model": config["sandbox_execution_model"],
                "sandbox_session_idle_ttl_seconds": int(
                    config["sandbox_session_idle_ttl_seconds"]
                ),
            }

        agent = config.get("agent") or {}
        sandbox = (config.get("toolkits") or {}).get("sandbox") or {}
        sandbox_runtime = sandbox.get("runtime") or {}
        sandbox_lifecycle = sandbox.get("lifecycle") or {}
        return {
            "model": str(agent.get("model") or "gpt-4o-mini"),
            "max_tool_calls_per_turn": int(agent.get("max_tool_calls_per_turn") or 4),
            "sandbox_mode": str(sandbox_runtime.get("mode") or "cluster"),
            "sandbox_api_url": str(sandbox_runtime.get("api_url") or ""),
            "sandbox_template_name": str(
                sandbox_runtime.get("template_name") or "python-runtime-template-small"
            ),
            "sandbox_namespace": str(sandbox_runtime.get("namespace") or "alt-default"),
            "sandbox_server_port": int(sandbox_runtime.get("server_port") or 8888),
            "sandbox_max_output_chars": int(
                sandbox_runtime.get("max_output_chars") or 6000
            ),
            "sandbox_local_timeout_seconds": int(
                sandbox_runtime.get("local_timeout_seconds") or 20
            ),
            "sandbox_execution_model": str(
                sandbox_lifecycle.get("execution_model") or "session"
            ),
            "sandbox_session_idle_ttl_seconds": int(
                sandbox_lifecycle.get("session_idle_ttl_seconds") or 1800
            ),
        }


class PostgreSQLAssetStore(PostgreSQLBaseStore, AssetStore):
    def _to_record(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "asset_id": row["asset_id"],
            "session_id": row["session_id"],
            "tool_call_id": row["tool_call_id"],
            "filename": row["filename"],
            "mime_type": row["mime_type"],
            "storage_path": row["storage_path"],
            "size_bytes": row["size_bytes"],
            "created_at": row["created_at"].isoformat() if isinstance(row["created_at"], datetime) else row["created_at"],
        }

    def add_asset(self, asset: dict[str, Any]) -> None:
        self._execute(
            """
            INSERT INTO assets (
                asset_id,
                session_id,
                tool_call_id,
                filename,
                mime_type,
                storage_path,
                size_bytes,
                created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (asset_id) DO UPDATE SET
                session_id=EXCLUDED.session_id,
                tool_call_id=EXCLUDED.tool_call_id,
                filename=EXCLUDED.filename,
                mime_type=EXCLUDED.mime_type,
                storage_path=EXCLUDED.storage_path,
                size_bytes=EXCLUDED.size_bytes,
                created_at=EXCLUDED.created_at
            """,
            (
                asset["asset_id"],
                asset["session_id"],
                asset.get("tool_call_id"),
                asset["filename"],
                asset["mime_type"],
                asset["storage_path"],
                int(asset["size_bytes"]),
                asset["created_at"],
            )
        )

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        rows = self._execute("SELECT * FROM assets WHERE asset_id = %s", (asset_id,))
        return self._to_record(rows[0]) if rows else None

    def get_asset_for_user(self, asset_id: str, user_id: str) -> dict[str, Any] | None:
        rows = self._execute(
            """
            SELECT a.*
            FROM assets a
            JOIN sessions s ON s.session_id = a.session_id
            WHERE a.asset_id = %s
              AND s.user_id = %s
            """,
            (asset_id, user_id)
        )
        return self._to_record(rows[0]) if rows else None

    def get_asset_for_share(
        self, asset_id: str, share_id: str
    ) -> dict[str, Any] | None:
        rows = self._execute(
            """
            SELECT a.*
            FROM assets a
            JOIN sessions s ON s.session_id = a.session_id
            WHERE a.asset_id = %s
              AND s.share_id = %s
            """,
            (asset_id, share_id)
        )
        return self._to_record(rows[0]) if rows else None


class PostgreSQLSandboxLeaseStore(PostgreSQLBaseStore, SandboxLeaseStore):
    def _to_record(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "lease_id": row["lease_id"],
            "scope_type": row["scope_type"],
            "scope_key": row["scope_key"],
            "status": row["status"],
            "claim_name": row["claim_name"],
            "template_name": row["template_name"],
            "namespace": row["namespace"],
            "metadata": row["metadata_json"] if isinstance(row["metadata_json"], dict) else json.loads(row["metadata_json"]),
            "created_at": row["created_at"].isoformat() if isinstance(row["created_at"], datetime) else row["created_at"],
            "last_used_at": row["last_used_at"].isoformat() if isinstance(row["last_used_at"], datetime) else row["last_used_at"],
            "expires_at": row["expires_at"].isoformat() if isinstance(row["expires_at"], datetime) else row["expires_at"],
            "released_at": row["released_at"].isoformat() if isinstance(row["released_at"], datetime) else row["released_at"],
            "last_error": row["last_error"],
        }

    def upsert_sandbox_lease(self, lease: dict[str, Any]) -> None:
        self._execute(
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
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(lease_id) DO UPDATE SET
                status=EXCLUDED.status,
                claim_name=EXCLUDED.claim_name,
                template_name=EXCLUDED.template_name,
                namespace=EXCLUDED.namespace,
                metadata_json=EXCLUDED.metadata_json,
                last_used_at=EXCLUDED.last_used_at,
                expires_at=EXCLUDED.expires_at,
                released_at=EXCLUDED.released_at,
                last_error=EXCLUDED.last_error
            """,
            (
                lease["lease_id"],
                lease["scope_type"],
                lease["scope_key"],
                lease["status"],
                lease.get("claim_name"),
                lease["template_name"],
                lease["namespace"],
                json.dumps(lease.get("metadata") or {}),
                lease["created_at"],
                lease["last_used_at"],
                lease["expires_at"],
                lease.get("released_at"),
                lease.get("last_error"),
            )
        )

    def get_sandbox_lease(self, lease_id: str) -> dict[str, Any] | None:
        rows = self._execute("SELECT * FROM sandbox_leases WHERE lease_id = %s", (lease_id,))
        return self._to_record(rows[0]) if rows else None

    def get_active_sandbox_lease(
        self, scope_type: str, scope_key: str
    ) -> dict[str, Any] | None:
        rows = self._execute(
            """
            SELECT * FROM sandbox_leases
            WHERE scope_type = %s
              AND scope_key = %s
              AND status IN ('pending', 'ready')
            ORDER BY last_used_at DESC
            LIMIT 1
            """,
            (scope_type, scope_key)
        )
        return self._to_record(rows[0]) if rows else None

    def list_active_sandbox_leases(self) -> list[dict[str, Any]]:
        rows = self._execute(
            """
            SELECT * FROM sandbox_leases
            WHERE status IN ('pending', 'ready')
            ORDER BY last_used_at DESC
            """
        )
        return [self._to_record(row) for row in rows]

    def list_sandbox_leases(self, limit: int | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM sandbox_leases ORDER BY created_at DESC"
        params: tuple[Any, ...] = ()
        if limit is not None and limit > 0:
            query += " LIMIT %s"
            params = (int(limit),)
        rows = self._execute(query, params)
        return [self._to_record(row) for row in rows]

    def list_expired_sandbox_leases(self, now_iso: str) -> list[dict[str, Any]]:
        rows = self._execute(
            """
            SELECT * FROM sandbox_leases
            WHERE status IN ('pending', 'ready')
              AND expires_at <= %s
            ORDER BY expires_at ASC
            """,
            (now_iso,)
        )
        return [self._to_record(row) for row in rows]

    def mark_sandbox_lease_released(
        self,
        lease_id: str,
        *,
        released_at: str,
        status: str = "released",
        last_error: str | None = None,
    ) -> None:
        self._execute(
            """
            UPDATE sandbox_leases
            SET status = %s, released_at = %s, last_error = %s
            WHERE lease_id = %s
            """,
            (status, released_at, last_error, lease_id)
        )


class PostgreSQLUserWorkspaceStore(PostgreSQLBaseStore, UserWorkspaceStore):
    def _to_record(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "workspace_id": row["workspace_id"],
            "user_id": row["user_id"],
            "status": row["status"],
            "status_reason": row.get("status_reason"),
            "bucket_name": row["bucket_name"],
            "managed_folder_path": row["managed_folder_path"],
            "gsa_email": row["gsa_email"],
            "ksa_name": row["ksa_name"],
            "derived_template_name": row["derived_template_name"],
            "claim_name": row["claim_name"],
            "claim_namespace": row["claim_namespace"],
            "last_provisioned_at": row["last_provisioned_at"].isoformat() if isinstance(row["last_provisioned_at"], datetime) else row["last_provisioned_at"],
            "last_verified_at": row["last_verified_at"].isoformat() if isinstance(row["last_verified_at"], datetime) else row["last_verified_at"],
            "last_error": row["last_error"],
            "created_at": row["created_at"].isoformat() if isinstance(row["created_at"], datetime) else row["created_at"],
            "updated_at": row["updated_at"].isoformat() if isinstance(row["updated_at"], datetime) else row["updated_at"],
            "deleted_at": row["deleted_at"].isoformat() if isinstance(row["deleted_at"], datetime) else row["deleted_at"],
        }

    def upsert_user_workspace(self, workspace: dict[str, Any]) -> None:
        self._execute(
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
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(workspace_id) DO UPDATE SET
                user_id=EXCLUDED.user_id,
                status=EXCLUDED.status,
                status_reason=EXCLUDED.status_reason,
                bucket_name=EXCLUDED.bucket_name,
                managed_folder_path=EXCLUDED.managed_folder_path,
                gsa_email=EXCLUDED.gsa_email,
                ksa_name=EXCLUDED.ksa_name,
                derived_template_name=EXCLUDED.derived_template_name,
                claim_name=EXCLUDED.claim_name,
                claim_namespace=EXCLUDED.claim_namespace,
                last_provisioned_at=EXCLUDED.last_provisioned_at,
                last_verified_at=EXCLUDED.last_verified_at,
                last_error=EXCLUDED.last_error,
                updated_at=EXCLUDED.updated_at,
                deleted_at=EXCLUDED.deleted_at
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
            )
        )

    def get_user_workspace(self, user_id: str) -> dict[str, Any] | None:
        rows = self._execute("SELECT * FROM user_workspaces WHERE user_id = %s LIMIT 1", (user_id,))
        return self._to_record(rows[0]) if rows else None

    def get_user_workspace_by_id(self, workspace_id: str) -> dict[str, Any] | None:
        rows = self._execute("SELECT * FROM user_workspaces WHERE workspace_id = %s LIMIT 1", (workspace_id,))
        return self._to_record(rows[0]) if rows else None

    def list_user_workspaces(self) -> list[dict[str, Any]]:
        rows = self._execute("SELECT * FROM user_workspaces ORDER BY updated_at DESC")
        return [self._to_record(row) for row in rows]


class PostgreSQLWorkspaceJobStore(PostgreSQLBaseStore, WorkspaceJobStore):
    def _to_record(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "job_id": row["job_id"],
            "user_id": row["user_id"],
            "workspace_id": row["workspace_id"],
            "status": row["status"],
            "reconcile_ready": bool(row["reconcile_ready"]),
            "attempt_count": int(row["attempt_count"]),
            "last_error": row["last_error"],
            "not_before_at": row["not_before_at"].isoformat() if isinstance(row["not_before_at"], datetime) else row["not_before_at"],
            "created_at": row["created_at"].isoformat() if isinstance(row["created_at"], datetime) else row["created_at"],
            "updated_at": row["updated_at"].isoformat() if isinstance(row["updated_at"], datetime) else row["updated_at"],
            "started_at": row["started_at"].isoformat() if isinstance(row["started_at"], datetime) else row["started_at"],
            "completed_at": row["completed_at"].isoformat() if isinstance(row["completed_at"], datetime) else row["completed_at"],
            "lease_expires_at": row["lease_expires_at"].isoformat() if isinstance(row["lease_expires_at"], datetime) else row["lease_expires_at"],
            "worker_id": row["worker_id"],
        }

    def insert_job(self, job: dict[str, Any]) -> None:
        self._execute(
            """
            INSERT INTO workspace_jobs (
                job_id,
                user_id,
                workspace_id,
                status,
                reconcile_ready,
                attempt_count,
                last_error,
                not_before_at,
                created_at,
                updated_at,
                started_at,
                completed_at,
                lease_expires_at,
                worker_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                job["job_id"],
                job["user_id"],
                job.get("workspace_id"),
                job["status"],
                1 if job.get("reconcile_ready") else 0,
                int(job.get("attempt_count") or 0),
                job.get("last_error"),
                job.get("not_before_at"),
                job["created_at"],
                job["updated_at"],
                job.get("started_at"),
                job.get("completed_at"),
                job.get("lease_expires_at"),
                job.get("worker_id"),
            )
        )

    def enqueue_job_if_no_active(self, job: dict[str, Any]) -> bool:
        with self.connect() as conn:
            with conn.cursor(cursor_factory=_real_dict_cursor()) as cur:
                cur.execute(
                    """
                    SELECT job_id
                    FROM workspace_jobs
                    WHERE user_id = %s
                      AND status IN ('queued', 'running')
                    LIMIT 1
                    FOR UPDATE
                    """,
                    (job["user_id"],)
                )
                active = cur.fetchone()
                if active:
                    conn.rollback()
                    return False

                cur.execute(
                    """
                    INSERT INTO workspace_jobs (
                        job_id,
                        user_id,
                        workspace_id,
                        status,
                        reconcile_ready,
                        attempt_count,
                        last_error,
                        not_before_at,
                        created_at,
                        updated_at,
                        started_at,
                        completed_at,
                        lease_expires_at,
                        worker_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        job["job_id"],
                        job["user_id"],
                        job.get("workspace_id"),
                        job["status"],
                        1 if job.get("reconcile_ready") else 0,
                        int(job.get("attempt_count") or 0),
                        job.get("last_error"),
                        job.get("not_before_at"),
                        job["created_at"],
                        job["updated_at"],
                        job.get("started_at"),
                        job.get("completed_at"),
                        job.get("lease_expires_at"),
                        job.get("worker_id"),
                    )
                )
                conn.commit()
                return True

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        rows = self._execute("SELECT * FROM workspace_jobs WHERE job_id = %s LIMIT 1", (job_id,))
        return self._to_record(rows[0]) if rows else None

    def get_active_job_for_user(self, user_id: str) -> dict[str, Any] | None:
        rows = self._execute(
            """
            SELECT *
            FROM workspace_jobs
            WHERE user_id = %s
              AND status IN ('queued', 'running')
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (user_id,)
        )
        return self._to_record(rows[0]) if rows else None

    def claim_next_job(
        self,
        *,
        now_iso: str,
        lease_expires_at: str,
        worker_id: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            with conn.cursor(cursor_factory=_real_dict_cursor()) as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM workspace_jobs
                    WHERE (status = 'queued' AND (not_before_at IS NULL OR not_before_at <= %s))
                       OR (status = 'running' AND lease_expires_at IS NOT NULL AND lease_expires_at < %s)
                    ORDER BY created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """,
                    (now_iso, now_iso)
                )
                row = cur.fetchone()
                if not row:
                    conn.rollback()
                    return None

                job_id = row["job_id"]
                cur.execute(
                    """
                    UPDATE workspace_jobs
                    SET
                        status = 'running',
                        attempt_count = COALESCE(attempt_count, 0) + 1,
                        updated_at = %s,
                        started_at = COALESCE(started_at, %s),
                        lease_expires_at = %s,
                        worker_id = %s,
                        not_before_at = NULL,
                        completed_at = NULL
                    WHERE job_id = %s
                    """,
                    (now_iso, now_iso, lease_expires_at, worker_id, job_id)
                )
                cur.execute("SELECT * FROM workspace_jobs WHERE job_id = %s", (job_id,))
                claimed = cur.fetchone()
                conn.commit()
        return self._to_record(claimed) if claimed else None

    def heartbeat_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        lease_expires_at: str,
        now_iso: str,
    ) -> bool:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE workspace_jobs
                    SET
                        lease_expires_at = %s,
                        updated_at = %s
                    WHERE job_id = %s
                      AND status = 'running'
                      AND worker_id = %s
                    """,
                    (lease_expires_at, now_iso, job_id, worker_id)
                )
                return bool(cur.rowcount)

    def retry_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        now_iso: str,
        not_before_at: str | None,
        last_error: str | None = None,
    ) -> bool:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE workspace_jobs
                    SET
                        status = 'queued',
                        updated_at = %s,
                        lease_expires_at = NULL,
                        worker_id = NULL,
                        completed_at = NULL,
                        last_error = %s,
                        not_before_at = %s
                    WHERE job_id = %s
                      AND status = 'running'
                      AND worker_id = %s
                    """,
                    (now_iso, last_error, not_before_at, job_id, worker_id)
                )
                return bool(cur.rowcount)

    def complete_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        status: str,
        now_iso: str,
        last_error: str | None = None,
    ) -> bool:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE workspace_jobs
                    SET
                        status = %s,
                        updated_at = %s,
                        completed_at = %s,
                        lease_expires_at = NULL,
                        worker_id = %s,
                        last_error = %s
                    WHERE job_id = %s
                      AND status = 'running'
                      AND worker_id = %s
                    """,
                    (status, now_iso, now_iso, worker_id, last_error, job_id, worker_id)
                )
                return bool(cur.rowcount)

    def list_active_jobs_for_user(self, user_id: str) -> list[dict[str, Any]]:
        rows = self._execute(
            """
            SELECT *
            FROM workspace_jobs
            WHERE user_id = %s
              AND status IN ('queued', 'running')
            ORDER BY created_at ASC
            """,
            (user_id,)
        )
        return [self._to_record(row) for row in rows]

    def list_jobs(
        self,
        *,
        limit: int | None = None,
        include_terminal: bool = True,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM workspace_jobs"
        where = []
        params = []
        if not include_terminal:
            where.append("status IN ('queued', 'running')")
        
        if where:
            query += " WHERE " + " AND ".join(where)
        
        query += " ORDER BY created_at DESC"
        
        if limit is not None:
            query += " LIMIT %s"
            params.append(int(limit))
            
        rows = self._execute(query, tuple(params))
        return [self._to_record(row) for row in rows]
