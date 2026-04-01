import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SessionStore:
    """SQLite-backed persistence for sessions, assets, and sandbox leases."""

    def __init__(self, db_path: str | None = None) -> None:
        default_path = os.getenv("SESSION_STORE_PATH", "/app/data/sessions.db")
        self.db_path = db_path or default_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """Open a database connection with dict-like row access."""
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        """Create all storage tables and indexes if they do not exist."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    tier TEXT NOT NULL DEFAULT 'default',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    title TEXT NOT NULL,
                    messages_json TEXT NOT NULL,
                    ui_messages_json TEXT NOT NULL,
                    tool_calls INTEGER NOT NULL,
                    last_error TEXT,
                    share_id TEXT
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(sessions)").fetchall()
            }
            if "user_id" not in columns:
                connection.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_share_id ON sessions (share_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_user_updated ON sessions (user_id, updated_at DESC)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_configs (
                    user_id TEXT PRIMARY KEY,
                    model TEXT NOT NULL,
                    max_tool_calls_per_turn INTEGER NOT NULL,
                    sandbox_mode TEXT NOT NULL,
                    sandbox_api_url TEXT NOT NULL,
                    sandbox_template_name TEXT NOT NULL,
                    sandbox_namespace TEXT NOT NULL,
                    sandbox_server_port INTEGER NOT NULL,
                    sandbox_max_output_chars INTEGER NOT NULL,
                    sandbox_local_timeout_seconds INTEGER NOT NULL,
                    sandbox_execution_model TEXT NOT NULL,
                    sandbox_session_idle_ttl_seconds INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
                """
            )
            user_config_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(user_configs)"
                ).fetchall()
            }
            if "config_json" not in user_config_columns:
                connection.execute(
                    "ALTER TABLE user_configs ADD COLUMN config_json TEXT"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS assets (
                    asset_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    tool_call_id TEXT,
                    filename TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    storage_path TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_assets_session_id ON assets (session_id)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sandbox_leases (
                    lease_id TEXT PRIMARY KEY,
                    scope_type TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    claim_name TEXT,
                    template_name TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    released_at TEXT,
                    last_error TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_sandbox_leases_scope
                ON sandbox_leases (scope_type, scope_key, status)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_sandbox_leases_expiry
                ON sandbox_leases (expires_at, status)
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO users (user_id, tier, created_at, updated_at)
                SELECT DISTINCT user_id, 'default', ?, ?
                FROM sessions
                WHERE user_id IS NOT NULL AND user_id != ''
                """,
                (now_iso, now_iso),
            )

    def ensure_user(self, user_id: str) -> dict[str, Any]:
        """Ensure a user row exists and return current user metadata."""
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO users (user_id, tier, created_at, updated_at)
                VALUES (?, 'default', ?, ?)
                ON CONFLICT(user_id) DO NOTHING
                """,
                (normalized_user_id, now_iso, now_iso),
            )
            row = connection.execute(
                "SELECT * FROM users WHERE user_id = ?", (normalized_user_id,)
            ).fetchone()
        assert row is not None
        return {
            "user_id": row["user_id"],
            "tier": row["tier"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        """Return a user row for the provided user_id when present."""
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE user_id = ?", (normalized_user_id,)
            ).fetchone()
        if not row:
            return None
        return {
            "user_id": row["user_id"],
            "tier": row["tier"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_user_config(self, user_id: str) -> dict[str, Any] | None:
        """Fetch stored per-user runtime configuration if available."""
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM user_configs WHERE user_id = ?", (normalized_user_id,)
            ).fetchone()
        if not row:
            return None
        config_json = row["config_json"] if "config_json" in row.keys() else None
        if config_json:
            parsed = json.loads(config_json)
            if isinstance(parsed, dict):
                return parsed
        return self._legacy_runtime_config_from_row(row)

    def upsert_user_config(self, user_id: str, config: dict[str, Any]) -> None:
        """Create or update per-user runtime configuration."""
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")
        self.ensure_user(normalized_user_id)
        now_iso = datetime.now(timezone.utc).isoformat()
        legacy = self._legacy_columns_from_runtime_config(config)
        with self._connect() as connection:
            connection.execute(
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    model=excluded.model,
                    max_tool_calls_per_turn=excluded.max_tool_calls_per_turn,
                    sandbox_mode=excluded.sandbox_mode,
                    sandbox_api_url=excluded.sandbox_api_url,
                    sandbox_template_name=excluded.sandbox_template_name,
                    sandbox_namespace=excluded.sandbox_namespace,
                    sandbox_server_port=excluded.sandbox_server_port,
                    sandbox_max_output_chars=excluded.sandbox_max_output_chars,
                    sandbox_local_timeout_seconds=excluded.sandbox_local_timeout_seconds,
                    sandbox_execution_model=excluded.sandbox_execution_model,
                    sandbox_session_idle_ttl_seconds=excluded.sandbox_session_idle_ttl_seconds,
                    config_json=excluded.config_json,
                    updated_at=excluded.updated_at
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
                    json.dumps(config, ensure_ascii=True),
                    now_iso,
                    now_iso,
                ),
            )

    def _legacy_runtime_config_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
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

    def _to_record(self, row: sqlite3.Row) -> dict[str, Any]:
        """Map a session row to an application dictionary."""
        return {
            "session_id": row["session_id"],
            "user_id": row["user_id"] or "",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "title": row["title"],
            "messages": json.loads(row["messages_json"]),
            "ui_messages": json.loads(row["ui_messages_json"]),
            "tool_calls": row["tool_calls"],
            "last_error": row["last_error"],
            "share_id": row["share_id"],
        }

    def upsert_session(self, session: dict[str, Any]) -> None:
        """Insert or update a session record and keep existing share_id when unset."""
        with self._connect() as connection:
            connection.execute(
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
                    share_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    user_id=excluded.user_id,
                    updated_at=excluded.updated_at,
                    title=excluded.title,
                    messages_json=excluded.messages_json,
                    ui_messages_json=excluded.ui_messages_json,
                    tool_calls=excluded.tool_calls,
                    last_error=excluded.last_error,
                    share_id=COALESCE(excluded.share_id, sessions.share_id)
                """,
                (
                    session["session_id"],
                    session.get("user_id") or "",
                    session["created_at"],
                    session["updated_at"],
                    session["title"],
                    json.dumps(session["messages"], ensure_ascii=True),
                    json.dumps(session["ui_messages"], ensure_ascii=True),
                    int(session["tool_calls"]),
                    session.get("last_error"),
                    session.get("share_id"),
                ),
            )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Return a single session by id or None when missing."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return self._to_record(row) if row else None

    def list_sessions(self) -> list[dict[str, Any]]:
        """Return all sessions ordered by most recent update time."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC"
            ).fetchall()
        return [self._to_record(row) for row in rows]

    def list_sessions_for_user(self, user_id: str) -> list[dict[str, Any]]:
        """Return sessions owned by one user ordered by most recent update."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
        return [self._to_record(row) for row in rows]

    def delete_session(self, session_id: str) -> bool:
        """Delete a session record by id and report whether a row was removed."""
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM sessions WHERE session_id = ?", (session_id,)
            )
        return cursor.rowcount > 0

    def delete_session_for_user(self, session_id: str, user_id: str) -> bool:
        """Delete a session record when owned by the provided user."""
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM sessions WHERE session_id = ? AND user_id = ?",
                (session_id, user_id),
            )
        return cursor.rowcount > 0

    def set_share_id(self, session_id: str, share_id: str) -> None:
        """Store a public share id for an existing session."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET share_id = ? WHERE session_id = ?",
                (share_id, session_id),
            )

    def set_share_id_for_user(
        self, session_id: str, user_id: str, share_id: str
    ) -> bool:
        """Store a public share id for a session owned by the provided user."""
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE sessions SET share_id = ? WHERE session_id = ? AND user_id = ?",
                (share_id, session_id, user_id),
            )
        return cursor.rowcount > 0

    def get_session_for_user(
        self, session_id: str, user_id: str
    ) -> dict[str, Any] | None:
        """Return one session by id when owned by the provided user."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
        return self._to_record(row) if row else None

    def get_by_share_id(self, share_id: str) -> dict[str, Any] | None:
        """Return a shared session by share id if present."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE share_id = ?", (share_id,)
            ).fetchone()
        return self._to_record(row) if row else None

    def add_asset(self, asset: dict[str, Any]) -> None:
        """Insert or replace an asset metadata record."""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO assets (
                    asset_id,
                    session_id,
                    tool_call_id,
                    filename,
                    mime_type,
                    storage_path,
                    size_bytes,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        """Fetch a single stored asset record by id."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
        if not row:
            return None
        return {
            "asset_id": row["asset_id"],
            "session_id": row["session_id"],
            "tool_call_id": row["tool_call_id"],
            "filename": row["filename"],
            "mime_type": row["mime_type"],
            "storage_path": row["storage_path"],
            "size_bytes": row["size_bytes"],
            "created_at": row["created_at"],
        }

    def get_asset_for_user(self, asset_id: str, user_id: str) -> dict[str, Any] | None:
        """Fetch an asset by id when it belongs to a session owned by the user."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT a.*
                FROM assets a
                JOIN sessions s ON s.session_id = a.session_id
                WHERE a.asset_id = ?
                  AND s.user_id = ?
                """,
                (asset_id, user_id),
            ).fetchone()
        if not row:
            return None
        return {
            "asset_id": row["asset_id"],
            "session_id": row["session_id"],
            "tool_call_id": row["tool_call_id"],
            "filename": row["filename"],
            "mime_type": row["mime_type"],
            "storage_path": row["storage_path"],
            "size_bytes": row["size_bytes"],
            "created_at": row["created_at"],
        }

    def get_asset_for_share(
        self, asset_id: str, share_id: str
    ) -> dict[str, Any] | None:
        """Fetch an asset by id when it belongs to a publicly shared session."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT a.*
                FROM assets a
                JOIN sessions s ON s.session_id = a.session_id
                WHERE a.asset_id = ?
                  AND s.share_id = ?
                """,
                (asset_id, share_id),
            ).fetchone()
        if not row:
            return None
        return {
            "asset_id": row["asset_id"],
            "session_id": row["session_id"],
            "tool_call_id": row["tool_call_id"],
            "filename": row["filename"],
            "mime_type": row["mime_type"],
            "storage_path": row["storage_path"],
            "size_bytes": row["size_bytes"],
            "created_at": row["created_at"],
        }

    def _to_lease_record(self, row: sqlite3.Row) -> dict[str, Any]:
        """Map a sandbox lease row to an application dictionary."""
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
        """Insert or update a sandbox lease record."""
        with self._connect() as connection:
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
        """Fetch a sandbox lease by id."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sandbox_leases WHERE lease_id = ?", (lease_id,)
            ).fetchone()
        return self._to_lease_record(row) if row else None

    def get_active_sandbox_lease(
        self, scope_type: str, scope_key: str
    ) -> dict[str, Any] | None:
        """Return the most recently used active lease for a scope."""
        with self._connect() as connection:
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
        return self._to_lease_record(row) if row else None

    def list_active_sandbox_leases(self) -> list[dict[str, Any]]:
        """List all active sandbox leases ordered by recent usage."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM sandbox_leases
                WHERE status IN ('pending', 'ready')
                ORDER BY last_used_at DESC
                """
            ).fetchall()
        return [self._to_lease_record(row) for row in rows]

    def list_expired_sandbox_leases(self, now_iso: str) -> list[dict[str, Any]]:
        """List active leases with expiration older than the provided timestamp."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM sandbox_leases
                WHERE status IN ('pending', 'ready')
                  AND expires_at <= ?
                ORDER BY expires_at ASC
                """,
                (now_iso,),
            ).fetchall()
        return [self._to_lease_record(row) for row in rows]

    def mark_sandbox_lease_released(
        self,
        lease_id: str,
        *,
        released_at: str,
        status: str = "released",
        last_error: str | None = None,
    ) -> None:
        """Mark a lease as released/expired and store optional error context."""
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE sandbox_leases
                SET status = ?, released_at = ?, last_error = ?
                WHERE lease_id = ?
                """,
                (status, released_at, last_error, lease_id),
            )
