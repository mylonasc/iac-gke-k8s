from typing import Any, TypedDict


class AgentGraphState(TypedDict):
    session_id: str
    messages: list[dict[str, Any]]
    runtime_config: dict[str, Any]
    max_tool_calls_per_turn: int
    pending_tool_calls: list[dict[str, Any]]
    turn_tool_calls: list[dict[str, Any]]
    tool_events: list[dict[str, Any]]
    tool_call_count: int
    final_reply: str
    error: str
    limit_reached: bool
