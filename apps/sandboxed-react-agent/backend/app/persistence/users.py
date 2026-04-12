from datetime import datetime, timezone
from typing import Any, Callable


class SQLiteUserStore:
    def __init__(self, connect: Callable[[], object]) -> None:
        self.connect = connect

    def ensure_user(self, user_id: str) -> dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
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
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return None
        with self.connect() as connection:
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

    def search_users(self, query: str = "", *, limit: int = 20) -> list[dict[str, Any]]:
        normalized_query = str(query or "").strip().lower()
        safe_limit = min(max(int(limit), 1), 100)

        where_clause = ""
        params: tuple[Any, ...] = ()
        if normalized_query:
            where_clause = "WHERE lower(u.user_id) LIKE ?"
            params = (f"%{normalized_query}%",)

        with self.connect() as connection:
            rows = connection.execute(
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
                LIMIT ?
                """,
                (*params, safe_limit),
            ).fetchall()

        return [
            {
                "user_id": row["user_id"],
                "tier": row["tier"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "workspace_status": row["workspace_status"],
                "workspace_updated_at": row["workspace_updated_at"],
                "last_session_at": row["last_session_at"],
            }
            for row in rows
        ]
