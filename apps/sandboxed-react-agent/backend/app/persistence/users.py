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
