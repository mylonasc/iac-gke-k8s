import asyncio
import copy
import inspect
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TypedDict

from assistant_stream import RunController
from langgraph.graph import END, StateGraph
from openai import AsyncOpenAI

from .asset_manager import AssetManager
from .sandbox_lifecycle import SandboxLifecycleService
from .sandbox_manager import SandboxManager
from .session_store import SessionStore


SYSTEM_PROMPT = (
    "You are a helpful coding agent. "
    "When the user asks to run code or inspect runtime behavior, prefer tools. "
    "Keep responses concise and include key findings from tool outputs. "
    "When writing math in markdown, always use dollar-delimited LaTeX: $...$ for inline and $$...$$ for blocks; never use \\( ... \\) or \\[ ... \\]. "
    "For simple computations, run one tool call at most, then provide the final answer. "
    "When producing files or images in python/shell tools, you MUST call expose_asset('path/to/file') "
    "inside sandbox_exec_python before finishing. If you save a plot/file and do not expose it, "
    "the UI will not be able to render/download it."
)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "sandbox_exec_python",
            "description": "Run Python code in an isolated Agent Sandbox runtime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute. REQUIRED: after creating any image/file you want in chat, call expose_asset('/absolute/or/relative/path').",
                    }
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_exec_shell",
            "description": "Run a shell command in an isolated Agent Sandbox runtime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute. If files are created, run a python helper that calls expose_asset(path) so assets are available to API/UI.",
                    }
                },
                "required": ["command"],
            },
        },
    },
]


@dataclass
class SessionState:
    session_id: str
    created_at: str
    updated_at: str
    title: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    ui_messages: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: int = 0
    last_error: str | None = None
    share_id: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _token_chunks(text: str) -> list[str]:
    if not text:
        return []
    chunks = re.findall(r"\S+\s*|\s+", text)
    return chunks or [text]


class AgentGraphState(TypedDict):
    session_id: str
    messages: list[dict[str, Any]]
    pending_tool_calls: list[dict[str, Any]]
    turn_tool_calls: list[dict[str, Any]]
    tool_events: list[dict[str, Any]]
    tool_call_count: int
    final_reply: str
    error: str
    limit_reached: bool


class SandboxedReactAgent:
    """Main orchestration layer for model calls, tools, and session state."""

    def __init__(self) -> None:
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.max_tool_calls_per_turn = int(
            os.getenv("AGENT_MAX_TOOL_CALLS_PER_TURN", "4")
        )
        self.async_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.sandbox_manager = SandboxManager()
        self.session_store = SessionStore()
        self.sandbox_lifecycle = SandboxLifecycleService(
            sandbox_manager=self.sandbox_manager,
            session_store=self.session_store,
        )
        self.asset_manager = AssetManager(self.session_store)
        self.sessions: dict[str, SessionState] = {}
        self._tool_event_listener: Any = None
        self._agent_graph = self._build_agent_graph()
        self._load_sessions_from_store()

    async def _notify_tool_event(self, event: dict[str, Any]) -> None:
        listener = self._tool_event_listener
        if listener is None:
            return
        try:
            maybe = listener(event)
            if inspect.isawaitable(maybe):
                await maybe
        except Exception:
            return

    def _session_to_dict(self, session: SessionState) -> dict[str, Any]:
        return {
            "session_id": session.session_id,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "title": session.title,
            "messages": session.messages,
            "ui_messages": session.ui_messages,
            "tool_calls": session.tool_calls,
            "last_error": session.last_error,
            "share_id": session.share_id,
        }

    def _persist_session(self, session: SessionState) -> None:
        self.session_store.upsert_session(self._session_to_dict(session))

    def _load_sessions_from_store(self) -> None:
        for record in self.session_store.list_sessions():
            self.sessions[record["session_id"]] = SessionState(
                session_id=record["session_id"],
                created_at=record["created_at"],
                updated_at=record["updated_at"],
                title=record.get("title") or "New chat",
                messages=record["messages"],
                ui_messages=record["ui_messages"],
                tool_calls=record["tool_calls"],
                last_error=record["last_error"],
                share_id=record.get("share_id"),
            )
            self._normalize_session_ui_messages(self.sessions[record["session_id"]])

    def _normalize_session_ui_messages(self, session: SessionState) -> None:
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

    def _sync_session_ui_from_controller(
        self, session: SessionState, controller: RunController
    ) -> None:
        state_messages = controller.state.get("messages") if controller.state else None
        if isinstance(state_messages, list):
            session.ui_messages = copy.deepcopy(state_messages)

    def _finalize_assistant_message_status(
        self, controller: RunController, assistant_index: int | None
    ) -> None:
        if assistant_index is None:
            return
        if controller.state is None:
            return
        messages = controller.state.get("messages")
        if not isinstance(messages, list):
            return
        if assistant_index < 0 or assistant_index >= len(messages):
            return
        message = messages[assistant_index]
        if isinstance(message, dict):
            message["status"] = {"type": "complete"}

    def _title_from_text(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text.strip())
        if not cleaned:
            return "New chat"
        sentence = re.split(r"(?<=[.!?])\s+", cleaned)[0]
        return sentence[:72]

    def _sanitize_messages(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
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

    def _normalize_user_parts(self, parts: list[Any]) -> list[dict[str, str]]:
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

    def _new_user_ui_message(
        self, parts: list[dict[str, str]], message_id: str | None = None
    ) -> dict[str, Any]:
        return {
            "id": message_id or str(uuid.uuid4()),
            "role": "user",
            "content": parts,
        }

    def _new_assistant_ui_message(self) -> dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "role": "assistant",
            "status": {"type": "running"},
            "content": [
                {"type": "reasoning", "text": ""},
                {"type": "text", "text": ""},
            ],
        }

    def _append_tool_update(
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
                "timestamp": _now_iso(),
            }
        )

    def _ensure_tool_parts_persisted(
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

    async def _stream_text_to_ui(
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

    def get_runtime_config(self) -> dict[str, Any]:
        """Return current model and sandbox runtime configuration."""
        sandbox_config = self.sandbox_manager.get_config()
        sandbox_config.update(self.sandbox_lifecycle.get_config())
        return {
            "model": self.model,
            "max_tool_calls_per_turn": self.max_tool_calls_per_turn,
            "sandbox": sandbox_config,
        }

    def update_runtime_config(
        self,
        model: str | None = None,
        max_tool_calls_per_turn: int | None = None,
        sandbox_mode: str | None = None,
        sandbox_api_url: str | None = None,
        sandbox_template_name: str | None = None,
        sandbox_namespace: str | None = None,
        sandbox_server_port: int | None = None,
        sandbox_max_output_chars: int | None = None,
        sandbox_local_timeout_seconds: int | None = None,
        sandbox_execution_model: str | None = None,
        sandbox_session_idle_ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        if model is not None:
            self.model = model
        if max_tool_calls_per_turn is not None:
            if max_tool_calls_per_turn < 1:
                raise ValueError("max_tool_calls_per_turn must be >= 1")
            self.max_tool_calls_per_turn = max_tool_calls_per_turn

        self.sandbox_manager.update_config(
            mode=sandbox_mode,
            api_url=sandbox_api_url,
            template_name=sandbox_template_name,
            namespace=sandbox_namespace,
            server_port=sandbox_server_port,
            max_output_chars=sandbox_max_output_chars,
            local_timeout_seconds=sandbox_local_timeout_seconds,
        )
        self.sandbox_lifecycle.update_config(
            execution_model=sandbox_execution_model,
            session_idle_ttl_seconds=sandbox_session_idle_ttl_seconds,
        )

        return self.get_runtime_config()

    def create_session(self, title: str | None = None) -> SessionState:
        session_id = str(uuid.uuid4())
        now = _now_iso()
        state = SessionState(
            session_id=session_id,
            created_at=now,
            updated_at=now,
            title=title or "New chat",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}],
        )
        self.sessions[session_id] = state
        self._persist_session(state)
        return state

    def get_or_create_session(self, session_id: str | None) -> SessionState:
        if session_id and session_id in self.sessions:
            return self.sessions[session_id]
        return self.create_session()

    def _run_tool(
        self,
        *,
        session_id: str,
        tool_call_id: str | None,
        name: str,
        arguments_json: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Execute a tool call and return payload plus stored asset metadata."""
        try:
            parsed = json.loads(arguments_json or "{}")
        except json.JSONDecodeError as exc:
            return (
                self._tool_error_output(
                    tool_name=name,
                    error=f"Invalid tool arguments JSON: {exc.msg}",
                ),
                [],
            )

        if not isinstance(parsed, dict):
            return (
                self._tool_error_output(
                    tool_name=name,
                    error="Invalid tool arguments payload type",
                ),
                [],
            )

        result = None
        if name == "sandbox_exec_python":
            code = parsed.get("code", "")
            result = self.sandbox_lifecycle.exec_python(session_id, code)
        elif name == "sandbox_exec_shell":
            command = parsed.get("command", "")
            result = self.sandbox_lifecycle.exec_shell(session_id, command)
        else:
            return (
                self._tool_error_output(
                    tool_name=name, error=f"Unsupported tool: {name}"
                ),
                [],
            )

        stored_assets: list[dict[str, Any]] = []
        for asset in result.assets or []:
            try:
                stored_asset = self.asset_manager.store_base64_asset(
                    session_id=session_id,
                    tool_call_id=tool_call_id,
                    filename=asset.get("filename", "asset.bin"),
                    mime_type=asset.get("mime_type", "application/octet-stream"),
                    base64_data=asset.get("base64", ""),
                    created_at=_now_iso(),
                )
                stored_assets.append(stored_asset)
            except Exception:
                continue

        payload = {
            "tool": result.tool_name,
            "ok": result.ok,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "error": result.error,
            "lease_id": result.lease_id,
            "claim_name": result.claim_name,
            "assets": [
                {
                    "asset_id": asset["asset_id"],
                    "filename": asset["filename"],
                    "mime_type": asset["mime_type"],
                    "view_url": asset["view_url"],
                    "download_url": asset["download_url"],
                }
                for asset in stored_assets
            ],
        }
        return json.dumps(payload, ensure_ascii=True), stored_assets

    def _tool_error_output(self, *, tool_name: str, error: str) -> str:
        return json.dumps(
            {
                "tool": tool_name,
                "ok": False,
                "stdout": "",
                "stderr": "",
                "exit_code": None,
                "error": error,
                "lease_id": None,
                "claim_name": None,
                "assets": [],
            },
            ensure_ascii=True,
        )

    async def _run_tool_async(
        self,
        *,
        session_id: str,
        tool_call_id: str | None,
        name: str,
        arguments_json: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        return await asyncio.to_thread(
            self._run_tool,
            session_id=session_id,
            tool_call_id=tool_call_id,
            name=name,
            arguments_json=arguments_json,
        )

    async def _persist_session_async(self, session: SessionState) -> None:
        await asyncio.to_thread(self._persist_session, session)

    async def _create_completion_async(self, messages: list[dict[str, Any]]) -> Any:
        return await self.async_client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.2,
        )

    async def _create_completion_streaming_async(
        self, messages: list[dict[str, Any]]
    ) -> dict[str, Any]:
        stream = await self.async_client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.2,
            stream=True,
        )

        text_chunks: list[str] = []
        tool_calls_by_index: dict[int, dict[str, Any]] = {}

        async for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            if delta is None:
                continue

            delta_text = getattr(delta, "content", None)
            if isinstance(delta_text, str) and delta_text:
                text_chunks.append(delta_text)
                await self._notify_tool_event(
                    {
                        "phase": "model_token",
                        "text": delta_text,
                    }
                )

            for tc in getattr(delta, "tool_calls", None) or []:
                index = int(getattr(tc, "index", 0) or 0)
                entry = tool_calls_by_index.setdefault(
                    index,
                    {
                        "id": "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    },
                )

                tc_id = getattr(tc, "id", None)
                if isinstance(tc_id, str) and tc_id:
                    entry["id"] = tc_id

                tc_type = getattr(tc, "type", None)
                if isinstance(tc_type, str) and tc_type:
                    entry["type"] = tc_type

                fn = getattr(tc, "function", None)
                if fn is None:
                    continue
                fn_name = getattr(fn, "name", None)
                if isinstance(fn_name, str) and fn_name:
                    entry["function"]["name"] += fn_name
                fn_args = getattr(fn, "arguments", None)
                if isinstance(fn_args, str) and fn_args:
                    entry["function"]["arguments"] += fn_args

        return {
            "content": "".join(text_chunks),
            "tool_calls": [
                tool_calls_by_index[index]
                for index in sorted(tool_calls_by_index.keys())
            ],
        }

    async def _graph_model_node(self, state: AgentGraphState) -> AgentGraphState:
        tool_calls: list[Any] = []
        final_text = ""

        if self._tool_event_listener is not None:
            streamed = await self._create_completion_streaming_async(state["messages"])
            final_text = str(streamed.get("content") or "")
            tool_calls = streamed.get("tool_calls") or []
        else:
            completion = await self._create_completion_async(state["messages"])
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

    async def _graph_tools_node(self, state: AgentGraphState) -> AgentGraphState:
        messages = list(state["messages"])
        turn_tool_calls = list(state["turn_tool_calls"])
        tool_events = list(state["tool_events"])
        tool_call_count = int(state["tool_call_count"])
        pending_tool_calls = list(state.get("pending_tool_calls", []))
        limit_reached = False
        error_text = state.get("error", "")
        final_reply = state.get("final_reply", "")

        for idx, tc in enumerate(pending_tool_calls):
            tool_name = tc.get("function", {}).get("name", "")
            args_text = tc.get("function", {}).get("arguments", "{}")
            tool_call_id = tc.get("id") or f"tool_{uuid.uuid4().hex}"

            if tool_call_count >= self.max_tool_calls_per_turn:
                limit_reached = True
                error_text = "Tool-calling loop exhausted max tool calls"
                final_reply = "I hit the tool-calling safety limit for this turn."
                for skipped_tc in pending_tool_calls[idx:]:
                    skipped_tool = skipped_tc.get("function", {}).get("name", "")
                    skipped_args = skipped_tc.get("function", {}).get("arguments", "{}")
                    skipped_id = skipped_tc.get("id") or f"tool_{uuid.uuid4().hex}"
                    skipped_output = self._tool_error_output(
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

            await self._notify_tool_event(
                {
                    "phase": "start",
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "args_text": args_text,
                }
            )

            try:
                output, stored_assets = await self._run_tool_async(
                    session_id=state["session_id"],
                    tool_call_id=tool_call_id,
                    name=tool_name,
                    arguments_json=args_text,
                )
            except Exception as exc:
                output = self._tool_error_output(
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
            await self._notify_tool_event(
                {
                    "phase": "end",
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

    def _route_after_model(self, state: AgentGraphState) -> str:
        if state.get("pending_tool_calls"):
            return "tools"
        return END

    def _route_after_tools(self, state: AgentGraphState) -> str:
        if state.get("limit_reached"):
            return END
        return "model"

    def _build_agent_graph(self):
        graph = StateGraph(AgentGraphState)
        graph.add_node("model", self._graph_model_node)
        graph.add_node("tools", self._graph_tools_node)
        graph.set_entry_point("model")
        graph.add_conditional_edges("model", self._route_after_model)
        graph.add_conditional_edges("tools", self._route_after_tools)
        return graph.compile()

    async def _run_agent_graph_async(
        self, messages: list[dict[str, Any]], session_id: str
    ) -> AgentGraphState:
        initial_state: AgentGraphState = {
            "session_id": session_id,
            "messages": list(messages),
            "pending_tool_calls": [],
            "turn_tool_calls": [],
            "tool_events": [],
            "tool_call_count": 0,
            "final_reply": "",
            "error": "",
            "limit_reached": False,
        }
        result = await self._agent_graph.ainvoke(
            initial_state,
            config={
                "recursion_limit": max(20, self.max_tool_calls_per_turn * 4 + 8),
                "configurable": {"session_id": session_id},
            },
        )
        return result

    def chat(self, user_message: str, session_id: str | None = None) -> dict[str, Any]:
        state = self.get_or_create_session(session_id)
        state.messages = self._sanitize_messages(state.messages)
        state.updated_at = _now_iso()
        state.messages.append({"role": "user", "content": user_message})
        if state.title == "New chat":
            state.title = self._title_from_text(user_message)
        try:
            result = asyncio.run(
                self._run_agent_graph_async(state.messages, state.session_id)
            )
            state.messages = result["messages"]
            state.tool_calls += len(result.get("tool_events", []))
            state.updated_at = _now_iso()

            if result.get("limit_reached"):
                state.last_error = result.get("error") or (
                    "Tool-calling loop exhausted max tool calls"
                )
            else:
                state.last_error = result.get("error") or None

            self._persist_session(state)
            reply = result.get("final_reply") or ""
            if not reply and result.get("limit_reached"):
                reply = "I hit the tool-calling safety limit for this turn."

            response: dict[str, Any] = {
                "session_id": state.session_id,
                "reply": reply,
                "tool_calls": result.get("turn_tool_calls", []),
            }
            if state.last_error:
                response["error"] = state.last_error
            return response
        except Exception as exc:
            state.last_error = str(exc)
            if (
                "tool_call_ids did not have response messages" in state.last_error
                or "messages with role 'tool' must be a response" in state.last_error
            ):
                state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            self._persist_session(state)
            return {
                "session_id": state.session_id,
                "reply": "The agent failed while processing your request.",
                "tool_calls": [],
                "error": state.last_error,
            }

    async def run_assistant_transport(
        self, payload: Any, controller: RunController
    ) -> None:
        if controller.state is None:
            controller.state = {}
        if "messages" not in controller.state:
            controller.state["messages"] = []
        if "tool_updates" not in controller.state:
            controller.state["tool_updates"] = []

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

        session = self.get_or_create_session(existing_session_id)
        controller.state["session_id"] = session.session_id
        controller.state["messages"] = copy.deepcopy(session.ui_messages)

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
            normalized_parts = self._normalize_user_parts(parts)
            if not normalized_parts:
                continue
            user_inputs.append((normalized_parts, getattr(message, "id", None)))

        for normalized_parts, message_id in user_inputs:
            assistant_index: int | None = None
            tool_part_index_by_call: dict[str, int] = {}
            model_text_streamed = False
            try:
                user_ui_message = self._new_user_ui_message(
                    normalized_parts, message_id=message_id
                )
                controller.state["messages"].append(user_ui_message)
                session.ui_messages.append(user_ui_message)

                session.messages = self._sanitize_messages(session.messages)
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
                        self._title_from_text(prompt_text)
                        if prompt_text
                        else "Image upload"
                    )
                session.updated_at = _now_iso()

                assistant_ui_message = self._new_assistant_ui_message()
                assistant_index = len(session.ui_messages)
                controller.state["messages"].append(assistant_ui_message)
                session.ui_messages.append(assistant_ui_message)
                assert assistant_index is not None

                self._append_tool_update(
                    controller,
                    stage="model",
                    status="running",
                    detail="Planning response...",
                )
                await self._stream_text_to_ui(
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
                            controller.state["messages"][assistant_index]["content"][1][
                                "text"
                            ] += token
                            model_text_streamed = True
                        return

                    tool_name = str(event.get("tool_name") or "tool")
                    tool_call_id = str(
                        event.get("tool_call_id") or f"tool_{uuid.uuid4().hex}"
                    )

                    if phase == "start":
                        args_text = str(event.get("args_text") or "{}")
                        part_index = len(
                            controller.state["messages"][assistant_index]["content"]
                        )
                        controller.state["messages"][assistant_index]["content"].append(
                            {
                                "type": "tool-call",
                                "toolCallId": tool_call_id,
                                "toolName": tool_name,
                                "argsText": args_text,
                                "args": {},
                            }
                        )
                        tool_part_index_by_call[tool_call_id] = part_index
                        self._append_tool_update(
                            controller,
                            stage="sandbox",
                            status="running",
                            detail=f"Waiting for claim/runtime for {tool_name}",
                            tool=tool_name,
                        )
                        await self._stream_text_to_ui(
                            controller,
                            assistant_index=assistant_index,
                            part_index=0,
                            text=f"Waiting for sandbox claim/runtime: {tool_name}\n",
                            delay_seconds=0.01,
                        )
                        return

                    if phase != "end":
                        return

                    part_index = tool_part_index_by_call.get(tool_call_id)
                    if part_index is not None:
                        part = controller.state["messages"][assistant_index]["content"][
                            part_index
                        ]
                        part["args"] = (
                            event.get("args")
                            if isinstance(event.get("args"), dict)
                            else {}
                        )
                        part["result"] = event.get("result")
                        if bool(event.get("is_error")):
                            part["isError"] = True

                    for asset in event.get("stored_assets", []) or []:
                        if str(asset.get("mime_type", "")).startswith("image/"):
                            controller.state["messages"][assistant_index][
                                "content"
                            ].append({"type": "image", "image": asset["view_url"]})

                    result = event.get("result")
                    claim_name = ""
                    if isinstance(result, dict):
                        claim_name = str(result.get("claim_name") or "")

                    if claim_name:
                        self._append_tool_update(
                            controller,
                            stage="sandbox",
                            status="completed",
                            detail=f"Claim ready: {claim_name}",
                            tool=tool_name,
                        )
                        await self._stream_text_to_ui(
                            controller,
                            assistant_index=assistant_index,
                            part_index=0,
                            text=f"Claim ready: {claim_name}\n",
                            delay_seconds=0.01,
                        )

                previous_listener = self._tool_event_listener
                self._tool_event_listener = _live_tool_listener
                try:
                    graph_result = await self._run_agent_graph_async(
                        session.messages, session.session_id
                    )
                finally:
                    self._tool_event_listener = previous_listener
                session.messages = graph_result["messages"]
                tool_events = graph_result.get("tool_events", [])
                session.tool_calls += len(tool_events)

                if tool_events:
                    await self._stream_text_to_ui(
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

                    tool_part_index = len(
                        controller.state["messages"][assistant_index]["content"]
                    )
                    controller.state["messages"][assistant_index]["content"].append(
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

                    for asset in event.get("stored_assets", []) or []:
                        if str(asset.get("mime_type", "")).startswith("image/"):
                            controller.state["messages"][assistant_index][
                                "content"
                            ].append({"type": "image", "image": asset["view_url"]})

                    self._append_tool_update(
                        controller,
                        stage="tool",
                        status="completed" if not is_error else "error",
                        detail=f"Finished {tool_name}",
                        tool=tool_name,
                    )
                    await self._stream_text_to_ui(
                        controller,
                        assistant_index=assistant_index,
                        part_index=0,
                        text=f"Finished tool: {tool_name}\n",
                        delay_seconds=0.01,
                    )

                final_text = graph_result.get("final_reply") or ""
                if graph_result.get("limit_reached") and not final_text:
                    final_text = "I hit the tool-calling safety limit for this turn."

                await self._stream_text_to_ui(
                    controller,
                    assistant_index=assistant_index,
                    part_index=0,
                    text="Generating final response...\n",
                    delay_seconds=0.001,
                )
                if not model_text_streamed:
                    await self._stream_text_to_ui(
                        controller,
                        assistant_index=assistant_index,
                        part_index=1,
                        text=final_text,
                        delay_seconds=0.001,
                    )

                controller.state["messages"][assistant_index]["status"] = {
                    "type": "complete"
                }
                self._append_tool_update(
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

                session.updated_at = _now_iso()
                self._sync_session_ui_from_controller(session, controller)
                if assistant_index is not None and 0 <= assistant_index < len(
                    session.ui_messages
                ):
                    assistant_message = session.ui_messages[assistant_index]
                    if isinstance(assistant_message, dict):
                        self._ensure_tool_parts_persisted(
                            assistant_message, tool_events
                        )
                self._normalize_session_ui_messages(session)
                await self._persist_session_async(session)
            except Exception as exc:
                error_text = str(exc)
                session.last_error = error_text
                if assistant_index is None:
                    assistant_ui_message = self._new_assistant_ui_message()
                    assistant_index = len(session.ui_messages)
                    controller.state["messages"].append(assistant_ui_message)
                    session.ui_messages.append(assistant_ui_message)
                self._append_tool_update(
                    controller,
                    stage="model",
                    status="error",
                    detail="Agent failed while processing the request",
                )
                controller.state["messages"][assistant_index]["content"][0]["text"] += (
                    "Encountered an error while processing.\n"
                )
                controller.state["messages"][assistant_index]["content"][1]["text"] += (
                    "I hit an internal error while processing this message. "
                    "Please verify your OPENAI_API_KEY and try again.\n\n"
                    f"Error: {error_text}"
                )
                controller.state["messages"][assistant_index]["status"] = {
                    "type": "complete"
                }
                self._sync_session_ui_from_controller(session, controller)
                self._normalize_session_ui_messages(session)
                await self._persist_session_async(session)

    def get_state_summary(self) -> dict[str, Any]:
        """Provide aggregate state information for diagnostics endpoints."""
        return {
            "session_count": len(self.sessions),
            "sessions": [
                {
                    "session_id": s.session_id,
                    "created_at": s.created_at,
                    "updated_at": s.updated_at,
                    "title": s.title,
                    "message_count": len(s.messages),
                    "ui_message_count": len(s.ui_messages),
                    "tool_calls": s.tool_calls,
                    "last_error": s.last_error,
                    "share_id": s.share_id,
                }
                for s in self.sessions.values()
            ],
            "sandbox": {
                "mode": self.sandbox_manager.mode,
                "api_url": self.sandbox_manager.api_url,
                "template_name": self.sandbox_manager.template_name,
                "namespace": self.sandbox_manager.namespace,
                "execution_model": self.sandbox_lifecycle.execution_model,
            },
            "runtime_config": self.get_runtime_config(),
        }

    def reset_session(self, session_id: str) -> bool:
        """Reset a session and release any scope-bound sandbox lease."""
        if session_id not in self.sessions:
            return False
        self.sandbox_lifecycle.release_scope("session", session_id)
        del self.sessions[session_id]
        self.session_store.delete_session(session_id)
        return True

    def list_sandboxes(self) -> list[dict[str, Any]]:
        """Return active sandbox leases for lifecycle inspection APIs."""
        return self.sandbox_lifecycle.list_sandboxes()

    def get_sandbox(self, lease_id: str) -> dict[str, Any] | None:
        """Fetch one sandbox lease by id."""
        return self.sandbox_lifecycle.get_sandbox(lease_id)

    def release_sandbox(self, lease_id: str) -> bool:
        """Release an active sandbox lease by id."""
        return self.sandbox_lifecycle.release_sandbox(lease_id)

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions = sorted(
            self.sessions.values(), key=lambda session: session.updated_at, reverse=True
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

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        session = self.sessions.get(session_id)
        if not session:
            return None
        self._normalize_session_ui_messages(session)
        return {
            "session_id": session.session_id,
            "title": session.title,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "share_id": session.share_id,
            "messages": session.ui_messages,
            "sandbox": self.get_session_sandbox(session_id),
        }

    def get_session_sandbox(self, session_id: str) -> dict[str, Any]:
        lease = self.sandbox_lifecycle.get_active_scope_lease("session", session_id)
        if not lease:
            return {
                "has_active_lease": False,
                "has_active_claim": False,
                "lease_id": None,
                "claim_name": None,
                "status": None,
                "template_name": None,
                "namespace": None,
                "created_at": None,
                "last_used_at": None,
                "expires_at": None,
            }

        claim_name = lease.get("claim_name")
        return {
            "has_active_lease": True,
            "has_active_claim": bool(claim_name),
            "lease_id": lease.get("lease_id"),
            "claim_name": claim_name,
            "status": lease.get("status"),
            "template_name": lease.get("template_name"),
            "namespace": lease.get("namespace"),
            "created_at": lease.get("created_at"),
            "last_used_at": lease.get("last_used_at"),
            "expires_at": lease.get("expires_at"),
        }

    def create_share(self, session_id: str) -> str | None:
        session = self.sessions.get(session_id)
        if not session:
            return None
        if not session.share_id:
            session.share_id = uuid.uuid4().hex
            self.session_store.set_share_id(session_id, session.share_id)
            self._persist_session(session)
        return session.share_id

    def get_shared_session(self, share_id: str) -> dict[str, Any] | None:
        for session in self.sessions.values():
            if session.share_id == share_id:
                return self.get_session(session.session_id)

        record = self.session_store.get_by_share_id(share_id)
        if not record:
            return None
        session_id = record["session_id"]
        if session_id not in self.sessions:
            self.sessions[session_id] = SessionState(
                session_id=record["session_id"],
                created_at=record["created_at"],
                updated_at=record["updated_at"],
                title=record.get("title") or "New chat",
                messages=record["messages"],
                ui_messages=record["ui_messages"],
                tool_calls=record["tool_calls"],
                last_error=record["last_error"],
                share_id=record.get("share_id"),
            )
        return self.get_session(session_id)

    def get_shared_session_markdown(self, share_id: str) -> str | None:
        session = self.get_shared_session(share_id)
        if not session:
            return None

        lines: list[str] = [f"# {session.get('title') or 'Shared Thread'}", ""]
        for message in session.get("messages", []):
            role = message.get("role", "assistant")
            header = "## Assistant" if role == "assistant" else "## User"
            lines.append(header)
            lines.append("")

            for part in message.get("content", []):
                part_type = part.get("type")
                if part_type == "text":
                    lines.append(part.get("text", ""))
                    lines.append("")
                elif part_type == "reasoning":
                    lines.append("> Thinking")
                    lines.append("")
                    lines.append(part.get("text", ""))
                    lines.append("")
                elif part_type == "image":
                    image = part.get("image", "")
                    if image:
                        lines.append(f"![uploaded-image]({image})")
                        lines.append("")
                elif part_type == "tool-call":
                    lines.append(f"### Tool: {part.get('toolName', 'tool')}")
                    lines.append("")
                    args_text = part.get("argsText") or json.dumps(
                        part.get("args", {}), ensure_ascii=True, indent=2
                    )
                    result_payload = part.get("result", "(pending)")
                    result_text = json.dumps(
                        result_payload, ensure_ascii=True, indent=2
                    )
                    lines.extend(
                        [
                            "```json",
                            args_text,
                            "```",
                            "",
                            "```json",
                            result_text,
                            "```",
                            "",
                        ]
                    )

                    assets = []
                    if isinstance(result_payload, dict):
                        maybe_assets = result_payload.get("assets")
                        if isinstance(maybe_assets, list):
                            assets = [a for a in maybe_assets if isinstance(a, dict)]

                    if assets:
                        lines.append("#### Tool assets")
                        lines.append("")
                        for asset in assets:
                            filename = str(asset.get("filename") or "asset")
                            view_url = str(asset.get("view_url") or "")
                            download_url = str(asset.get("download_url") or view_url)
                            mime_type = str(asset.get("mime_type") or "")

                            if view_url and mime_type.startswith("image/"):
                                lines.append(f"![{filename}]({view_url})")
                            if download_url:
                                lines.append(f"- [{filename}]({download_url})")
                            elif view_url:
                                lines.append(f"- [{filename}]({view_url})")
                        lines.append("")

            lines.extend(["---", ""])

        return "\n".join(lines).strip() + "\n"
