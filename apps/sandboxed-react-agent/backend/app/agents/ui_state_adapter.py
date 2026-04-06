import copy
from typing import Any

from assistant_stream import RunController


class AssistantUIStateAdapter:
    """Small adapter around the transport message state shape used by the frontend."""

    def ensure_state(self, controller: RunController) -> None:
        if controller.state is None:
            controller.state = {}
        if "messages" not in controller.state:
            controller.state["messages"] = []
        if "tool_updates" not in controller.state:
            controller.state["tool_updates"] = []

    def load_session_messages(
        self, controller: RunController, ui_messages: list[dict[str, Any]]
    ) -> None:
        controller.state["messages"] = copy.deepcopy(ui_messages)

    def append_message(self, controller: RunController, message: dict[str, Any]) -> int:
        controller.state["messages"].append(message)
        return len(controller.state["messages"]) - 1

    def assistant_content(
        self, controller: RunController, assistant_index: int
    ) -> list[dict[str, Any]]:
        return controller.state["messages"][assistant_index]["content"]

    def append_reasoning_text(
        self, controller: RunController, assistant_index: int, text: str
    ) -> None:
        self.assistant_content(controller, assistant_index)[0]["text"] += text

    def append_response_text(
        self, controller: RunController, assistant_index: int, text: str
    ) -> None:
        self.assistant_content(controller, assistant_index)[1]["text"] += text

    def append_tool_call(
        self,
        controller: RunController,
        assistant_index: int,
        *,
        tool_call_id: str,
        tool_name: str,
        args_text: str,
    ) -> int:
        content = self.assistant_content(controller, assistant_index)
        content.append(
            {
                "type": "tool-call",
                "toolCallId": tool_call_id,
                "toolName": tool_name,
                "argsText": args_text,
                "args": {},
            }
        )
        return len(content) - 1

    def update_tool_call_result(
        self,
        controller: RunController,
        assistant_index: int,
        part_index: int,
        *,
        args: dict[str, Any],
        result: Any,
        is_error: bool,
    ) -> None:
        part = self.assistant_content(controller, assistant_index)[part_index]
        part["args"] = args
        part["result"] = result
        if is_error:
            part["isError"] = True

    def append_image(
        self, controller: RunController, assistant_index: int, image_url: str
    ) -> None:
        self.assistant_content(controller, assistant_index).append(
            {"type": "image", "image": image_url}
        )

    def append_completed_tool_call(
        self,
        controller: RunController,
        assistant_index: int,
        *,
        tool_call_id: str,
        tool_name: str,
        args_text: str,
        args: dict[str, Any],
        result: Any,
        is_error: bool,
    ) -> None:
        payload = {
            "type": "tool-call",
            "toolCallId": tool_call_id,
            "toolName": tool_name,
            "argsText": args_text,
            "args": args,
            "result": result,
        }
        if is_error:
            payload["isError"] = True
        self.assistant_content(controller, assistant_index).append(payload)

    def set_complete(self, controller: RunController, assistant_index: int) -> None:
        controller.state["messages"][assistant_index]["status"] = {"type": "complete"}
