from typing import Any


def model_token_event(text: str) -> dict[str, Any]:
    return {
        "phase": "model_token",
        "text": text,
    }


def tool_start_event(
    tool_call_id: str, tool_name: str, args_text: str
) -> dict[str, Any]:
    return {
        "phase": "start",
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "args_text": args_text,
    }


def tool_end_event(
    *,
    tool_call_id: str,
    tool_name: str,
    args_text: str,
    args: dict[str, Any],
    result: Any,
    is_error: bool,
    stored_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "phase": "end",
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "args_text": args_text,
        "args": args,
        "result": result,
        "is_error": is_error,
        "stored_assets": stored_assets,
    }
