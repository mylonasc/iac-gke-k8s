from typing import Any

from ..session_store import SessionStore


class UserConfigRepository:
    def __init__(self, session_store: SessionStore) -> None:
        self.session_store = session_store

    def get_config(self, user_id: str) -> dict[str, Any] | None:
        return self.session_store.get_user_config(user_id)

    def upsert_config(self, user_id: str, config: dict[str, Any]) -> None:
        self.session_store.upsert_user_config(user_id, config)
