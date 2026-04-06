import asyncio
import copy
import re
import uuid
from typing import Any, Callable

from ..agents.prompts import SYSTEM_PROMPT
from ..agents.session_ui import SessionUIHelper
from ..repositories.session_repository import SessionRepository
from ..repositories.user_repository import UserRepository
from .session_state import SessionState, now_iso


class SessionService:
    def __init__(
        self,
        *,
        session_repository: SessionRepository,
        user_repository: UserRepository,
        session_ui: SessionUIHelper,
        release_session_leases: Callable[[str], None],
        get_session_sandbox: Callable[[str], dict[str, Any]],
    ) -> None:
        self.session_repository = session_repository
        self.user_repository = user_repository
        self.session_ui = session_ui
        self.release_session_leases = release_session_leases
        self.get_session_sandbox = get_session_sandbox
        self.sessions: dict[str, SessionState] = {}
        self._load_sessions_from_store()

    def persist_session(self, session: SessionState) -> None:
        self.session_repository.upsert(session)

    async def persist_session_async(self, session: SessionState) -> None:
        await asyncio.to_thread(self.persist_session, session)

    def ensure_user_profile(self, user_id: str) -> dict[str, Any]:
        return self.user_repository.ensure_user(user_id)

    def hydrate_session_record(self, record: dict[str, Any]) -> SessionState:
        session = SessionState(
            session_id=record["session_id"],
            user_id=record.get("user_id") or "",
            created_at=record["created_at"],
            updated_at=record["updated_at"],
            title=record.get("title") or "New chat",
            messages=record["messages"],
            ui_messages=record["ui_messages"],
            tool_calls=record["tool_calls"],
            last_error=record["last_error"],
            share_id=record.get("share_id"),
        )
        self.session_ui.normalize_session_ui_messages(session)
        self.sessions[session.session_id] = session
        return session

    def _load_sessions_from_store(self) -> None:
        for record in self.session_repository.list_sessions():
            self.hydrate_session_record(record)

    def create_session(
        self, title: str | None = None, user_id: str = ""
    ) -> SessionState:
        if user_id:
            self.ensure_user_profile(user_id)
        now = now_iso()
        state = SessionState(
            session_id=str(uuid.uuid4()),
            user_id=user_id,
            created_at=now,
            updated_at=now,
            title=title or "New chat",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}],
        )
        self.sessions[state.session_id] = state
        self.persist_session(state)
        return state

    def get_or_create_session(
        self, session_id: str | None, user_id: str
    ) -> SessionState:
        if user_id:
            self.ensure_user_profile(user_id)
        if session_id and session_id in self.sessions:
            existing = self.sessions[session_id]
            if existing.user_id != user_id:
                raise PermissionError("Session not found")
            return existing
        return self.create_session(user_id=user_id)

    def reset_session(self, session_id: str, user_id: str) -> bool:
        session = self.sessions.get(session_id)
        if not session or session.user_id != user_id:
            return False
        self.release_session_leases(session_id)
        del self.sessions[session_id]
        self.session_repository.delete_for_user(session_id, user_id)
        return True

    def _session_preview(self, session: SessionState) -> str:
        for message in reversed(session.ui_messages):
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = str(part.get("text") or "").strip()
                    if text:
                        return text[:90]
        return ""

    def list_sessions(self, user_id: str) -> list[dict[str, Any]]:
        sessions = sorted(
            [s for s in self.sessions.values() if s.user_id == user_id],
            key=lambda session: session.updated_at,
            reverse=True,
        )
        return [
            {
                "session_id": session.session_id,
                "title": session.title,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "tool_calls": session.tool_calls,
                "share_id": session.share_id,
                "preview": self._session_preview(session),
                "sandbox": self.get_session_sandbox(session.session_id),
            }
            for session in sessions
        ]

    def get_session(self, session_id: str, user_id: str) -> dict[str, Any] | None:
        session = self.sessions.get(session_id)
        if not session or session.user_id != user_id:
            return None
        self.session_ui.normalize_session_ui_messages(session)
        return {
            "session_id": session.session_id,
            "title": session.title,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "share_id": session.share_id,
            "messages": session.ui_messages,
            "sandbox": self.get_session_sandbox(session_id),
        }

    def title_from_text(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text.strip())
        if not cleaned:
            return "New chat"
        sentence = re.split(r"(?<=[.!?])\s+", cleaned)[0]
        return sentence[:72]

    def sanitize_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sanitized: list[dict[str, Any]] = []
        open_tool_ids: set[str] = set()

        for message in messages:
            role = message.get("role")
            if role == "assistant":
                tool_calls = message.get("tool_calls") or []
                for tc in tool_calls:
                    tc_id = tc.get("id")
                    if tc_id:
                        open_tool_ids.add(tc_id)
                sanitized.append(message)
                continue

            if role == "tool":
                tool_call_id = message.get("tool_call_id")
                if tool_call_id and tool_call_id in open_tool_ids:
                    open_tool_ids.remove(tool_call_id)
                    sanitized.append(message)
                continue

            sanitized.append(message)

        return sanitized

    def get_state_sessions(self, user_id: str | None = None) -> list[SessionState]:
        sessions = list(self.sessions.values())
        if user_id is not None:
            sessions = [session for session in sessions if session.user_id == user_id]
        return sessions
