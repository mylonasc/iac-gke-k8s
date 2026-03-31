import asyncio
import copy
import inspect
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from assistant_stream import RunController
from openai import AsyncOpenAI

from .agents.factory import AgentFactory
from .agents.integrations.assets import AssetFacade
from .agents.integrations.sandbox_leases import SandboxLeaseFacade
from .agents.integrations.sandbox_sessions import SessionSandboxFacade
from .agents.prompts import SYSTEM_PROMPT
from .agents.runtime import AgentRuntime
from .agents.session_ui import SessionUIHelper
from .agents.state import AgentGraphState
from .agents.transport import AssistantTransportRuntime
from .agents.tool_events import model_token_event
from .asset_manager import AssetManager
from .sandbox_lifecycle import SandboxLifecycleService
from .sandbox_manager import SandboxManager
from .session_store import SessionStore


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public_asset_url(share_id: str, asset_id: str, *, download: bool = False) -> str:
    base = f"/api/public/{share_id}/assets/{asset_id}"
    if download:
        return f"{base}/download"
    return base


class SandboxedReactAgent:
    """Main orchestration layer for model calls, tools, and session state."""

    def __init__(self) -> None:
        self.default_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.default_max_tool_calls_per_turn = int(
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
        self.asset_facade = AssetFacade(self.asset_manager)
        self.sandbox_lease_facade = SandboxLeaseFacade(self.sandbox_lifecycle)
        self.session_sandbox_facade = SessionSandboxFacade(
            self.sandbox_lease_facade,
            self.asset_facade,
        )
        self.default_sandbox_config = self.sandbox_manager.get_config()
        self.default_sandbox_config.update(self.sandbox_lifecycle.get_config())
        self.sessions: dict[str, SessionState] = {}
        self._tool_event_listener: Any = None
        self._session_ui = SessionUIHelper(now_iso=_now_iso)
        self._agent_runtime = AgentRuntime(
            build_sandbox_toolkit=self._build_sandbox_toolkit,
            notify_tool_event=self._notify_tool_event,
            get_create_completion=lambda: self._create_completion_async,
            get_create_completion_streaming=lambda: (
                self._create_completion_streaming_async
            ),
            tool_error_output=self._tool_error_output,
        )
        self._assistant_transport = AssistantTransportRuntime(
            get_or_create_session=self.get_or_create_session,
            runtime_context_for_user=self._runtime_context_for_user,
            normalize_user_parts=self._session_ui.normalize_user_parts,
            new_user_ui_message=self._session_ui.new_user_ui_message,
            new_assistant_ui_message=self._session_ui.new_assistant_ui_message,
            sanitize_messages=self._sanitize_messages,
            title_from_text=self._title_from_text,
            append_tool_update=self._session_ui.append_tool_update,
            stream_text_to_ui=self._session_ui.stream_text_to_ui,
            run_agent_graph_async=self._run_agent_graph_async,
            sync_session_ui_from_controller=self._session_ui.sync_session_ui_from_controller,
            ensure_tool_parts_persisted=self._session_ui.ensure_tool_parts_persisted,
            normalize_session_ui_messages=self._session_ui.normalize_session_ui_messages,
            persist_session_async=self._persist_session_async,
            now_iso=_now_iso,
            get_tool_event_listener=lambda: self._tool_event_listener,
            set_tool_event_listener=lambda listener: setattr(
                self, "_tool_event_listener", listener
            ),
        )
        self._agent_factory = AgentFactory(
            model_node=self._agent_runtime.graph_model_node,
            tools_node=self._agent_runtime.graph_tools_node,
            route_after_model=self._agent_runtime.route_after_model,
            route_after_tools=self._agent_runtime.route_after_tools,
        )
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
            "user_id": session.user_id,
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
            self._session_ui.normalize_session_ui_messages(
                self.sessions[record["session_id"]]
            )

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

    def _default_runtime_config_record(self) -> dict[str, Any]:
        return {
            "model": self.default_model,
            "max_tool_calls_per_turn": self.default_max_tool_calls_per_turn,
            "sandbox_mode": self.default_sandbox_config.get("mode", "cluster"),
            "sandbox_api_url": self.default_sandbox_config.get("api_url", ""),
            "sandbox_template_name": self.default_sandbox_config.get(
                "template_name", "python-runtime-template-small"
            ),
            "sandbox_namespace": self.default_sandbox_config.get(
                "namespace", "alt-default"
            ),
            "sandbox_server_port": int(
                self.default_sandbox_config.get("server_port", 8888)
            ),
            "sandbox_max_output_chars": int(
                self.default_sandbox_config.get("max_output_chars", 6000)
            ),
            "sandbox_local_timeout_seconds": int(
                self.default_sandbox_config.get("local_timeout_seconds", 20)
            ),
            "sandbox_execution_model": self.default_sandbox_config.get(
                "execution_model", "session"
            ),
            "sandbox_session_idle_ttl_seconds": int(
                self.default_sandbox_config.get("session_idle_ttl_seconds", 1800)
            ),
        }

    def _build_sandbox_toolkit(self, session_id: str, runtime_config: dict[str, Any]):
        return self._agent_factory.build_sandbox_toolkit(
            session_sandbox=self.session_sandbox_facade,
            session_id=session_id,
            runtime_config=runtime_config.get("sandbox") or {},
            now_iso=_now_iso,
            event_sink=self._notify_tool_event,
        )

    def _ensure_user_profile(self, user_id: str) -> dict[str, Any]:
        return self.session_store.ensure_user(user_id)

    def get_user_profile(self, user_id: str) -> dict[str, Any]:
        """Return a persisted user profile, creating it on first access."""
        return self._ensure_user_profile(user_id)

    def _resolve_user_runtime_record(self, user_id: str) -> dict[str, Any]:
        defaults = self._default_runtime_config_record()
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return defaults
        self._ensure_user_profile(normalized_user_id)
        stored = self.session_store.get_user_config(normalized_user_id)
        if not stored:
            return defaults
        merged = dict(defaults)
        merged.update(
            {
                key: stored[key]
                for key in defaults.keys()
                if key in stored and stored[key] is not None
            }
        )
        return merged

    def _runtime_context_for_user(self, user_id: str) -> dict[str, Any]:
        record = self._resolve_user_runtime_record(user_id)
        sandbox = {
            "mode": record["sandbox_mode"],
            "api_url": record["sandbox_api_url"],
            "template_name": record["sandbox_template_name"],
            "namespace": record["sandbox_namespace"],
            "server_port": int(record["sandbox_server_port"]),
            "max_output_chars": int(record["sandbox_max_output_chars"]),
            "local_timeout_seconds": int(record["sandbox_local_timeout_seconds"]),
            "execution_model": record["sandbox_execution_model"],
            "session_idle_ttl_seconds": int(record["sandbox_session_idle_ttl_seconds"]),
            "sandbox_ready_timeout": int(
                self.default_sandbox_config.get("sandbox_ready_timeout", 420)
            ),
            "gateway_ready_timeout": int(
                self.default_sandbox_config.get("gateway_ready_timeout", 180)
            ),
            "max_lease_ttl_seconds": int(
                self.default_sandbox_config.get("max_lease_ttl_seconds", 21600)
            ),
        }
        return {
            "model": record["model"],
            "max_tool_calls_per_turn": int(record["max_tool_calls_per_turn"]),
            "sandbox": sandbox,
        }

    def _default_runtime_context(self) -> dict[str, Any]:
        """Return baseline runtime context before user-specific overrides."""
        defaults = self._default_runtime_config_record()
        return {
            "model": defaults["model"],
            "max_tool_calls_per_turn": int(defaults["max_tool_calls_per_turn"]),
            "sandbox": {
                "mode": defaults["sandbox_mode"],
                "api_url": defaults["sandbox_api_url"],
                "template_name": defaults["sandbox_template_name"],
                "namespace": defaults["sandbox_namespace"],
                "server_port": int(defaults["sandbox_server_port"]),
                "max_output_chars": int(defaults["sandbox_max_output_chars"]),
                "local_timeout_seconds": int(defaults["sandbox_local_timeout_seconds"]),
                "execution_model": defaults["sandbox_execution_model"],
                "session_idle_ttl_seconds": int(
                    defaults["sandbox_session_idle_ttl_seconds"]
                ),
                "sandbox_ready_timeout": int(
                    self.default_sandbox_config.get("sandbox_ready_timeout", 420)
                ),
                "gateway_ready_timeout": int(
                    self.default_sandbox_config.get("gateway_ready_timeout", 180)
                ),
                "max_lease_ttl_seconds": int(
                    self.default_sandbox_config.get("max_lease_ttl_seconds", 21600)
                ),
            },
        }

    def get_runtime_config(self, user_id: str) -> dict[str, Any]:
        """Return effective model and sandbox runtime configuration for one user."""
        return self._runtime_context_for_user(user_id)

    def _release_user_session_leases(self, user_id: str) -> None:
        for session in self.sessions.values():
            if session.user_id != user_id:
                continue
            self.sandbox_lease_facade.release_session(session.session_id)

    def update_runtime_config(
        self,
        user_id: str,
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
        current = self._resolve_user_runtime_record(user_id)
        updated = dict(current)

        if model is not None:
            updated["model"] = model
        if max_tool_calls_per_turn is not None:
            if max_tool_calls_per_turn < 1:
                raise ValueError("max_tool_calls_per_turn must be >= 1")
            updated["max_tool_calls_per_turn"] = max_tool_calls_per_turn

        if sandbox_mode is not None:
            normalized_mode = sandbox_mode.strip().lower()
            if normalized_mode not in {"cluster", "local"}:
                raise ValueError("sandbox_mode must be 'cluster' or 'local'")
            updated["sandbox_mode"] = normalized_mode
        if sandbox_api_url is not None:
            updated["sandbox_api_url"] = sandbox_api_url
        if sandbox_template_name is not None:
            updated["sandbox_template_name"] = sandbox_template_name
        if sandbox_namespace is not None:
            updated["sandbox_namespace"] = sandbox_namespace
        if sandbox_server_port is not None:
            if sandbox_server_port <= 0:
                raise ValueError("sandbox_server_port must be > 0")
            updated["sandbox_server_port"] = sandbox_server_port
        if sandbox_max_output_chars is not None:
            if sandbox_max_output_chars < 100:
                raise ValueError("sandbox_max_output_chars must be >= 100")
            updated["sandbox_max_output_chars"] = sandbox_max_output_chars
        if sandbox_local_timeout_seconds is not None:
            if sandbox_local_timeout_seconds <= 0:
                raise ValueError("sandbox_local_timeout_seconds must be > 0")
            updated["sandbox_local_timeout_seconds"] = sandbox_local_timeout_seconds
        if sandbox_execution_model is not None:
            normalized_model = sandbox_execution_model.strip().lower()
            if normalized_model not in {"ephemeral", "session"}:
                raise ValueError(
                    "sandbox_execution_model must be 'ephemeral' or 'session'"
                )
            updated["sandbox_execution_model"] = normalized_model
        if sandbox_session_idle_ttl_seconds is not None:
            if sandbox_session_idle_ttl_seconds <= 0:
                raise ValueError("sandbox_session_idle_ttl_seconds must be > 0")
            updated["sandbox_session_idle_ttl_seconds"] = (
                sandbox_session_idle_ttl_seconds
            )

        self.session_store.upsert_user_config(user_id, updated)

        recycle_fields = {
            "sandbox_mode",
            "sandbox_api_url",
            "sandbox_template_name",
            "sandbox_namespace",
            "sandbox_server_port",
            "sandbox_execution_model",
        }
        should_recycle = any(updated[key] != current[key] for key in recycle_fields)
        if should_recycle:
            self._release_user_session_leases(user_id)

        return self.get_runtime_config(user_id)

    def create_session(
        self, title: str | None = None, user_id: str = ""
    ) -> SessionState:
        if user_id:
            self._ensure_user_profile(user_id)
        session_id = str(uuid.uuid4())
        now = _now_iso()
        state = SessionState(
            session_id=session_id,
            user_id=user_id,
            created_at=now,
            updated_at=now,
            title=title or "New chat",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}],
        )
        self.sessions[session_id] = state
        self._persist_session(state)
        return state

    def get_or_create_session(
        self, session_id: str | None, user_id: str
    ) -> SessionState:
        if user_id:
            self._ensure_user_profile(user_id)
        if session_id and session_id in self.sessions:
            existing = self.sessions[session_id]
            if existing.user_id != user_id:
                raise PermissionError("Session not found")
            return existing
        return self.create_session(user_id=user_id)

    def _run_tool(
        self,
        *,
        session_id: str,
        tool_call_id: str | None,
        name: str,
        arguments_json: str,
        runtime_config: dict[str, Any],
    ) -> tuple[str, list[dict[str, Any]]]:
        """Execute a tool call through the session-scoped sandbox toolkit."""
        toolkit = self._build_sandbox_toolkit(session_id, runtime_config)
        return asyncio.run(
            toolkit.run_tool_call(
                tool_call_id=tool_call_id,
                name=name,
                arguments_json=arguments_json,
            )
        )

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
        runtime_config: dict[str, Any],
    ) -> tuple[str, list[dict[str, Any]]]:
        return await asyncio.to_thread(
            self._run_tool,
            session_id=session_id,
            tool_call_id=tool_call_id,
            name=name,
            arguments_json=arguments_json,
            runtime_config=runtime_config,
        )

    async def _persist_session_async(self, session: SessionState) -> None:
        await asyncio.to_thread(self._persist_session, session)

    async def _create_completion_async(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]]
    ) -> Any:
        return await self.async_client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.2,
        )

    async def _create_completion_streaming_async(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        stream = await self.async_client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
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
                await self._notify_tool_event(model_token_event(delta_text))

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

    def _build_agent_graph(self):
        graph = self._agent_factory.build_graph()
        self._agent_runtime.set_graph(graph)
        return graph

    async def _run_agent_graph_async(
        self,
        messages: list[dict[str, Any]],
        session_id: str,
        runtime_config: dict[str, Any],
    ) -> AgentGraphState:
        return await self._agent_runtime.run_graph_async(
            messages=messages,
            session_id=session_id,
            runtime_config=runtime_config,
        )

    def chat(
        self, user_message: str, session_id: str | None = None, user_id: str = ""
    ) -> dict[str, Any]:
        runtime_config = self._runtime_context_for_user(user_id)
        state = self.get_or_create_session(session_id, user_id)
        state.messages = self._sanitize_messages(state.messages)
        state.updated_at = _now_iso()
        state.messages.append({"role": "user", "content": user_message})
        if state.title == "New chat":
            state.title = self._title_from_text(user_message)
        try:
            result = asyncio.run(
                self._run_agent_graph_async(
                    state.messages,
                    state.session_id,
                    runtime_config,
                )
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
        self, payload: Any, controller: RunController, user_id: str
    ) -> None:
        await self._assistant_transport.run(payload, controller, user_id)

    def get_state_summary(self, user_id: str | None = None) -> dict[str, Any]:
        """Provide aggregate state information for diagnostics endpoints."""
        sessions = list(self.sessions.values())
        if user_id is not None:
            sessions = [session for session in sessions if session.user_id == user_id]
        runtime_config = (
            self.get_runtime_config(user_id)
            if user_id
            else self._default_runtime_context()
        )
        return {
            "session_count": len(sessions),
            "sessions": [
                {
                    "session_id": s.session_id,
                    "user_id": s.user_id,
                    "created_at": s.created_at,
                    "updated_at": s.updated_at,
                    "title": s.title,
                    "message_count": len(s.messages),
                    "ui_message_count": len(s.ui_messages),
                    "tool_calls": s.tool_calls,
                    "last_error": s.last_error,
                    "share_id": s.share_id,
                }
                for s in sessions
            ],
            "sandbox": {
                "mode": self.sandbox_manager.mode,
                "api_url": self.sandbox_manager.api_url,
                "template_name": self.sandbox_manager.template_name,
                "namespace": self.sandbox_manager.namespace,
                "execution_model": self.sandbox_lifecycle.execution_model,
            },
            "runtime_config": runtime_config,
        }

    def reset_session(self, session_id: str, user_id: str) -> bool:
        """Reset a session and release any scope-bound sandbox lease."""
        if session_id not in self.sessions:
            return False
        if self.sessions[session_id].user_id != user_id:
            return False
        self.sandbox_lease_facade.release_session(session_id)
        del self.sessions[session_id]
        self.session_store.delete_session_for_user(session_id, user_id)
        return True

    def list_sandboxes(self) -> list[dict[str, Any]]:
        """Return active sandbox leases for lifecycle inspection APIs."""
        return self.sandbox_lease_facade.list_active_leases()

    def get_sandbox(self, lease_id: str) -> dict[str, Any] | None:
        """Fetch one sandbox lease by id."""
        return self.sandbox_lease_facade.get_lease(lease_id)

    def release_sandbox(self, lease_id: str) -> bool:
        """Release an active sandbox lease by id."""
        return self.sandbox_lease_facade.release_lease(lease_id)

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

    def get_session(self, session_id: str, user_id: str) -> dict[str, Any] | None:
        session = self.sessions.get(session_id)
        if not session:
            return None
        if session.user_id != user_id:
            return None
        self._session_ui.normalize_session_ui_messages(session)
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
        lease = self.sandbox_lease_facade.get_session_lease(session_id)
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

    def create_share(self, session_id: str, user_id: str) -> str | None:
        session = self.sessions.get(session_id)
        if not session:
            return None
        if session.user_id != user_id:
            return None
        if not session.share_id:
            session.share_id = uuid.uuid4().hex
            self.session_store.set_share_id_for_user(
                session_id, user_id, session.share_id
            )
            self._persist_session(session)
        return session.share_id

    def _publicize_shared_session(
        self, session: dict[str, Any], share_id: str
    ) -> dict[str, Any]:
        rewritten = copy.deepcopy(session)
        for message in rewritten.get("messages", []):
            if not isinstance(message, dict):
                continue
            for part in message.get("content", []):
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "image":
                    image_url = str(part.get("image") or "")
                    match = re.fullmatch(r"/api/assets/([A-Za-z0-9_-]+)", image_url)
                    if match:
                        part["image"] = _public_asset_url(share_id, match.group(1))
                if part.get("type") == "tool-call":
                    result = part.get("result")
                    if not isinstance(result, dict):
                        continue
                    assets = result.get("assets")
                    if not isinstance(assets, list):
                        continue
                    for asset in assets:
                        if not isinstance(asset, dict):
                            continue
                        asset_id = str(asset.get("asset_id") or "")
                        if not asset_id:
                            continue
                        asset["view_url"] = _public_asset_url(share_id, asset_id)
                        asset["download_url"] = _public_asset_url(
                            share_id, asset_id, download=True
                        )
        return rewritten

    def get_shared_session(self, share_id: str) -> dict[str, Any] | None:
        for session in self.sessions.values():
            if session.share_id == share_id:
                private_session = self.get_session(session.session_id, session.user_id)
                if not private_session:
                    return None
                return self._publicize_shared_session(private_session, share_id)

        record = self.session_store.get_by_share_id(share_id)
        if not record:
            return None
        session_id = record["session_id"]
        if session_id not in self.sessions:
            self.sessions[session_id] = SessionState(
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
        private_session = self.get_session(
            session_id, self.sessions[session_id].user_id
        )
        if not private_session:
            return None
        return self._publicize_shared_session(private_session, share_id)

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
