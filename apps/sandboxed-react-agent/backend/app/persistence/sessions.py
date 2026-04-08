import json
from typing import Any, Callable


class SQLiteSessionStore:
    def __init__(self, connect: Callable[[], object]) -> None:
        self.connect = connect

    def _to_record(self, row: Any) -> dict[str, Any]:
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
            "sandbox_policy": (
                json.loads(row["sandbox_policy_json"])
                if row["sandbox_policy_json"]
                else {}
            ),
        }

    def upsert_session(self, session: dict[str, Any]) -> None:
        with self.connect() as connection:
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
                    share_id,
                    sandbox_policy_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    user_id=excluded.user_id,
                    updated_at=excluded.updated_at,
                    title=excluded.title,
                    messages_json=excluded.messages_json,
                    ui_messages_json=excluded.ui_messages_json,
                    tool_calls=excluded.tool_calls,
                    last_error=excluded.last_error,
                    share_id=COALESCE(excluded.share_id, sessions.share_id),
                    sandbox_policy_json=excluded.sandbox_policy_json
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
                    json.dumps(session.get("sandbox_policy") or {}, ensure_ascii=True),
                ),
            )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return self._to_record(row) if row else None

    def list_sessions(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC"
            ).fetchall()
        return [self._to_record(row) for row in rows]

    def list_sessions_for_user(self, user_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
        return [self._to_record(row) for row in rows]

    def delete_session(self, session_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM sessions WHERE session_id = ?", (session_id,)
            )
        return cursor.rowcount > 0

    def delete_session_for_user(self, session_id: str, user_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM sessions WHERE session_id = ? AND user_id = ?",
                (session_id, user_id),
            )
        return cursor.rowcount > 0

    def set_share_id(self, session_id: str, share_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE sessions SET share_id = ? WHERE session_id = ?",
                (share_id, session_id),
            )

    def set_share_id_for_user(
        self, session_id: str, user_id: str, share_id: str
    ) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE sessions SET share_id = ? WHERE session_id = ? AND user_id = ?",
                (share_id, session_id, user_id),
            )
        return cursor.rowcount > 0

    def get_session_for_user(
        self, session_id: str, user_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
        return self._to_record(row) if row else None

    def get_by_share_id(self, share_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE share_id = ?", (share_id,)
            ).fetchone()
        return self._to_record(row) if row else None
