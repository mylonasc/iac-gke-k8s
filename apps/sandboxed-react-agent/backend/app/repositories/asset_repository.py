from typing import Any

from ..session_store import SessionStore


class AssetRepository:
    def __init__(self, session_store: SessionStore) -> None:
        self.session_store = session_store

    def add(self, asset: dict[str, Any]) -> None:
        self.session_store.add_asset(asset)

    def get(self, asset_id: str) -> dict[str, Any] | None:
        return self.session_store.get_asset(asset_id)

    def get_for_user(self, asset_id: str, user_id: str) -> dict[str, Any] | None:
        return self.session_store.get_asset_for_user(asset_id, user_id)

    def get_for_share(self, asset_id: str, share_id: str) -> dict[str, Any] | None:
        return self.session_store.get_asset_for_share(asset_id, share_id)
