from typing import Any, Callable


class SQLiteAssetStore:
    def __init__(self, connect: Callable[[], object]) -> None:
        self.connect = connect

    def _to_record(self, row: Any) -> dict[str, Any]:
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

    def add_asset(self, asset: dict[str, Any]) -> None:
        with self.connect() as connection:
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
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
        return self._to_record(row) if row else None

    def get_asset_for_user(self, asset_id: str, user_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
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
        return self._to_record(row) if row else None

    def get_asset_for_share(
        self, asset_id: str, share_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
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
        return self._to_record(row) if row else None
