from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class SessionState:
    session_id: str
    user_id: str
    created_at: str
    updated_at: str
    title: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    ui_messages: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: int = 0
    last_error: str | None = None
    share_id: str | None = None
    sandbox_policy: dict[str, Any] = field(default_factory=dict)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
