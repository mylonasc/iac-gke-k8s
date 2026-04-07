import asyncio
import inspect
import json
import os
from typing import Any

from assistant_stream import RunController
from openai import AsyncOpenAI

from .agents.factory import AgentFactory
from .agents.integrations.assets import AssetFacade
from .agents.integrations.sandbox_leases import SandboxLeaseFacade
from .agents.integrations.sandbox_sessions import SessionSandboxFacade
from .agents.runtime import AgentRuntime
from .agents.session_ui import SessionUIHelper
from .agents.state import AgentGraphState
from .agents.tool_events import model_token_event
from .agents.toolkits.base import ToolkitProvider
from .agents.toolkits.highcharts import HighchartsToolkitProvider
from .agents.toolkits.sandbox import SandboxToolkitProvider
from .agents.transport import AssistantTransportRuntime
from .agents.ui_state_adapter import AssistantUIStateAdapter
from .asset_manager import AssetManager
from .frontend_libs import FrontendLibraryCache
from .repositories.asset_repository import AssetRepository
from .repositories.sandbox_lease_repository import SandboxLeaseRepository
from .repositories.session_repository import SessionRepository
from .repositories.user_config_repository import UserConfigRepository
from .repositories.user_repository import UserRepository
from .repositories.user_workspace_repository import UserWorkspaceRepository
from .sandbox_lifecycle import SandboxLifecycleService
from .sandbox_manager import SandboxManager
from .services.runtime_config_service import RuntimeConfigService
from .services.sandbox_admin_service import SandboxAdminService
from .services.session_service import SessionService
from .services.session_state import SessionState, now_iso
from .services.sharing_service import SharingService
from .services.workspace_async_service import WorkspaceAsyncService
from .services.workspace_admin_clients import (
    DisabledGoogleWorkspaceAdminClient,
    DisabledKubernetesWorkspaceAdminClient,
    GoogleApiWorkspaceAdminClient,
    KubernetesApiWorkspaceAdminClient,
)
from .services.workspace_models import WorkspaceInfraConfig
from .services.workspace_provisioning_service import WorkspaceProvisioningService
from .services.workspace_service import WorkspaceService
from .session_store import SessionStore


class SandboxedReactAgent:
    """Application facade that composes runtime, services, and toolkit providers."""

    def __init__(self) -> None:
        self.default_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.default_max_tool_calls_per_turn = int(
            os.getenv("AGENT_MAX_TOOL_CALLS_PER_TURN", "4")
        )
        self.async_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.frontend_library_cache = FrontendLibraryCache()
        self.sandbox_manager = SandboxManager()
        self.session_store = SessionStore()
        self.user_repository = UserRepository(self.session_store)
        self.user_config_repository = UserConfigRepository(self.session_store)
        self.user_workspace_repository = UserWorkspaceRepository(self.session_store)
        self.session_repository = SessionRepository(self.session_store)
        self.asset_repository = AssetRepository(self.session_store)
        self.sandbox_lease_repository = SandboxLeaseRepository(self.session_store)
        self.sandbox_lifecycle = SandboxLifecycleService(
            sandbox_manager=self.sandbox_manager,
            sandbox_lease_repository=self.sandbox_lease_repository,
            get_user_id_for_session=lambda session_id: (
                self.sessions.get(session_id).user_id
                if self.sessions.get(session_id)
                else None
            ),
            get_workspace_for_user=lambda user_id: self.get_workspace(user_id),
            ensure_workspace_async_for_user=lambda user_id: self.ensure_workspace_async(
                user_id
            ),
            bind_workspace_claim_for_session=lambda session_id, claim_name, namespace: (
                self._bind_workspace_claim_for_session(
                    session_id,
                    claim_name=claim_name,
                    namespace=namespace,
                )
            ),
        )
        self.asset_manager = AssetManager(self.asset_repository)
        self.asset_facade = AssetFacade(self.asset_manager)
        self.sandbox_lease_facade = SandboxLeaseFacade(self.sandbox_lifecycle)
        self.session_sandbox_facade = SessionSandboxFacade(
            self.sandbox_lease_facade,
            self.asset_facade,
        )
        self.toolkit_providers: list[ToolkitProvider] = [
            SandboxToolkitProvider(
                self.session_sandbox_facade,
                self.sandbox_manager,
                self.sandbox_lifecycle,
            ),
            HighchartsToolkitProvider(
                self.asset_manager,
                self.frontend_library_cache,
            ),
        ]
        self._tool_event_listener: Any = None
        self._session_ui = SessionUIHelper(now_iso=now_iso)
        self._sandbox_admin = SandboxAdminService(
            sandbox_lease_facade=self.sandbox_lease_facade,
            sandbox_manager=self.sandbox_manager,
            sandbox_lifecycle=self.sandbox_lifecycle,
        )
        self._session_service = SessionService(
            session_repository=self.session_repository,
            user_repository=self.user_repository,
            session_ui=self._session_ui,
            release_session_leases=self.sandbox_lease_facade.release_session,
            get_session_sandbox=self._sandbox_admin.get_session_sandbox,
        )
        self.sessions = self._session_service.sessions
        self._runtime_config_service = RuntimeConfigService(
            user_repository=self.user_repository,
            user_config_repository=self.user_config_repository,
            toolkit_providers=self.toolkit_providers,
            release_user_session_leases=self._release_user_session_leases,
            default_model=self.default_model,
            default_max_tool_calls_per_turn=self.default_max_tool_calls_per_turn,
        )
        self._sharing_service = SharingService(
            session_repository=self.session_repository,
            session_service=self._session_service,
            get_session=self.get_session,
        )
        infra_config = WorkspaceInfraConfig(
            project_id=os.getenv("GCP_PROJECT_ID", ""),
            bucket_prefix=os.getenv("SANDBOX_WORKSPACE_BUCKET_PREFIX", ""),
            namespace=os.getenv("SANDBOX_NAMESPACE", self.sandbox_manager.namespace),
            base_template_name=os.getenv(
                "SANDBOX_WORKSPACE_BASE_TEMPLATE_NAME",
                self.sandbox_manager.template_name,
            ),
        )
        provisioning_enabled = self._workspace_provisioning_enabled(infra_config)
        self._workspace_provisioning_service = WorkspaceProvisioningService(
            user_repository=self.user_repository,
            user_workspace_repository=self.user_workspace_repository,
            google_admin_client=(
                GoogleApiWorkspaceAdminClient(project_id=infra_config.project_id)
                if provisioning_enabled
                else DisabledGoogleWorkspaceAdminClient()
            ),
            kubernetes_admin_client=(
                KubernetesApiWorkspaceAdminClient(namespace=infra_config.namespace)
                if provisioning_enabled
                else DisabledKubernetesWorkspaceAdminClient()
            ),
            infra_config=infra_config,
        )
        self._workspace_async_service = WorkspaceAsyncService(
            workspace_provisioning_service=self._workspace_provisioning_service,
            max_workers=int(os.getenv("WORKSPACE_PROVISIONER_MAX_WORKERS", "4")),
        )
        self._workspace_service = WorkspaceService(
            workspace_provisioning_service=self._workspace_provisioning_service,
            user_workspace_repository=self.user_workspace_repository,
            workspace_async_service=self._workspace_async_service,
        )
        self._ui_state = AssistantUIStateAdapter()
        self._agent_runtime = AgentRuntime(
            build_tool_runtime=self._build_tool_runtime,
            notify_tool_event=self._notify_tool_event,
            should_stream_model=self._should_stream_model,
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
            sanitize_messages=self._session_service.sanitize_messages,
            title_from_text=self._session_service.title_from_text,
            append_tool_update=self._session_ui.append_tool_update,
            stream_text_to_ui=self._session_ui.stream_text_to_ui,
            run_agent_graph_async=self._run_agent_graph_async,
            sync_session_ui_from_controller=self._session_ui.sync_session_ui_from_controller,
            ensure_tool_parts_persisted=self._session_ui.ensure_tool_parts_persisted,
            normalize_session_ui_messages=self._session_ui.normalize_session_ui_messages,
            persist_session_async=self._session_service.persist_session_async,
            now_iso=now_iso,
            get_tool_event_listener=lambda: self._tool_event_listener,
            set_tool_event_listener=lambda listener: setattr(
                self, "_tool_event_listener", listener
            ),
            ui_state=self._ui_state,
        )
        self._agent_factory = AgentFactory(
            model_node=self._agent_runtime.graph_model_node,
            tools_node=self._agent_runtime.graph_tools_node,
            route_after_model=self._agent_runtime.route_after_model,
            route_after_tools=self._agent_runtime.route_after_tools,
        )
        self._agent_graph = self._build_agent_graph()

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

    def _should_stream_model(self) -> bool:
        if self._tool_event_listener is None:
            return False

        current_completion = getattr(self._create_completion_async, "__func__", None)
        current_streaming = getattr(
            self._create_completion_streaming_async, "__func__", None
        )
        default_completion = SandboxedReactAgent._create_completion_async
        default_streaming = SandboxedReactAgent._create_completion_streaming_async

        # Keep transport tests and local overrides working when only the
        # non-streaming completion path has been replaced.
        if (
            current_completion is not default_completion
            and current_streaming is default_streaming
        ):
            return False
        return True

    def _build_tool_runtime(self, session_id: str, runtime_config: dict[str, Any]):
        return self._agent_factory.build_tool_runtime(
            toolkit_providers=self.toolkit_providers,
            session_id=session_id,
            runtime_config=runtime_config,
            now_iso=now_iso,
            event_sink=self._notify_tool_event,
        )

    def _persist_session(self, session: SessionState) -> None:
        self._session_service.persist_session(session)

    async def _persist_session_async(self, session: SessionState) -> None:
        await self._session_service.persist_session_async(session)

    def _sanitize_messages(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return self._session_service.sanitize_messages(messages)

    def _title_from_text(self, text: str) -> str:
        return self._session_service.title_from_text(text)

    def get_user_profile(self, user_id: str) -> dict[str, Any]:
        return self._runtime_config_service.get_user_profile(user_id)

    def get_workspace(self, user_id: str) -> dict[str, Any] | None:
        workspace = self._workspace_service.get_workspace_for_user(user_id)
        return workspace.as_record() if workspace else None

    def get_workspace_status(self, user_id: str) -> dict[str, Any]:
        workspace = self.get_workspace(user_id)
        active_session_leases = []
        for session in self.sessions.values():
            if session.user_id != user_id:
                continue
            lease = self.sandbox_lease_facade.get_session_lease(session.session_id)
            if not lease:
                continue
            active_session_leases.append(
                {
                    "session_id": session.session_id,
                    "lease_id": lease.get("lease_id"),
                    "claim_name": lease.get("claim_name"),
                    "template_name": lease.get("template_name"),
                    "namespace": lease.get("namespace"),
                    "status": lease.get("status"),
                    "last_used_at": lease.get("last_used_at"),
                    "expires_at": lease.get("expires_at"),
                }
            )
        return {
            "workspace": workspace,
            "provisioning_pending": self._workspace_service.is_workspace_pending(
                user_id
            ),
            "active_session_leases": active_session_leases,
        }

    def ensure_workspace(self, user_id: str) -> dict[str, Any]:
        return self._workspace_service.get_or_create_user_workspace(user_id).as_record()

    def ensure_workspace_async(self, user_id: str) -> tuple[dict[str, Any], bool]:
        workspace, started = self._workspace_service.ensure_workspace_async(user_id)
        return workspace.as_record(), started

    def delete_workspace(self, user_id: str, *, delete_data: bool = False) -> bool:
        return self._workspace_service.delete_workspace_for_user(
            user_id,
            delete_data=delete_data,
        )

    def _bind_workspace_claim_for_session(
        self, session_id: str, *, claim_name: str | None, namespace: str | None
    ) -> None:
        session = self.sessions.get(session_id)
        if not session:
            return
        self._workspace_service.bind_claim_for_user(
            session.user_id,
            claim_name=claim_name,
            claim_namespace=namespace,
        )

    def _runtime_context_for_user(self, user_id: str) -> dict[str, Any]:
        runtime = self._runtime_config_service.resolve_user_runtime_config(user_id)
        return self._apply_workspace_runtime_overrides(user_id, runtime)

    def _default_runtime_context(self) -> dict[str, Any]:
        return self._runtime_config_service.default_runtime_config()

    def get_runtime_config(self, user_id: str) -> dict[str, Any]:
        return self._runtime_context_for_user(user_id)

    def _workspace_provisioning_enabled(
        self, infra_config: WorkspaceInfraConfig
    ) -> bool:
        raw = (
            (os.getenv("SANDBOX_WORKSPACE_PROVISIONING_ENABLED") or "").strip().lower()
        )
        if raw:
            return raw in {"1", "true", "yes", "on"}
        return bool(infra_config.project_id and infra_config.bucket_prefix)

    def _apply_workspace_runtime_overrides(
        self, user_id: str, runtime: dict[str, Any]
    ) -> dict[str, Any]:
        workspace = self._workspace_service.get_workspace_for_user(user_id)
        if not workspace or workspace.status != "ready":
            return runtime
        updated = json.loads(json.dumps(runtime))
        sandbox_runtime = (
            updated.setdefault("toolkits", {})
            .setdefault("sandbox", {})
            .setdefault("runtime", {})
        )
        sandbox_runtime["template_name"] = workspace.derived_template_name
        sandbox_runtime["namespace"] = (
            workspace.claim_namespace or self.sandbox_manager.namespace
        )
        updated.setdefault("workspace", workspace.as_record())
        return updated

    def _release_user_session_leases(self, user_id: str) -> None:
        for session in self.sessions.values():
            if session.user_id == user_id:
                self.sandbox_lease_facade.release_session(session.session_id)

    def update_runtime_config(
        self,
        user_id: str,
        agent: dict[str, Any] | None = None,
        toolkits: dict[str, Any] | None = None,
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
        return self._runtime_config_service.update_runtime_config(
            user_id=user_id,
            agent=agent,
            toolkits=toolkits,
            model=model,
            max_tool_calls_per_turn=max_tool_calls_per_turn,
            sandbox_mode=sandbox_mode,
            sandbox_api_url=sandbox_api_url,
            sandbox_template_name=sandbox_template_name,
            sandbox_namespace=sandbox_namespace,
            sandbox_server_port=sandbox_server_port,
            sandbox_max_output_chars=sandbox_max_output_chars,
            sandbox_local_timeout_seconds=sandbox_local_timeout_seconds,
            sandbox_execution_model=sandbox_execution_model,
            sandbox_session_idle_ttl_seconds=sandbox_session_idle_ttl_seconds,
        )

    def create_session(
        self, title: str | None = None, user_id: str = ""
    ) -> SessionState:
        return self._session_service.create_session(title=title, user_id=user_id)

    def get_or_create_session(
        self, session_id: str | None, user_id: str
    ) -> SessionState:
        return self._session_service.get_or_create_session(session_id, user_id)

    def _run_tool(
        self,
        *,
        session_id: str,
        tool_call_id: str | None,
        name: str,
        arguments_json: str,
        runtime_config: dict[str, Any],
    ) -> tuple[str, list[dict[str, Any]]]:
        toolkit = self._build_tool_runtime(session_id, runtime_config)
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
        state.messages = self._session_service.sanitize_messages(state.messages)
        state.updated_at = now_iso()
        state.messages.append({"role": "user", "content": user_message})
        if state.title == "New chat":
            state.title = self._session_service.title_from_text(user_message)
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
            state.updated_at = now_iso()

            if result.get("limit_reached"):
                state.last_error = result.get("error") or (
                    "Tool-calling loop exhausted max tool calls"
                )
            else:
                state.last_error = result.get("error") or None

            self._session_service.persist_session(state)
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
                state.messages = [state.messages[0]] if state.messages else []
            self._session_service.persist_session(state)
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
        sessions = self._session_service.get_state_sessions(user_id)
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
        return self._session_service.reset_session(session_id, user_id)

    def list_sandboxes(self) -> list[dict[str, Any]]:
        return self._sandbox_admin.list_sandboxes()

    def get_sandbox(self, lease_id: str) -> dict[str, Any] | None:
        return self._sandbox_admin.get_sandbox(lease_id)

    def release_sandbox(self, lease_id: str) -> bool:
        return self._sandbox_admin.release_sandbox(lease_id)

    def list_sessions(self, user_id: str) -> list[dict[str, Any]]:
        return self._session_service.list_sessions(user_id)

    def get_session(self, session_id: str, user_id: str) -> dict[str, Any] | None:
        return self._session_service.get_session(session_id, user_id)

    def get_session_sandbox(self, session_id: str) -> dict[str, Any]:
        return self._sandbox_admin.get_session_sandbox(session_id)

    def create_share(self, session_id: str, user_id: str) -> str | None:
        return self._sharing_service.create_share(session_id, user_id)

    def get_shared_session(self, share_id: str) -> dict[str, Any] | None:
        return self._sharing_service.get_shared_session(share_id)

    def get_shared_session_markdown(self, share_id: str) -> str | None:
        return self._sharing_service.get_shared_session_markdown(share_id)
