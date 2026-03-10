import json
import os
import sqlite3
from pathlib import Path
from typing import Any


class SessionStore:
    def __init__(self, db_path: str | None = None) -> None:
        default_path = os.getenv("SESSION_STORE_PATH", "/app/data/sessions.db")
        self.db_path = db_path or default_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
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
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_share_id ON sessions (share_id)"
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

    def _to_record(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "session_id": row["session_id"],
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
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions (
                    session_id,
                    created_at,
                    updated_at,
                    title,
                    messages_json,
                    ui_messages_json,
                    tool_calls,
                    last_error,
                    share_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
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
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return self._to_record(row) if row else None

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC"
            ).fetchall()
        return [self._to_record(row) for row in rows]

    def delete_session(self, session_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM sessions WHERE session_id = ?", (session_id,)
            )
        return cursor.rowcount > 0

    def set_share_id(self, session_id: str, share_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET share_id = ? WHERE session_id = ?",
                (share_id, session_id),
            )

    def get_by_share_id(self, share_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE share_id = ?", (share_id,)
            ).fetchone()
        return self._to_record(row) if row else None

    def add_asset(self, asset: dict[str, Any]) -> None:
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
