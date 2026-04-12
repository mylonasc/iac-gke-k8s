from typing import Any

from ..session_store import SessionStore


class UserRepository:
    def __init__(self, session_store: SessionStore) -> None:
        self.session_store = session_store

    def ensure_user(self, user_id: str) -> dict[str, Any]:
        return self.session_store.ensure_user(user_id)

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        return self.session_store.get_user(user_id)

    def search_users(self, query: str = "", *, limit: int = 20) -> list[dict[str, Any]]:
        return self.session_store.search_users(query=query, limit=limit)
