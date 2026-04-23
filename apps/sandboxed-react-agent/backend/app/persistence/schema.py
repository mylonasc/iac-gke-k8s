import sqlite3
from datetime import datetime, timezone
from typing import Callable, Any


def _execute_sql(
    connection: Any,
    *,
    query: str,
    params: tuple[Any, ...] = (),
    is_sqlite: bool,
) -> None:
    if is_sqlite:
        connection.execute(query, params)
        return
    with connection.cursor() as cur:
        cur.execute(query, params)


def _fetchall_sql(
    connection: Any,
    *,
    query: str,
    params: tuple[Any, ...] = (),
    is_sqlite: bool,
) -> list[Any]:
    if is_sqlite:
        return connection.execute(query, params).fetchall()
    with connection.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def init_schema(connect: Callable[[], Any]) -> None:
    """Create all storage tables and indexes if they do not exist."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with connect() as connection:
        # Detect if it's SQLite or Postgres
        is_sqlite = isinstance(connection, sqlite3.Connection)

        # 1. Users table
        _execute_sql(
            connection,
            query="""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    tier TEXT NOT NULL DEFAULT 'default',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """,
            is_sqlite=is_sqlite,
        )

        # 2. Sessions table
        _execute_sql(
            connection,
            query="""
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
                    share_id TEXT,
                    sandbox_policy_json TEXT
                )
            """,
            is_sqlite=is_sqlite,
        )

        # Sessions column migrations
        if is_sqlite:
            columns = {
                row["name"]
                for row in _fetchall_sql(
                    connection,
                    query="PRAGMA table_info(sessions)",
                    is_sqlite=True,
                )
            }
        else:
            # Postgres check
            columns = {
                row[0]
                for row in _fetchall_sql(
                    connection,
                    query="SELECT column_name FROM information_schema.columns WHERE table_name = 'sessions'",
                    is_sqlite=False,
                )
            }

        if "user_id" not in columns:
            _execute_sql(
                connection,
                query="ALTER TABLE sessions ADD COLUMN user_id TEXT",
                is_sqlite=is_sqlite,
            )
        if "sandbox_policy_json" not in columns:
            _execute_sql(
                connection,
                query="ALTER TABLE sessions ADD COLUMN sandbox_policy_json TEXT",
                is_sqlite=is_sqlite,
            )

        _execute_sql(
            connection,
            query="CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_share_id ON sessions (share_id)",
            is_sqlite=is_sqlite,
        )
        _execute_sql(
            connection,
            query="CREATE INDEX IF NOT EXISTS idx_sessions_user_updated ON sessions (user_id, updated_at DESC)",
            is_sqlite=is_sqlite,
        )

        # 3. User Configs table
        _execute_sql(
            connection,
            query="""
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
            """,
            is_sqlite=is_sqlite,
        )

        if is_sqlite:
            user_config_columns = {
                row["name"]
                for row in _fetchall_sql(
                    connection,
                    query="PRAGMA table_info(user_configs)",
                    is_sqlite=True,
                )
            }
        else:
            user_config_columns = {
                row[0]
                for row in _fetchall_sql(
                    connection,
                    query="SELECT column_name FROM information_schema.columns WHERE table_name = 'user_configs'",
                    is_sqlite=False,
                )
            }

        if "config_json" not in user_config_columns:
            _execute_sql(
                connection,
                query="ALTER TABLE user_configs ADD COLUMN config_json TEXT",
                is_sqlite=is_sqlite,
            )

        # 4. Assets table
        _execute_sql(
            connection,
            query="""
                CREATE TABLE IF NOT EXISTS assets (
                    asset_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    tool_call_id TEXT,
                    filename TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    storage_path TEXT NOT NULL,
                    size_bytes BIGINT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """,
            is_sqlite=is_sqlite,
        )
        _execute_sql(
            connection,
            query="CREATE INDEX IF NOT EXISTS idx_assets_session_id ON assets (session_id)",
            is_sqlite=is_sqlite,
        )

        # 5. Sandbox Leases table
        _execute_sql(
            connection,
            query="""
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
            """,
            is_sqlite=is_sqlite,
        )
        _execute_sql(
            connection,
            query="""
                CREATE INDEX IF NOT EXISTS idx_sandbox_leases_scope
                ON sandbox_leases (scope_type, scope_key, status)
            """,
            is_sqlite=is_sqlite,
        )
        _execute_sql(
            connection,
            query="""
                CREATE INDEX IF NOT EXISTS idx_sandbox_leases_expiry
                ON sandbox_leases (expires_at, status)
            """,
            is_sqlite=is_sqlite,
        )

        # 6. User Workspaces table
        _execute_sql(
            connection,
            query="""
                CREATE TABLE IF NOT EXISTS user_workspaces (
                    workspace_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    status_reason TEXT,
                    bucket_name TEXT NOT NULL,
                    managed_folder_path TEXT NOT NULL,
                    gsa_email TEXT NOT NULL,
                    ksa_name TEXT NOT NULL,
                    derived_template_name TEXT NOT NULL,
                    claim_name TEXT,
                    claim_namespace TEXT,
                    last_provisioned_at TEXT,
                    last_verified_at TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """,
            is_sqlite=is_sqlite,
        )

        if is_sqlite:
            workspace_columns = {
                row["name"]
                for row in _fetchall_sql(
                    connection,
                    query="PRAGMA table_info(user_workspaces)",
                    is_sqlite=True,
                )
            }
        else:
            workspace_columns = {
                row[0]
                for row in _fetchall_sql(
                    connection,
                    query="SELECT column_name FROM information_schema.columns WHERE table_name = 'user_workspaces'",
                    is_sqlite=False,
                )
            }

        if "status_reason" not in workspace_columns:
            _execute_sql(
                connection,
                query="ALTER TABLE user_workspaces ADD COLUMN status_reason TEXT",
                is_sqlite=is_sqlite,
            )

        # 7. Workspace Jobs table
        _execute_sql(
            connection,
            query="""
                CREATE TABLE IF NOT EXISTS workspace_jobs (
                    job_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    workspace_id TEXT,
                    status TEXT NOT NULL,
                    reconcile_ready INTEGER NOT NULL DEFAULT 0,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    not_before_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    lease_expires_at TEXT,
                    worker_id TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    FOREIGN KEY (workspace_id) REFERENCES user_workspaces(workspace_id) ON DELETE SET NULL
                )
            """,
            is_sqlite=is_sqlite,
        )

        if is_sqlite:
            workspace_job_columns = {
                row["name"]
                for row in _fetchall_sql(
                    connection,
                    query="PRAGMA table_info(workspace_jobs)",
                    is_sqlite=True,
                )
            }
        else:
            workspace_job_columns = {
                row[0]
                for row in _fetchall_sql(
                    connection,
                    query="SELECT column_name FROM information_schema.columns WHERE table_name = 'workspace_jobs'",
                    is_sqlite=False,
                )
            }

        if "not_before_at" not in workspace_job_columns:
            _execute_sql(
                connection,
                query="ALTER TABLE workspace_jobs ADD COLUMN not_before_at TEXT",
                is_sqlite=is_sqlite,
            )

        _execute_sql(
            connection,
            query="""
                CREATE INDEX IF NOT EXISTS idx_user_workspaces_status
                ON user_workspaces (status, updated_at DESC)
            """,
            is_sqlite=is_sqlite,
        )
        _execute_sql(
            connection,
            query="""
                CREATE INDEX IF NOT EXISTS idx_workspace_jobs_status_created
                ON workspace_jobs (status, created_at ASC)
            """,
            is_sqlite=is_sqlite,
        )
        _execute_sql(
            connection,
            query="""
                CREATE INDEX IF NOT EXISTS idx_workspace_jobs_not_before
                ON workspace_jobs (status, not_before_at)
            """,
            is_sqlite=is_sqlite,
        )
        _execute_sql(
            connection,
            query="""
                CREATE INDEX IF NOT EXISTS idx_workspace_jobs_user_status
                ON workspace_jobs (user_id, status, created_at ASC)
            """,
            is_sqlite=is_sqlite,
        )

        # Backfill users from sessions if missing
        if is_sqlite:
            _execute_sql(
                connection,
                query="""
                    INSERT OR IGNORE INTO users (user_id, tier, created_at, updated_at)
                    SELECT DISTINCT user_id, 'default', ?, ?
                    FROM sessions
                    WHERE user_id IS NOT NULL AND user_id != ''
                """,
                params=(now_iso, now_iso),
                is_sqlite=True,
            )
        else:
            _execute_sql(
                connection,
                query="""
                    INSERT INTO users (user_id, tier, created_at, updated_at)
                    SELECT DISTINCT user_id, 'default', %s, %s
                    FROM sessions
                    WHERE user_id IS NOT NULL AND user_id != ''
                    ON CONFLICT (user_id) DO NOTHING
                """,
                params=(now_iso, now_iso),
                is_sqlite=False,
            )
