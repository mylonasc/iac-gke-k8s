from typing import Any

from ...asset_manager import AssetManager


class AssetFacade:
    """Thin wrapper around asset storage for toolkits and runtimes."""

    def __init__(self, asset_manager: AssetManager) -> None:
        self.asset_manager = asset_manager

    def store_execution_assets(
        self,
        *,
        session_id: str,
        tool_call_id: str | None,
        assets: list[dict[str, str]] | None,
        created_at: str,
    ) -> list[dict[str, Any]]:
        stored_assets: list[dict[str, Any]] = []
        for asset in assets or []:
            try:
                stored_asset = self.asset_manager.store_base64_asset(
                    session_id=session_id,
                    tool_call_id=tool_call_id,
                    filename=asset.get("filename", "asset.bin"),
                    mime_type=asset.get("mime_type", "application/octet-stream"),
                    base64_data=asset.get("base64", ""),
                    created_at=created_at,
                )
                stored_assets.append(stored_asset)
            except Exception:
                continue
        return stored_assets
