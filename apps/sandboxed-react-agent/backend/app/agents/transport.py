import uuid
from typing import Any, Awaitable, Callable

from assistant_stream import RunController

from .ui_state_adapter import AssistantUIStateAdapter


class AssistantTransportRuntime:
    """Coordinates assistant transport streaming using injected UI/session hooks."""

    def __init__(
        self,
        *,
        get_or_create_session: Callable[[str | None, str], Any],
        runtime_context_for_user: Callable[[str], dict[str, Any]],
        normalize_user_parts: Callable[[list[Any]], list[dict[str, str]]],
        new_user_ui_message: Callable[
            [list[dict[str, str]], str | None], dict[str, Any]
        ],
        new_assistant_ui_message: Callable[[], dict[str, Any]],
        sanitize_messages: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
        title_from_text: Callable[[str], str],
        append_tool_update: Callable[..., None],
        stream_text_to_ui: Callable[..., Awaitable[None]],
        run_agent_graph_async: Callable[..., Awaitable[dict[str, Any]]],
        sync_session_ui_from_controller: Callable[[Any, RunController], None],
        ensure_tool_parts_persisted: Callable[
            [dict[str, Any], list[dict[str, Any]]], None
        ],
        normalize_session_ui_messages: Callable[[Any], None],
        persist_session_async: Callable[[Any], Awaitable[None]],
        now_iso: Callable[[], str],
        get_tool_event_listener: Callable[[], Any],
        set_tool_event_listener: Callable[[Any], None],
        ui_state: AssistantUIStateAdapter,
    ) -> None:
        self.get_or_create_session = get_or_create_session
        self.runtime_context_for_user = runtime_context_for_user
        self.normalize_user_parts = normalize_user_parts
        self.new_user_ui_message = new_user_ui_message
        self.new_assistant_ui_message = new_assistant_ui_message
        self.sanitize_messages = sanitize_messages
        self.title_from_text = title_from_text
        self.append_tool_update = append_tool_update
        self.stream_text_to_ui = stream_text_to_ui
        self.run_agent_graph_async = run_agent_graph_async
        self.sync_session_ui_from_controller = sync_session_ui_from_controller
        self.ensure_tool_parts_persisted = ensure_tool_parts_persisted
        self.normalize_session_ui_messages = normalize_session_ui_messages
        self.persist_session_async = persist_session_async
        self.now_iso = now_iso
        self.get_tool_event_listener = get_tool_event_listener
        self.set_tool_event_listener = set_tool_event_listener
        self.ui_state = ui_state

    async def run(self, payload: Any, controller: RunController, user_id: str) -> None:
        runtime_config = self.runtime_context_for_user(user_id)
        self.ui_state.ensure_state(controller)

        existing_session_id = None
        if isinstance(payload.state, dict):
            maybe_session_id = payload.state.get("session_id")
            if isinstance(maybe_session_id, str) and maybe_session_id:
                existing_session_id = maybe_session_id

        try:
            current_session_id = controller.state["session_id"]
            if isinstance(current_session_id, str) and current_session_id:
                existing_session_id = current_session_id
        except KeyError:
            pass

        session = self.get_or_create_session(existing_session_id, user_id)
        controller.state["session_id"] = session.session_id
        self.ui_state.load_session_messages(controller, session.ui_messages)

        user_inputs: list[tuple[list[dict[str, str]], str | None]] = []
        for command in payload.commands:
            if getattr(command, "type", None) != "add-message":
                continue
            message = getattr(command, "message", None)
            if message is None:
                continue
            parts = getattr(message, "parts", []) or []
            if not parts:
                parts = getattr(message, "content", []) or []
            normalized_parts = self.normalize_user_parts(parts)
            if not normalized_parts:
                continue
            user_inputs.append((normalized_parts, getattr(message, "id", None)))

        for normalized_parts, message_id in user_inputs:
            assistant_index: int | None = None
            tool_part_index_by_call: dict[str, int] = {}
            model_text_streamed = False
            try:
                user_ui_message = self.new_user_ui_message(
                    normalized_parts, message_id=message_id
                )
                self.ui_state.append_message(controller, user_ui_message)
                session.ui_messages.append(user_ui_message)

                session.messages = self.sanitize_messages(session.messages)
                user_texts = [
                    part.get("text", "")
                    for part in normalized_parts
                    if part.get("type") == "text"
                ]
                user_images = [
                    part.get("image", "")
                    for part in normalized_parts
                    if part.get("type") == "image"
                ]

                prompt_text = "\n".join([text for text in user_texts if text]).strip()

                if user_images:
                    llm_content: list[dict[str, Any]] = []
                    if prompt_text:
                        llm_content.append({"type": "text", "text": prompt_text})
                    for image in user_images:
                        if image:
                            llm_content.append(
                                {"type": "image_url", "image_url": {"url": image}}
                            )
                    session.messages.append({"role": "user", "content": llm_content})
                else:
                    session.messages.append({"role": "user", "content": prompt_text})

                if session.title == "New chat":
                    session.title = (
                        self.title_from_text(prompt_text)
                        if prompt_text
                        else "Image upload"
                    )
                session.updated_at = self.now_iso()

                assistant_ui_message = self.new_assistant_ui_message()
                assistant_index = len(session.ui_messages)
                self.ui_state.append_message(controller, assistant_ui_message)
                session.ui_messages.append(assistant_ui_message)

                self.append_tool_update(
                    controller,
                    stage="model",
                    status="running",
                    detail="Planning response...",
                )
                await self.stream_text_to_ui(
                    controller,
                    assistant_index=assistant_index,
                    part_index=0,
                    text="Planning response...\n",
                    delay_seconds=0.01,
                )

                async def _live_tool_listener(event: dict[str, Any]) -> None:
                    nonlocal model_text_streamed
                    if assistant_index is None:
                        return
                    phase = str(event.get("phase") or "")

                    if phase == "model_token":
                        token = str(event.get("text") or "")
                        if token:
                            self.ui_state.append_response_text(
                                controller, assistant_index, token
                            )
                            model_text_streamed = True
                        return

                    tool_name = str(event.get("tool_name") or "tool")
                    tool_call_id = str(
                        event.get("tool_call_id") or f"tool_{uuid.uuid4().hex}"
                    )

                    if phase == "start":
                        args_text = str(event.get("args_text") or "{}")
                        part_index = self.ui_state.append_tool_call(
                            controller,
                            assistant_index,
                            tool_call_id=tool_call_id,
                            tool_name=tool_name,
                            args_text=args_text,
                        )
                        tool_part_index_by_call[tool_call_id] = part_index
                        self.append_tool_update(
                            controller,
                            stage="tool",
                            status="running",
                            detail=f"Running {tool_name}",
                            tool=tool_name,
                        )
                        await self.stream_text_to_ui(
                            controller,
                            assistant_index=assistant_index,
                            part_index=0,
                            text=f"Running tool: {tool_name}\n",
                            delay_seconds=0.01,
                        )
                        return

                    if phase != "end":
                        return

                    part_index = tool_part_index_by_call.get(tool_call_id)
                    if part_index is not None:
                        self.ui_state.update_tool_call_result(
                            controller,
                            assistant_index,
                            part_index,
                            args=(
                                event.get("args")
                                if isinstance(event.get("args"), dict)
                                else {}
                            ),
                            result=event.get("result"),
                            is_error=bool(event.get("is_error")),
                        )

                    for asset in event.get("stored_assets", []) or []:
                        if str(asset.get("mime_type", "")).startswith("image/"):
                            self.ui_state.append_image(
                                controller, assistant_index, asset["view_url"]
                            )

                    result = event.get("result")
                    claim_name = ""
                    if isinstance(result, dict):
                        claim_name = str(result.get("claim_name") or "")

                    if claim_name:
                        self.append_tool_update(
                            controller,
                            stage="tool",
                            status="completed",
                            detail=f"Resource ready: {claim_name}",
                            tool=tool_name,
                        )
                        await self.stream_text_to_ui(
                            controller,
                            assistant_index=assistant_index,
                            part_index=0,
                            text=f"Resource ready: {claim_name}\n",
                            delay_seconds=0.01,
                        )

                previous_listener = self.get_tool_event_listener()
                self.set_tool_event_listener(_live_tool_listener)
                try:
                    graph_result = await self.run_agent_graph_async(
                        session.messages,
                        session.session_id,
                        runtime_config,
                    )
                finally:
                    self.set_tool_event_listener(previous_listener)
                session.messages = graph_result["messages"]
                tool_events = graph_result.get("tool_events", [])
                session.tool_calls += len(tool_events)

                if tool_events:
                    await self.stream_text_to_ui(
                        controller,
                        assistant_index=assistant_index,
                        part_index=0,
                        text="Using tools to gather results...\n",
                        delay_seconds=0.01,
                    )

                for event in tool_events:
                    tool_name = str(event.get("tool_name") or "tool")
                    tool_call_id = str(
                        event.get("tool_call_id") or f"tool_{uuid.uuid4().hex}"
                    )

                    if tool_call_id in tool_part_index_by_call:
                        continue

                    args_text = str(event.get("args_text") or "{}")
                    parsed_args = (
                        event.get("args") if isinstance(event.get("args"), dict) else {}
                    )
                    parsed_result = event.get("result")
                    is_error = bool(event.get("is_error"))

                    self.ui_state.append_completed_tool_call(
                        controller,
                        assistant_index,
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        args_text=args_text,
                        args=parsed_args,
                        result=parsed_result,
                        is_error=is_error,
                    )

                    for asset in event.get("stored_assets", []) or []:
                        if str(asset.get("mime_type", "")).startswith("image/"):
                            self.ui_state.append_image(
                                controller, assistant_index, asset["view_url"]
                            )

                    self.append_tool_update(
                        controller,
                        stage="tool",
                        status="completed" if not is_error else "error",
                        detail=f"Finished {tool_name}",
                        tool=tool_name,
                    )
                    await self.stream_text_to_ui(
                        controller,
                        assistant_index=assistant_index,
                        part_index=0,
                        text=f"Finished tool: {tool_name}\n",
                        delay_seconds=0.01,
                    )

                final_text = graph_result.get("final_reply") or ""
                if graph_result.get("limit_reached") and not final_text:
                    final_text = "I hit the tool-calling safety limit for this turn."

                await self.stream_text_to_ui(
                    controller,
                    assistant_index=assistant_index,
                    part_index=0,
                    text="Generating final response...\n",
                    delay_seconds=0.001,
                )
                if not model_text_streamed:
                    await self.stream_text_to_ui(
                        controller,
                        assistant_index=assistant_index,
                        part_index=1,
                        text=final_text,
                        delay_seconds=0.001,
                    )

                self.ui_state.set_complete(controller, assistant_index)
                self.append_tool_update(
                    controller,
                    stage="model",
                    status="completed",
                    detail="Completed response",
                )

                if graph_result.get("limit_reached"):
                    session.last_error = graph_result.get("error") or (
                        "Tool-calling loop exhausted max tool calls"
                    )
                else:
                    session.last_error = graph_result.get("error") or None

                session.updated_at = self.now_iso()
                self.sync_session_ui_from_controller(session, controller)
                if assistant_index is not None and 0 <= assistant_index < len(
                    session.ui_messages
                ):
                    assistant_message = session.ui_messages[assistant_index]
                    if isinstance(assistant_message, dict):
                        self.ensure_tool_parts_persisted(assistant_message, tool_events)
                self.normalize_session_ui_messages(session)
                await self.persist_session_async(session)
            except Exception as exc:
                error_text = str(exc)
                session.last_error = error_text
                if assistant_index is None:
                    assistant_ui_message = self.new_assistant_ui_message()
                    assistant_index = len(session.ui_messages)
                    self.ui_state.append_message(controller, assistant_ui_message)
                    session.ui_messages.append(assistant_ui_message)
                self.append_tool_update(
                    controller,
                    stage="model",
                    status="error",
                    detail="Agent failed while processing the request",
                )
                self.ui_state.append_reasoning_text(
                    controller,
                    assistant_index,
                    "Encountered an error while processing.\n",
                )
                self.ui_state.append_response_text(
                    controller,
                    assistant_index,
                    "I hit an internal error while processing this message. "
                    "Please verify your OPENAI_API_KEY and try again.\n\n"
                    f"Error: {error_text}",
                )
                self.ui_state.set_complete(controller, assistant_index)
                self.sync_session_ui_from_controller(session, controller)
                self.normalize_session_ui_messages(session)
                await self.persist_session_async(session)
