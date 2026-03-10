import base64
import os
import re
import uuid
from pathlib import Path
from typing import Any

from .session_store import SessionStore


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", name.strip())
    return cleaned or "asset.bin"


class AssetManager:
    def __init__(self, session_store: SessionStore) -> None:
        base = os.getenv("ASSET_STORE_PATH", "/app/data/assets")
        self.base_dir = Path(base)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.session_store = session_store

    def store_base64_asset(
        self,
        *,
        session_id: str,
        tool_call_id: str | None,
        filename: str,
        mime_type: str,
        base64_data: str,
        created_at: str,
    ) -> dict[str, Any]:
        data = base64.b64decode(base64_data)
        asset_id = uuid.uuid4().hex
        safe_name = _safe_filename(filename)
        session_dir = self.base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        storage_path = session_dir / f"{asset_id}-{safe_name}"
        storage_path.write_bytes(data)

        record = {
            "asset_id": asset_id,
            "session_id": session_id,
            "tool_call_id": tool_call_id,
            "filename": safe_name,
            "mime_type": mime_type or "application/octet-stream",
            "storage_path": str(storage_path),
            "size_bytes": len(data),
            "created_at": created_at,
        }
        self.session_store.add_asset(record)
        return {
            **record,
            "view_url": f"/api/assets/{asset_id}",
            "download_url": f"/api/assets/{asset_id}/download",
        }

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        return self.session_store.get_asset(asset_id)
