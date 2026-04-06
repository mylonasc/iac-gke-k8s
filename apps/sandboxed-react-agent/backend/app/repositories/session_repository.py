from typing import Any

from ..services.session_state import SessionState
from ..session_store import SessionStore


class SessionRepository:
    def __init__(self, session_store: SessionStore) -> None:
        self.session_store = session_store

    def to_record(self, session: SessionState) -> dict[str, Any]:
        return {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "title": session.title,
            "messages": session.messages,
            "ui_messages": session.ui_messages,
            "tool_calls": session.tool_calls,
            "last_error": session.last_error,
            "share_id": session.share_id,
        }

    def list_sessions(self) -> list[dict[str, Any]]:
        return self.session_store.list_sessions()

    def upsert(self, session: SessionState) -> None:
        self.session_store.upsert_session(self.to_record(session))

    def delete_for_user(self, session_id: str, user_id: str) -> bool:
        return self.session_store.delete_session_for_user(session_id, user_id)

    def get_by_share_id(self, share_id: str) -> dict[str, Any] | None:
        return self.session_store.get_by_share_id(share_id)

    def set_share_id_for_user(
        self, session_id: str, user_id: str, share_id: str
    ) -> bool:
        return self.session_store.set_share_id_for_user(session_id, user_id, share_id)
