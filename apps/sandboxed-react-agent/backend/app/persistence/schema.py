from datetime import datetime, timezone
from typing import Callable


def init_schema(connect: Callable[[], object]) -> None:
    """Create all storage tables and indexes if they do not exist."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with connect() as connection:
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
            for row in connection.execute("PRAGMA table_info(user_configs)").fetchall()
        }
        if "config_json" not in user_config_columns:
            connection.execute("ALTER TABLE user_configs ADD COLUMN config_json TEXT")
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
