import asyncio
import copy
import re
import uuid
from typing import Any, Callable

from assistant_stream import RunController


def _token_chunks(text: str) -> list[str]:
    if not text:
        return []
    chunks = re.findall(r"\S+\s*|\s+", text)
    return chunks or [text]


class SessionUIHelper:
    """Encapsulates session/UI message shaping and streaming helpers."""

    def __init__(self, *, now_iso: Callable[[], str]) -> None:
        self.now_iso = now_iso

    def normalize_session_ui_messages(self, session: Any) -> None:
        normalized: list[dict[str, Any]] = []
        changed = False
        for message in session.ui_messages:
            if not isinstance(message, dict):
                normalized.append(message)
                continue

            if message.get("role") != "assistant":
                normalized.append(message)
                continue

            status = message.get("status")
            if isinstance(status, dict) and status.get("type") == "running":
                message = dict(message)
                message["status"] = {"type": "complete"}
                changed = True
            normalized.append(message)

        if changed:
            session.ui_messages = normalized

    def sync_session_ui_from_controller(
        self, session: Any, controller: RunController
    ) -> None:
        state_messages = controller.state.get("messages") if controller.state else None
        if isinstance(state_messages, list):
            session.ui_messages = copy.deepcopy(state_messages)

    def normalize_user_parts(self, parts: list[Any]) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for part in parts:
            part_type = None
            text_value = None
            image_value = None
            if isinstance(part, dict):
                part_type = part.get("type")
                text_value = part.get("text")
                image_value = part.get("image")
            else:
                part_type = getattr(part, "type", None)
                text_value = getattr(part, "text", None)
                image_value = getattr(part, "image", None)

            if part_type == "text" and isinstance(text_value, str) and text_value:
                normalized.append({"type": "text", "text": text_value})
            elif part_type == "image" and isinstance(image_value, str) and image_value:
                normalized.append({"type": "image", "image": image_value})

        return normalized

    def new_user_ui_message(
        self, parts: list[dict[str, str]], message_id: str | None = None
    ) -> dict[str, Any]:
        return {
            "id": message_id or str(uuid.uuid4()),
            "role": "user",
            "content": parts,
        }

    def new_assistant_ui_message(self) -> dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "role": "assistant",
            "status": {"type": "running"},
            "content": [
                {"type": "reasoning", "text": ""},
                {"type": "text", "text": ""},
            ],
        }

    def append_tool_update(
        self,
        controller: RunController,
        *,
        stage: str,
        status: str,
        detail: str,
        tool: str | None = None,
    ) -> None:
        controller.state["tool_updates"].append(
            {
                "id": str(uuid.uuid4()),
                "stage": stage,
                "status": status,
                "tool": tool,
                "detail": detail,
                "timestamp": self.now_iso(),
            }
        )

    def ensure_tool_parts_persisted(
        self, assistant_message: dict[str, Any], tool_events: list[dict[str, Any]]
    ) -> None:
        content = assistant_message.get("content")
        if not isinstance(content, list):
            return

        existing_tool_ids = {
            str(part.get("toolCallId") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "tool-call"
        }

        existing_images = {
            str(part.get("image") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "image"
        }

        for event in tool_events:
            tool_call_id = str(event.get("tool_call_id") or "")
            tool_name = str(event.get("tool_name") or "tool")
            args_text = str(event.get("args_text") or "{}")
            parsed_args = (
                event.get("args") if isinstance(event.get("args"), dict) else {}
            )
            parsed_result = event.get("result")
            is_error = bool(event.get("is_error"))

            if tool_call_id and tool_call_id not in existing_tool_ids:
                content.append(
                    {
                        "type": "tool-call",
                        "toolCallId": tool_call_id,
                        "toolName": tool_name,
                        "argsText": args_text,
                        "args": parsed_args,
                        "result": parsed_result,
                        **({"isError": True} if is_error else {}),
                    }
                )
                existing_tool_ids.add(tool_call_id)

            for asset in event.get("stored_assets", []) or []:
                view_url = str(asset.get("view_url") or "")
                if (
                    view_url
                    and str(asset.get("mime_type", "")).startswith("image/")
                    and view_url not in existing_images
                ):
                    content.append({"type": "image", "image": view_url})
                    existing_images.add(view_url)

    async def stream_text_to_ui(
        self,
        controller: RunController,
        *,
        assistant_index: int,
        part_index: int,
        text: str,
        delay_seconds: float,
    ) -> None:
        for chunk in _token_chunks(text):
            controller.state["messages"][assistant_index]["content"][part_index][
                "text"
            ] += chunk
            await asyncio.sleep(delay_seconds)
