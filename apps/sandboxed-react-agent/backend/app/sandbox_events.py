from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def sandbox_progress_event(
    *,
    stage: str,
    status: str,
    code: str,
    payload: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Build a normalized sandbox progress event payload.

    This event shape is transport-agnostic and can be consumed by any UI adapter.
    """

    event: dict[str, Any] = {
        "phase": "sandbox_progress",
        "category": "sandbox",
        "stage": str(stage or "unknown"),
        "status": str(status or "info"),
        "code": str(code or "unknown"),
        "payload": payload if isinstance(payload, dict) else {},
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if session_id:
        event["session_id"] = session_id
    return event


def is_sandbox_progress_event(event: dict[str, Any] | None) -> bool:
    if not isinstance(event, dict):
        return False
    return str(event.get("phase") or "") == "sandbox_progress"
