import inspect
import json
import uuid
from typing import Any, Awaitable, Callable

from langgraph.graph import END

from .state import AgentGraphState


class AgentRuntime:
    """Runs the model/tool LangGraph loop using injected toolkits and callbacks."""

    def __init__(
        self,
        *,
        build_sandbox_toolkit: Callable[[str, dict[str, Any]], Any],
        notify_tool_event: Callable[[dict[str, Any]], Awaitable[None]],
        should_stream_model: Callable[[], bool],
        get_create_completion: Callable[[], Callable[..., Awaitable[Any]]],
        get_create_completion_streaming: Callable[
            [], Callable[..., Awaitable[dict[str, Any]]]
        ],
        tool_error_output: Callable[..., str],
    ) -> None:
        self.build_sandbox_toolkit = build_sandbox_toolkit
        self.notify_tool_event = notify_tool_event
        self.should_stream_model = should_stream_model
        self.get_create_completion = get_create_completion
        self.get_create_completion_streaming = get_create_completion_streaming
        self.tool_error_output = tool_error_output
        self._graph = None

    def set_graph(self, graph: Any) -> None:
        self._graph = graph

    def _last_tool_result(
        self, turn_tool_calls: list[dict[str, Any]], tool_name: str, args_text: str
    ) -> str | None:
        for prior in reversed(turn_tool_calls):
            if prior.get("tool") == tool_name and prior.get("arguments") == args_text:
                result = prior.get("result")
                if isinstance(result, str):
                    return result
        return None

    async def _call_completion_async(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]],
    ) -> Any:
        create_completion = self.get_create_completion()
        parameters = inspect.signature(create_completion).parameters
        if "tools" in parameters:
            return await create_completion(messages, model, tools)
        return await create_completion(messages, model)

    async def _call_completion_streaming_async(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        create_completion_streaming = self.get_create_completion_streaming()
        parameters = inspect.signature(create_completion_streaming).parameters
        if "tools" in parameters:
            return await create_completion_streaming(messages, model, tools)
        return await create_completion_streaming(messages, model)

    async def graph_model_node(self, state: AgentGraphState) -> AgentGraphState:
        tool_calls: list[Any] = []
        final_text = ""
        toolkit = self.build_sandbox_toolkit(
            state["session_id"], state["runtime_config"]
        )
        tools = toolkit.get_openai_tools()

        if self.should_stream_model():
            streamed = await self._call_completion_streaming_async(
                messages=state["messages"],
                model=str(state["runtime_config"]["model"]),
                tools=tools,
            )
            final_text = str(streamed.get("content") or "")
            tool_calls = streamed.get("tool_calls") or []
        else:
            completion = await self._call_completion_async(
                messages=state["messages"],
                model=str(state["runtime_config"]["model"]),
                tools=tools,
            )
            assistant_message = completion.choices[0].message
            final_text = assistant_message.content or ""
            tool_calls = assistant_message.tool_calls or []

        if not tool_calls:
            return {
                **state,
                "messages": state["messages"]
                + [{"role": "assistant", "content": final_text}],
                "pending_tool_calls": [],
                "final_reply": final_text,
            }

        assistant_payload = {
            "role": "assistant",
            "content": final_text,
            "tool_calls": [
                {
                    "id": (
                        tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "")
                    ),
                    "type": (
                        tc.get("type")
                        if isinstance(tc, dict)
                        else getattr(tc, "type", "function")
                    )
                    or "function",
                    "function": {
                        "name": (
                            (tc.get("function") or {}).get("name")
                            if isinstance(tc, dict)
                            else getattr(getattr(tc, "function", None), "name", "")
                        ),
                        "arguments": (
                            (tc.get("function") or {}).get("arguments")
                            if isinstance(tc, dict)
                            else getattr(getattr(tc, "function", None), "arguments", "")
                        ),
                    },
                }
                for tc in tool_calls
            ],
        }
        return {
            **state,
            "messages": state["messages"] + [assistant_payload],
            "pending_tool_calls": assistant_payload["tool_calls"],
        }

    async def graph_tools_node(self, state: AgentGraphState) -> AgentGraphState:
        messages = list(state["messages"])
        turn_tool_calls = list(state["turn_tool_calls"])
        tool_events = list(state["tool_events"])
        tool_call_count = int(state["tool_call_count"])
        pending_tool_calls = list(state.get("pending_tool_calls", []))
        limit_reached = False
        error_text = state.get("error", "")
        final_reply = state.get("final_reply", "")
        toolkit = self.build_sandbox_toolkit(
            state["session_id"], state["runtime_config"]
        )

        for idx, tc in enumerate(pending_tool_calls):
            tool_name = tc.get("function", {}).get("name", "")
            args_text = tc.get("function", {}).get("arguments", "{}")
            tool_call_id = tc.get("id") or f"tool_{uuid.uuid4().hex}"

            if tool_call_count >= int(state["max_tool_calls_per_turn"]):
                limit_reached = True
                error_text = "Tool-calling loop exhausted max tool calls"
                final_reply = "I hit the tool-calling safety limit for this turn."
                for skipped_tc in pending_tool_calls[idx:]:
                    skipped_tool = skipped_tc.get("function", {}).get("name", "")
                    skipped_args = skipped_tc.get("function", {}).get("arguments", "{}")
                    skipped_id = skipped_tc.get("id") or f"tool_{uuid.uuid4().hex}"
                    skipped_output = self.tool_error_output(
                        tool_name=skipped_tool,
                        error="Skipped because tool-calling safety limit was reached",
                    )
                    try:
                        skipped_result: Any = json.loads(skipped_output)
                    except json.JSONDecodeError:
                        skipped_result = skipped_output

                    turn_tool_calls.append(
                        {
                            "tool": skipped_tool,
                            "arguments": skipped_args,
                            "result": skipped_output,
                        }
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": skipped_id,
                            "content": skipped_output,
                        }
                    )
                    tool_events.append(
                        {
                            "tool_call_id": skipped_id,
                            "tool_name": skipped_tool,
                            "args_text": skipped_args,
                            "args": {},
                            "result": skipped_result,
                            "is_error": True,
                            "stored_assets": [],
                        }
                    )
                break

            cached_output = self._last_tool_result(
                turn_tool_calls, tool_name, args_text
            )
            if cached_output is not None:
                # Some model runs immediately re-issue the exact same tool call.
                # Reuse the previous tool output for the LLM context and avoid
                # double-executing the sandbox or duplicating UI tool cards.
                tool_call_count += 1
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": cached_output,
                    }
                )
                continue

            try:
                output, stored_assets = await toolkit.run_tool_call(
                    tool_call_id=tool_call_id,
                    name=tool_name,
                    arguments_json=args_text,
                )
            except Exception as exc:
                output = self.tool_error_output(
                    tool_name=tool_name,
                    error=f"Tool execution failed: {exc}",
                )
                stored_assets = []
            tool_call_count += 1

            turn_tool_calls.append(
                {
                    "tool": tool_name,
                    "arguments": args_text,
                    "result": output,
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": output,
                }
            )

            try:
                parsed_args = json.loads(args_text)
            except json.JSONDecodeError:
                parsed_args = {}

            parsed_result: Any = output
            try:
                parsed_result = json.loads(output)
            except json.JSONDecodeError:
                parsed_result = output

            is_error = isinstance(parsed_result, dict) and not parsed_result.get(
                "ok", True
            )
            tool_events.append(
                {
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "args_text": args_text,
                    "args": parsed_args,
                    "result": parsed_result,
                    "is_error": is_error,
                    "stored_assets": stored_assets,
                }
            )

        if limit_reached:
            messages.append({"role": "assistant", "content": final_reply})

        return {
            **state,
            "messages": messages,
            "pending_tool_calls": [],
            "turn_tool_calls": turn_tool_calls,
            "tool_events": tool_events,
            "tool_call_count": tool_call_count,
            "limit_reached": limit_reached,
            "error": error_text,
            "final_reply": final_reply,
        }

    def route_after_model(self, state: AgentGraphState) -> str:
        if state.get("pending_tool_calls"):
            return "tools"
        return END

    def route_after_tools(self, state: AgentGraphState) -> str:
        if state.get("limit_reached"):
            return END
        return "model"

    async def run_graph_async(
        self,
        *,
        messages: list[dict[str, Any]],
        session_id: str,
        runtime_config: dict[str, Any],
    ) -> AgentGraphState:
        if self._graph is None:
            raise RuntimeError("Agent graph has not been initialized")
        initial_state: AgentGraphState = {
            "session_id": session_id,
            "messages": list(messages),
            "runtime_config": runtime_config,
            "max_tool_calls_per_turn": int(runtime_config["max_tool_calls_per_turn"]),
            "pending_tool_calls": [],
            "turn_tool_calls": [],
            "tool_events": [],
            "tool_call_count": 0,
            "final_reply": "",
            "error": "",
            "limit_reached": False,
        }
        return await self._graph.ainvoke(
            initial_state,
            config={
                "recursion_limit": max(
                    20, int(runtime_config["max_tool_calls_per_turn"]) * 4 + 8
                ),
                "configurable": {"session_id": session_id},
            },
        )
