import asyncio
import copy
import contextvars
import inspect
import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
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
from .repositories.workspace_job_repository import WorkspaceJobRepository
from .sandbox_lifecycle import SandboxLifecycleService
from .sandbox_manager import SandboxManager
from .services.runtime_config_service import RuntimeConfigService
from .services.sandbox_admin_service import SandboxAdminService
from .services.sandbox_terminal_service import SandboxTerminalService
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
from .authz import AccessContext, AuthorizationPolicyService


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _seconds_between(earlier: datetime | None, later: datetime | None) -> int | None:
    if earlier is None or later is None:
        return None
    diff = (later - earlier).total_seconds()
    if diff < 0:
        return 0
    return int(diff)


def _csv_values(raw: str | None) -> list[str]:
    if raw is None:
        return []
    values: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        value = part.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


class AuthorizationError(RuntimeError):
    """Raised when a request is authenticated but lacks required capability."""


class SandboxedReactAgent:
    """Application facade that composes runtime, services, and toolkit providers."""

    def __init__(
        self,
        *,
        authorization_service: AuthorizationPolicyService | None = None,
    ) -> None:
        self.authorization_service = authorization_service
        self._access_context_var: contextvars.ContextVar[AccessContext | None] = (
            contextvars.ContextVar("authz_access_context", default=None)
        )
        self.allow_local_sandbox_mode = str(
            os.getenv("SANDBOX_ALLOW_LOCAL_MODE", "")
        ).strip().lower() in {"1", "true", "yes", "on"}
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
        self.workspace_job_repository = WorkspaceJobRepository(self.session_store)
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
            resolve_workspace_template_for_user=lambda user_id, requested_template_name: (
                self.resolve_workspace_template_for_runtime(
                    user_id,
                    requested_template_name=requested_template_name,
                )
            ),
            ensure_workspace_async_for_user=lambda user_id, reconcile_ready=False: (
                self.ensure_workspace_async(
                    user_id,
                    reconcile_ready=reconcile_ready,
                )
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
        self._sandbox_toolkit_provider = SandboxToolkitProvider(
            self.session_sandbox_facade,
            self.sandbox_manager,
            self.sandbox_lifecycle,
            allow_local_mode=self.allow_local_sandbox_mode,
            get_session_status=lambda session_id: (
                self.get_session_sandbox_status_for_tools(session_id)
            ),
            get_workspace_status=lambda session_id: self.get_workspace_status_for_tools(
                session_id
            ),
            list_available_sandboxes=lambda session_id: (
                self.list_available_sandboxes_for_tools(session_id)
            ),
            set_session_policy=lambda session_id, policy: (
                self.set_session_sandbox_policy_for_tools(
                    session_id,
                    policy,
                )
            ),
            release_session_lease=lambda session_id: (
                self.release_session_sandbox_for_tools(session_id)
            ),
            reconcile_workspace=lambda session_id, wait=False: (
                self.reconcile_workspace_for_tools(
                    session_id,
                    wait=wait,
                )
            ),
            open_interactive_shell=lambda session_id: (
                self.open_interactive_shell_for_tools(session_id)
            ),
        )
        self.toolkit_providers: list[ToolkitProvider] = [
            self._sandbox_toolkit_provider,
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
        self._sandbox_terminal = SandboxTerminalService(
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
        workspace_base_templates = _csv_values(
            os.getenv("SANDBOX_WORKSPACE_BASE_TEMPLATE_NAMES")
        )
        if workspace_base_templates:
            workspace_primary_template = workspace_base_templates[0]
            workspace_additional_templates = tuple(workspace_base_templates[1:])
        else:
            workspace_primary_template = (
                os.getenv(
                    "SANDBOX_WORKSPACE_BASE_TEMPLATE_NAME",
                    self.sandbox_manager.template_name,
                ).strip()
                or self.sandbox_manager.template_name
            )
            workspace_additional_templates = ()
        infra_config = WorkspaceInfraConfig(
            project_id=os.getenv("GCP_PROJECT_ID", ""),
            bucket_prefix=os.getenv("SANDBOX_WORKSPACE_BUCKET_PREFIX", ""),
            namespace=os.getenv("SANDBOX_NAMESPACE", self.sandbox_manager.namespace),
            base_template_name=workspace_primary_template,
            base_template_names=workspace_additional_templates,
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
            workspace_job_repository=self.workspace_job_repository,
            max_workers=int(os.getenv("WORKSPACE_PROVISIONER_MAX_WORKERS", "4")),
            max_retry_attempts=int(os.getenv("WORKSPACE_JOB_MAX_RETRY_ATTEMPTS", "3")),
            retry_backoff_seconds=float(
                os.getenv("WORKSPACE_JOB_RETRY_BACKOFF_SECONDS", "5")
            ),
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
            runtime_context_for_session=self._runtime_context_for_session,
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

    def search_admin_users(self, query: str = "", *, limit: int = 20) -> dict[str, Any]:
        safe_limit = min(max(int(limit), 1), 100)
        users = self.user_repository.search_users(query=query, limit=safe_limit)
        return {
            "generated_at": now_iso(),
            "query": str(query or ""),
            "limit": safe_limit,
            "users": users,
        }

    def get_workspace(self, user_id: str) -> dict[str, Any] | None:
        workspace = self._workspace_service.get_workspace_for_user(user_id)
        return workspace.as_record() if workspace else None

    def resolve_workspace_template_for_runtime(
        self,
        user_id: str,
        *,
        requested_template_name: str | None,
    ) -> str:
        return self._workspace_service.resolve_derived_template_name(
            user_id,
            requested_template_name=requested_template_name,
        )

    def workspace_base_template_names(self) -> list[str]:
        return self._workspace_service.workspace_base_template_names()

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

    def ensure_workspace_async(
        self, user_id: str, *, reconcile_ready: bool = False
    ) -> tuple[dict[str, Any], bool]:
        workspace, started = self._workspace_service.ensure_workspace_async(
            user_id,
            reconcile_ready=reconcile_ready,
        )
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

    @contextmanager
    def bind_access_context(self, access_context: AccessContext | None):
        access_var = getattr(self, "_access_context_var", None)
        if access_var is None:
            yield
            return
        token = access_var.set(access_context)
        try:
            yield
        finally:
            access_var.reset(token)

    def _active_access_context(self, user_id: str) -> AccessContext | None:
        access_var = getattr(self, "_access_context_var", None)
        if access_var is None:
            return None
        context = access_var.get()
        if context is None:
            return None
        if str(context.user_id or "").strip() != str(user_id or "").strip():
            return None
        return context

    def _authorized_values(
        self,
        context: AccessContext | None,
        *,
        category: str,
        candidates: list[str],
    ) -> list[str]:
        authorization_service = getattr(self, "authorization_service", None)
        if authorization_service is None:
            return list(dict.fromkeys(candidates))
        return authorization_service.filter_sandbox_values(
            context,
            category=category,
            values=candidates,
        )

    def _constrain_runtime_context_for_access(
        self,
        user_id: str,
        runtime_context: dict[str, Any],
    ) -> dict[str, Any]:
        context = self._active_access_context(user_id)
        if context is None:
            return runtime_context

        merged = copy.deepcopy(runtime_context)
        sandbox_toolkit = merged.setdefault("toolkits", {}).setdefault("sandbox", {})
        sandbox_runtime = sandbox_toolkit.setdefault("runtime", {})
        sandbox_lifecycle = sandbox_toolkit.setdefault("lifecycle", {})

        mode_candidates = ["cluster"] + (
            ["local"] if self.allow_local_sandbox_mode else []
        )
        allowed_modes = self._authorized_values(
            context,
            category="modes",
            candidates=mode_candidates,
        )
        current_mode = str(sandbox_runtime.get("mode") or "cluster").strip().lower()
        if allowed_modes and current_mode not in {
            item.lower() for item in allowed_modes
        }:
            sandbox_runtime["mode"] = allowed_modes[0]

        profile_candidates = ["persistent_workspace", "transient"]
        allowed_profiles = self._authorized_values(
            context,
            category="profiles",
            candidates=profile_candidates,
        )
        current_profile = (
            str(sandbox_runtime.get("profile") or "persistent_workspace")
            .strip()
            .lower()
        )
        if allowed_profiles and current_profile not in {
            item.lower() for item in allowed_profiles
        }:
            sandbox_runtime["profile"] = allowed_profiles[0]

        execution_model_candidates = ["session", "ephemeral"]
        allowed_execution_models = self._authorized_values(
            context,
            category="execution_models",
            candidates=execution_model_candidates,
        )
        current_execution_model = (
            str(sandbox_lifecycle.get("execution_model") or "session").strip().lower()
        )
        if allowed_execution_models and current_execution_model not in {
            item.lower() for item in allowed_execution_models
        }:
            sandbox_lifecycle["execution_model"] = allowed_execution_models[0]

        template_candidates = [
            str(sandbox_runtime.get("template_name") or "").strip(),
            self.sandbox_manager.template_name,
            *self.workspace_base_template_names(),
        ]
        template_candidates = [
            candidate for candidate in template_candidates if candidate
        ]
        allowed_templates = self._authorized_values(
            context,
            category="templates",
            candidates=template_candidates,
        )
        current_template = str(sandbox_runtime.get("template_name") or "").strip()
        if allowed_templates and current_template not in set(allowed_templates):
            sandbox_runtime["template_name"] = allowed_templates[0]

        return merged

    def _runtime_context_for_user(self, user_id: str) -> dict[str, Any]:
        runtime = self._runtime_config_service.resolve_user_runtime_config(user_id)
        return self._constrain_runtime_context_for_access(user_id, runtime)

    def _apply_session_sandbox_policy(
        self, runtime_config: dict[str, Any], sandbox_policy: dict[str, Any]
    ) -> dict[str, Any]:
        if not sandbox_policy:
            return runtime_config

        sandbox_runtime_updates: dict[str, Any] = {}
        sandbox_lifecycle_updates: dict[str, Any] = {}
        for runtime_key in ("mode", "profile", "template_name", "namespace"):
            value = sandbox_policy.get(runtime_key)
            if value is not None:
                sandbox_runtime_updates[runtime_key] = value

        for lifecycle_key in ("execution_model", "session_idle_ttl_seconds"):
            value = sandbox_policy.get(lifecycle_key)
            if value is not None:
                sandbox_lifecycle_updates[lifecycle_key] = value

        if not sandbox_runtime_updates and not sandbox_lifecycle_updates:
            return runtime_config

        merged = json.loads(json.dumps(runtime_config))
        sandbox_config = (
            (merged.setdefault("toolkits", {}).setdefault("sandbox", {}))
            if isinstance(merged.get("toolkits"), dict)
            else merged.setdefault("toolkits", {}).setdefault("sandbox", {})
        )
        updated_toolkit = self._sandbox_toolkit_provider.apply_updates(
            copy.deepcopy(sandbox_config if isinstance(sandbox_config, dict) else {}),
            toolkit_updates={
                "runtime": sandbox_runtime_updates,
                "lifecycle": sandbox_lifecycle_updates,
            },
        )
        merged.setdefault("toolkits", {})["sandbox"] = updated_toolkit
        return merged

    def _runtime_context_for_session(
        self, user_id: str, session_id: str
    ) -> dict[str, Any]:
        runtime = self._runtime_context_for_user(user_id)
        session = self.sessions.get(session_id)
        if not session:
            return runtime
        if session.user_id != user_id:
            return runtime
        return self._apply_session_sandbox_policy(runtime, session.sandbox_policy)

    def _assert_authorized_sandbox_value(
        self,
        user_id: str,
        *,
        category: str,
        value: Any,
    ) -> None:
        normalized = str(value or "").strip()
        if not normalized:
            return
        access_context = self._active_access_context(user_id)
        authorization_service = getattr(self, "authorization_service", None)
        if authorization_service is None or access_context is None:
            return
        if authorization_service.is_sandbox_value_allowed(
            access_context,
            category=category,
            value=normalized,
        ):
            return
        raise AuthorizationError(
            f"Not authorized to use sandbox {category.rstrip('s')} '{normalized}'."
        )

    def _assert_authorized_feature(self, user_id: str, feature: str) -> None:
        access_context = self._active_access_context(user_id)
        authorization_service = getattr(self, "authorization_service", None)
        if authorization_service is None or access_context is None:
            return
        if authorization_service.is_feature_allowed(access_context, feature):
            return
        raise AuthorizationError(f"Not authorized for feature '{feature}'.")

    def _sandbox_runtime_context(
        self, runtime_context: dict[str, Any]
    ) -> dict[str, Any]:
        sandbox_toolkit = (runtime_context.get("toolkits") or {}).get("sandbox") or {}
        sandbox_runtime = sandbox_toolkit.get("runtime") or {}
        sandbox_lifecycle = sandbox_toolkit.get("lifecycle") or {}
        flattened: dict[str, Any] = {}
        if isinstance(sandbox_runtime, dict):
            flattened.update(sandbox_runtime)
        if isinstance(sandbox_lifecycle, dict):
            flattened.update(sandbox_lifecycle)
        return flattened

    def get_session_sandbox_policy(
        self, session_id: str, user_id: str
    ) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if not session or session.user_id != user_id:
            raise PermissionError("Session not found")
        return dict(session.sandbox_policy or {})

    def update_session_sandbox_policy(
        self,
        session_id: str,
        user_id: str,
        policy_updates: dict[str, Any],
        *,
        clear: bool = False,
    ) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if not session or session.user_id != user_id:
            raise PermissionError("Session not found")

        current_policy = {} if clear else dict(session.sandbox_policy or {})
        for key in (
            "mode",
            "profile",
            "template_name",
            "namespace",
            "execution_model",
            "session_idle_ttl_seconds",
        ):
            if key not in policy_updates:
                continue
            value = policy_updates.get(key)
            if value is None:
                current_policy.pop(key, None)
                continue
            current_policy[key] = value

        if "mode" in current_policy:
            self._assert_authorized_sandbox_value(
                user_id,
                category="modes",
                value=current_policy.get("mode"),
            )
        if "profile" in current_policy:
            self._assert_authorized_sandbox_value(
                user_id,
                category="profiles",
                value=current_policy.get("profile"),
            )
        if "template_name" in current_policy:
            self._assert_authorized_sandbox_value(
                user_id,
                category="templates",
                value=current_policy.get("template_name"),
            )
        if "execution_model" in current_policy:
            self._assert_authorized_sandbox_value(
                user_id,
                category="execution_models",
                value=current_policy.get("execution_model"),
            )

        # Validate by attempting to apply to resolved runtime.
        self._apply_session_sandbox_policy(
            self._runtime_context_for_user(user_id),
            current_policy,
        )

        changed = current_policy != dict(session.sandbox_policy or {})
        session.sandbox_policy = current_policy
        session.updated_at = now_iso()
        self._session_service.persist_session(session)

        if changed:
            self.sandbox_lease_facade.release_session(session_id)

        return {
            "session_id": session_id,
            "sandbox_policy": dict(session.sandbox_policy or {}),
            "lease_released": bool(changed),
        }

    def _available_cluster_templates(self, namespace: str) -> list[dict[str, str]]:
        templates: list[dict[str, str]] = []
        try:
            from kubernetes import client, config

            try:
                config.load_incluster_config()
            except Exception:
                config.load_kube_config()

            api = client.CustomObjectsApi()
            payload = api.list_namespaced_custom_object(
                group="extensions.agents.x-k8s.io",
                version="v1alpha1",
                namespace=namespace,
                plural="sandboxtemplates",
            )
            for item in list(payload.get("items") or []):
                metadata = item.get("metadata") or {}
                labels = metadata.get("labels") or {}
                if (
                    str(labels.get("managed-by") or "").strip().lower()
                    == "sandbox-workspace-provisioner"
                ):
                    continue
                name = str(metadata.get("name") or "").strip()
                if not name:
                    continue
                templates.append({"name": name, "namespace": namespace})
        except Exception:
            pass

        if templates:
            templates.sort(key=lambda item: item["name"])
            return templates

        return [
            {"name": "python-runtime-template-small", "namespace": namespace},
            {"name": "python-runtime-template", "namespace": namespace},
            {"name": "python-runtime-template-large", "namespace": namespace},
            {"name": "python-runtime-template-pydata", "namespace": namespace},
        ]

    def list_available_sandboxes(self, user_id: str) -> dict[str, Any]:
        access_context = self._active_access_context(user_id)
        runtime = self._runtime_context_for_user(user_id)
        sandbox_runtime = ((runtime.get("toolkits") or {}).get("sandbox") or {}).get(
            "runtime"
        ) or {}
        namespace = str(
            sandbox_runtime.get("namespace") or self.sandbox_manager.namespace
        )
        workspace_base_templates = self.workspace_base_template_names()

        profiles = self._authorized_values(
            access_context,
            category="profiles",
            candidates=["persistent_workspace", "transient"],
        )
        execution_models = self._authorized_values(
            access_context,
            category="execution_models",
            candidates=["session", "ephemeral"],
        )
        modes = self._authorized_values(
            access_context,
            category="modes",
            candidates=["cluster"]
            + (["local"] if self.allow_local_sandbox_mode else []),
        )
        templates = self._available_cluster_templates(namespace)
        allowed_template_names = set(
            self._authorized_values(
                access_context,
                category="templates",
                candidates=[
                    str(item.get("name") or "")
                    for item in templates
                    if str(item.get("name") or "").strip()
                ],
            )
        )
        filtered_templates = [
            item
            for item in templates
            if str(item.get("name") or "") in allowed_template_names
        ]
        allowed_workspace_base_templates = set(
            self._authorized_values(
                access_context,
                category="templates",
                candidates=workspace_base_templates,
            )
        )
        filtered_workspace_base_templates = [
            item
            for item in workspace_base_templates
            if item in allowed_workspace_base_templates
        ]

        return {
            "profiles": profiles,
            "execution_models": execution_models,
            "modes": modes,
            "templates": filtered_templates,
            "persistent_workspace": {
                "base_templates": filtered_workspace_base_templates,
                "primary_base_template": (
                    filtered_workspace_base_templates[0]
                    if filtered_workspace_base_templates
                    else self.sandbox_manager.template_name
                ),
            },
        }

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
        sandbox_profile: str | None = None,
        sandbox_api_url: str | None = None,
        sandbox_template_name: str | None = None,
        sandbox_namespace: str | None = None,
        sandbox_server_port: int | None = None,
        sandbox_max_output_chars: int | None = None,
        sandbox_local_timeout_seconds: int | None = None,
        sandbox_execution_model: str | None = None,
        sandbox_session_idle_ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        if sandbox_mode is not None:
            self._assert_authorized_sandbox_value(
                user_id,
                category="modes",
                value=sandbox_mode,
            )
        if sandbox_profile is not None:
            self._assert_authorized_sandbox_value(
                user_id,
                category="profiles",
                value=sandbox_profile,
            )
        if sandbox_template_name is not None:
            self._assert_authorized_sandbox_value(
                user_id,
                category="templates",
                value=sandbox_template_name,
            )
        if sandbox_execution_model is not None:
            self._assert_authorized_sandbox_value(
                user_id,
                category="execution_models",
                value=sandbox_execution_model,
            )

        sandbox_toolkit_updates = (
            toolkits.get("sandbox") if isinstance(toolkits, dict) else None
        )
        if isinstance(sandbox_toolkit_updates, dict):
            runtime_updates = sandbox_toolkit_updates.get("runtime")
            if isinstance(runtime_updates, dict):
                if runtime_updates.get("mode") is not None:
                    self._assert_authorized_sandbox_value(
                        user_id,
                        category="modes",
                        value=runtime_updates.get("mode"),
                    )
                if runtime_updates.get("profile") is not None:
                    self._assert_authorized_sandbox_value(
                        user_id,
                        category="profiles",
                        value=runtime_updates.get("profile"),
                    )
                if runtime_updates.get("template_name") is not None:
                    self._assert_authorized_sandbox_value(
                        user_id,
                        category="templates",
                        value=runtime_updates.get("template_name"),
                    )
            lifecycle_updates = sandbox_toolkit_updates.get("lifecycle")
            if isinstance(lifecycle_updates, dict):
                if lifecycle_updates.get("execution_model") is not None:
                    self._assert_authorized_sandbox_value(
                        user_id,
                        category="execution_models",
                        value=lifecycle_updates.get("execution_model"),
                    )

        return self._runtime_config_service.update_runtime_config(
            user_id=user_id,
            agent=agent,
            toolkits=toolkits,
            model=model,
            max_tool_calls_per_turn=max_tool_calls_per_turn,
            sandbox_mode=sandbox_mode,
            sandbox_profile=sandbox_profile,
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
        state = self.get_or_create_session(session_id, user_id)
        runtime_config = self._runtime_context_for_session(user_id, state.session_id)
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

    def _build_admin_lease_entries(
        self,
        leases: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        now = datetime.now(UTC)
        sessions_by_id = {
            str(record.get("session_id") or ""): record
            for record in self.session_repository.list_sessions()
            if str(record.get("session_id") or "")
        }
        workspaces_by_user_id = {
            str(record.get("user_id") or ""): record
            for record in self.user_workspace_repository.list_workspaces()
            if str(record.get("user_id") or "")
        }
        cached_user_profiles: dict[str, dict[str, Any] | None] = {}

        entries: list[dict[str, Any]] = []
        for lease in leases:
            scope_type = str(lease.get("scope_type") or "")
            scope_key = str(lease.get("scope_key") or "")
            status = str(lease.get("status") or "")
            session_id = scope_key if scope_type == "session" and scope_key else None
            session_record = sessions_by_id.get(session_id or "")

            metadata = lease.get("metadata")
            metadata_dict = metadata if isinstance(metadata, dict) else {}

            user_id = ""
            if session_record:
                user_id = str(session_record.get("user_id") or "").strip()
            if not user_id:
                for key in (
                    "user_id",
                    "scope_user_id",
                    "owner_user_id",
                    "requested_by",
                ):
                    value = str(metadata_dict.get(key) or "").strip()
                    if value:
                        user_id = value
                        break
            if not user_id and scope_type == "user" and scope_key:
                user_id = scope_key

            workspace = workspaces_by_user_id.get(user_id) if user_id else None
            user_profile = None
            if user_id:
                if user_id not in cached_user_profiles:
                    cached_user_profiles[user_id] = self.user_repository.get_user(
                        user_id
                    )
                user_profile = cached_user_profiles.get(user_id)

            created_at = str(lease.get("created_at") or "")
            last_used_at = str(lease.get("last_used_at") or "")
            expires_at = str(lease.get("expires_at") or "")
            released_at = str(lease.get("released_at") or "")
            created_dt = _parse_iso_datetime(created_at)
            last_used_dt = _parse_iso_datetime(last_used_at)
            expires_dt = _parse_iso_datetime(expires_at)
            released_dt = _parse_iso_datetime(released_at)

            duration_seconds = _seconds_between(created_dt, released_dt)
            age_seconds = _seconds_between(created_dt, now)
            idle_seconds = _seconds_between(last_used_dt, now)
            expires_in_seconds = _seconds_between(now, expires_dt)

            is_active = status in {"pending", "ready"}
            expires_soon = (
                is_active
                and isinstance(expires_in_seconds, int)
                and 0 <= expires_in_seconds <= 900
            )
            stale = is_active and isinstance(idle_seconds, int) and idle_seconds >= 3600

            entries.append(
                {
                    "lease_id": str(lease.get("lease_id") or ""),
                    "scope_type": scope_type,
                    "scope_key": scope_key,
                    "status": status,
                    "claim_name": str(lease.get("claim_name") or ""),
                    "template_name": str(lease.get("template_name") or ""),
                    "namespace": str(lease.get("namespace") or ""),
                    "created_at": created_at,
                    "last_used_at": last_used_at,
                    "expires_at": expires_at,
                    "released_at": released_at or None,
                    "last_error": str(lease.get("last_error") or "") or None,
                    "metadata": metadata_dict,
                    "session_id": session_id,
                    "session_exists": bool(session_record),
                    "session_title": (
                        str(session_record.get("title") or "")
                        if session_record
                        else None
                    ),
                    "session_updated_at": (
                        str(session_record.get("updated_at") or "")
                        if session_record
                        else None
                    ),
                    "user_id": user_id or None,
                    "user_tier": (
                        str(user_profile.get("tier") or "") if user_profile else None
                    ),
                    "workspace_id": (
                        str(workspace.get("workspace_id") or "") if workspace else None
                    ),
                    "workspace_status": (
                        str(workspace.get("status") or "") if workspace else None
                    ),
                    "workspace_template_name": (
                        str(workspace.get("derived_template_name") or "")
                        if workspace
                        else None
                    ),
                    "workspace_claim_name": (
                        str(workspace.get("claim_name") or "") if workspace else None
                    ),
                    "workspace_last_error": (
                        str(workspace.get("last_error") or "") if workspace else None
                    ),
                    "is_active": is_active,
                    "expires_soon": expires_soon,
                    "stale": stale,
                    "duration_seconds": duration_seconds,
                    "age_seconds": age_seconds,
                    "idle_seconds": idle_seconds,
                    "expires_in_seconds": expires_in_seconds,
                }
            )

        workspace_status_counts: dict[str, int] = {}
        for workspace in workspaces_by_user_id.values():
            status = str(workspace.get("status") or "unknown")
            workspace_status_counts[status] = workspace_status_counts.get(status, 0) + 1

        return entries, {
            "workspace_status_counts": workspace_status_counts,
            "workspace_total": len(workspaces_by_user_id),
        }

    def get_admin_sandbox_index(self, *, limit: int = 500) -> dict[str, Any]:
        safe_limit = min(max(int(limit), 1), 5000)
        leases = self._sandbox_admin.list_all_sandboxes(limit=safe_limit)
        entries, workspace_stats = self._build_admin_lease_entries(leases)

        status_counts: dict[str, int] = {}
        active_entries = []
        claim_owner_index: dict[str, dict[str, Any]] = {}

        for entry in entries:
            status = str(entry.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            if entry.get("is_active"):
                active_entries.append(entry)

        active_sorted = sorted(
            active_entries,
            key=lambda item: str(
                item.get("last_used_at") or item.get("created_at") or ""
            ),
            reverse=True,
        )
        for entry in active_sorted:
            claim_name = str(entry.get("claim_name") or "")
            if claim_name and claim_name not in claim_owner_index:
                claim_owner_index[claim_name] = {
                    "lease_id": entry.get("lease_id"),
                    "session_id": entry.get("session_id"),
                    "user_id": entry.get("user_id"),
                    "status": entry.get("status"),
                    "template_name": entry.get("template_name"),
                    "workspace_status": entry.get("workspace_status"),
                    "created_at": entry.get("created_at"),
                    "last_used_at": entry.get("last_used_at"),
                    "expires_at": entry.get("expires_at"),
                    "expires_soon": entry.get("expires_soon"),
                }

        unhealthy_count = sum(
            1
            for entry in active_entries
            if bool(entry.get("expires_soon"))
            or bool(entry.get("stale"))
            or (not entry.get("session_exists"))
            or (
                str(entry.get("workspace_status") or "") not in {"", "ready", "deleted"}
            )
        )

        return {
            "generated_at": now_iso(),
            "limit": safe_limit,
            "leases": entries,
            "active_leases": active_sorted,
            "claim_owner_index": claim_owner_index,
            "summary": {
                "total_leases": len(entries),
                "active_leases": len(active_entries),
                "status_counts": status_counts,
                "active_session_leases": sum(
                    1
                    for entry in active_entries
                    if str(entry.get("scope_type") or "") == "session"
                ),
                "expiring_soon_leases": sum(
                    1 for entry in active_entries if bool(entry.get("expires_soon"))
                ),
                "stale_active_leases": sum(
                    1 for entry in active_entries if bool(entry.get("stale"))
                ),
                "unhealthy_active_leases": unhealthy_count,
                "active_leases_without_session": sum(
                    1
                    for entry in active_entries
                    if str(entry.get("scope_type") or "") == "session"
                    and not bool(entry.get("session_exists"))
                ),
                "workspace_total": int(workspace_stats.get("workspace_total") or 0),
                "workspace_status_counts": workspace_stats.get(
                    "workspace_status_counts"
                )
                or {},
            },
        }

    def get_admin_lease_analytics(
        self,
        *,
        days: int = 14,
        limit: int = 200,
    ) -> dict[str, Any]:
        safe_days = min(max(int(days), 1), 90)
        safe_limit = min(max(int(limit), 1), 2000)
        leases = self._sandbox_admin.list_all_sandboxes(limit=None)
        entries, _ = self._build_admin_lease_entries(leases)

        now = datetime.now(UTC)
        start_date = (now - timedelta(days=safe_days - 1)).date()
        daily_created: dict[str, int] = {}
        daily_released: dict[str, int] = {}

        for day_offset in range(safe_days):
            day = start_date + timedelta(days=day_offset)
            key = day.isoformat()
            daily_created[key] = 0
            daily_released[key] = 0

        status_counts: dict[str, int] = {}
        scope_counts: dict[str, int] = {}
        lifetime_seconds_by_status: dict[str, list[int]] = {}

        for entry in entries:
            status = str(entry.get("status") or "unknown")
            scope_type = str(entry.get("scope_type") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            scope_counts[scope_type] = scope_counts.get(scope_type, 0) + 1

            created_dt = _parse_iso_datetime(entry.get("created_at"))
            if created_dt and created_dt.date() >= start_date:
                key = created_dt.date().isoformat()
                if key in daily_created:
                    daily_created[key] += 1

            released_dt = _parse_iso_datetime(entry.get("released_at"))
            if released_dt and released_dt.date() >= start_date:
                key = released_dt.date().isoformat()
                if key in daily_released:
                    daily_released[key] += 1

            duration = entry.get("duration_seconds")
            if isinstance(duration, int):
                lifetime_seconds_by_status.setdefault(status, []).append(duration)

        lifetime_stats = []
        for status, samples in sorted(lifetime_seconds_by_status.items()):
            if not samples:
                continue
            lifetime_stats.append(
                {
                    "status": status,
                    "samples": len(samples),
                    "avg_seconds": int(sum(samples) / len(samples)),
                    "min_seconds": int(min(samples)),
                    "max_seconds": int(max(samples)),
                }
            )

        recent_events = sorted(
            entries,
            key=lambda item: str(
                item.get("released_at")
                or item.get("last_used_at")
                or item.get("created_at")
                or ""
            ),
            reverse=True,
        )[:safe_limit]
        recent_event_rows = [
            {
                "lease_id": row.get("lease_id"),
                "status": row.get("status"),
                "scope_type": row.get("scope_type"),
                "scope_key": row.get("scope_key"),
                "claim_name": row.get("claim_name"),
                "session_id": row.get("session_id"),
                "user_id": row.get("user_id"),
                "workspace_status": row.get("workspace_status"),
                "created_at": row.get("created_at"),
                "last_used_at": row.get("last_used_at"),
                "released_at": row.get("released_at"),
                "duration_seconds": row.get("duration_seconds"),
                "idle_seconds": row.get("idle_seconds"),
                "expires_at": row.get("expires_at"),
                "last_error": row.get("last_error"),
            }
            for row in recent_events
        ]

        return {
            "generated_at": now_iso(),
            "days": safe_days,
            "limit": safe_limit,
            "summary": {
                "total_leases": len(entries),
                "active_leases": sum(
                    1 for entry in entries if bool(entry.get("is_active"))
                ),
                "status_counts": status_counts,
                "scope_counts": scope_counts,
                "expiring_soon_active": sum(
                    1
                    for entry in entries
                    if bool(entry.get("is_active")) and bool(entry.get("expires_soon"))
                ),
                "stale_active": sum(
                    1
                    for entry in entries
                    if bool(entry.get("is_active")) and bool(entry.get("stale"))
                ),
            },
            "daily_created": [
                {"date": key, "count": daily_created[key]}
                for key in sorted(daily_created.keys())
            ],
            "daily_released": [
                {"date": key, "count": daily_released[key]}
                for key in sorted(daily_released.keys())
            ],
            "lifetime_by_status": lifetime_stats,
            "recent_events": recent_event_rows,
        }

    def get_admin_workspace_jobs(
        self,
        *,
        limit: int = 200,
        include_terminal: bool = True,
    ) -> dict[str, Any]:
        safe_limit = min(max(int(limit), 1), 2000)
        jobs = self.workspace_job_repository.list_jobs(
            limit=safe_limit,
            include_terminal=include_terminal,
        )
        now = datetime.now(UTC)
        workspaces_by_id = {
            str(record.get("workspace_id") or ""): record
            for record in self.user_workspace_repository.list_workspaces()
            if str(record.get("workspace_id") or "")
        }
        cached_users: dict[str, dict[str, Any] | None] = {}

        entries: list[dict[str, Any]] = []
        for job in jobs:
            user_id = str(job.get("user_id") or "").strip()
            workspace_id = str(job.get("workspace_id") or "").strip()
            workspace = workspaces_by_id.get(workspace_id)
            if user_id not in cached_users:
                cached_users[user_id] = self.user_repository.get_user(user_id)
            user = cached_users.get(user_id)

            created_dt = _parse_iso_datetime(job.get("created_at"))
            started_dt = _parse_iso_datetime(job.get("started_at"))
            completed_dt = _parse_iso_datetime(job.get("completed_at"))
            lease_expires_dt = _parse_iso_datetime(job.get("lease_expires_at"))
            status = str(job.get("status") or "")

            queue_wait_seconds = _seconds_between(created_dt, started_dt)
            run_seconds = _seconds_between(
                started_dt,
                completed_dt if completed_dt is not None else now,
            )
            age_seconds = _seconds_between(created_dt, now)
            lease_expires_in_seconds = _seconds_between(now, lease_expires_dt)
            stale_running = (
                status == "running"
                and lease_expires_dt is not None
                and lease_expires_dt < now
            )

            entries.append(
                {
                    "job_id": str(job.get("job_id") or ""),
                    "user_id": user_id or None,
                    "user_tier": (
                        str(user.get("tier") or "") if isinstance(user, dict) else None
                    ),
                    "workspace_id": workspace_id or None,
                    "workspace_status": (
                        str(workspace.get("status") or "") if workspace else None
                    ),
                    "workspace_status_reason": (
                        str(workspace.get("status_reason") or "") if workspace else None
                    ),
                    "status": status,
                    "reconcile_ready": bool(job.get("reconcile_ready")),
                    "attempt_count": int(job.get("attempt_count") or 0),
                    "last_error": str(job.get("last_error") or "") or None,
                    "created_at": str(job.get("created_at") or ""),
                    "started_at": str(job.get("started_at") or "") or None,
                    "completed_at": str(job.get("completed_at") or "") or None,
                    "lease_expires_at": str(job.get("lease_expires_at") or "") or None,
                    "worker_id": str(job.get("worker_id") or "") or None,
                    "queue_wait_seconds": queue_wait_seconds,
                    "run_seconds": run_seconds,
                    "age_seconds": age_seconds,
                    "lease_expires_in_seconds": lease_expires_in_seconds,
                    "stale_running": stale_running,
                }
            )

        status_counts: dict[str, int] = {}
        for entry in entries:
            status = str(entry.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

        return {
            "generated_at": now_iso(),
            "limit": safe_limit,
            "include_terminal": bool(include_terminal),
            "summary": {
                "total_jobs": len(entries),
                "queued_jobs": sum(
                    1 for entry in entries if str(entry.get("status") or "") == "queued"
                ),
                "running_jobs": sum(
                    1
                    for entry in entries
                    if str(entry.get("status") or "") == "running"
                ),
                "failed_jobs": sum(
                    1 for entry in entries if str(entry.get("status") or "") == "failed"
                ),
                "stale_running_jobs": sum(
                    1 for entry in entries if bool(entry.get("stale_running"))
                ),
                "status_counts": status_counts,
            },
            "jobs": entries,
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

    def open_session_terminal(self, session_id: str, user_id: str) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if not session or session.user_id != user_id:
            raise PermissionError("Session not found")
        self._assert_authorized_feature(user_id, "terminal.open")
        runtime_context = self._runtime_context_for_session(user_id, session_id)
        runtime_config = self._sandbox_runtime_context(runtime_context)
        return self._sandbox_terminal.open_terminal(
            session_id=session_id,
            user_id=user_id,
            runtime_config=runtime_config,
        )

    def connect_session_terminal(
        self,
        *,
        session_id: str,
        terminal_id: str,
        token: str,
    ) -> dict[str, Any]:
        return self._sandbox_terminal.consume_connect_token(
            session_id=session_id,
            terminal_id=terminal_id,
            token_value=token,
        )

    def read_session_terminal_output(
        self,
        *,
        session_id: str,
        terminal_id: str,
        timeout_seconds: float = 0.2,
        max_chunks: int = 12,
    ) -> list[dict[str, str]]:
        return self._sandbox_terminal.read_output(
            session_id=session_id,
            terminal_id=terminal_id,
            timeout_seconds=timeout_seconds,
            max_chunks=max_chunks,
        )

    def write_session_terminal_input(
        self,
        *,
        session_id: str,
        terminal_id: str,
        data: str,
    ) -> None:
        self._sandbox_terminal.write_input(
            session_id=session_id,
            terminal_id=terminal_id,
            data=data,
        )

    def resize_session_terminal(
        self,
        *,
        session_id: str,
        terminal_id: str,
        cols: int,
        rows: int,
    ) -> None:
        self._sandbox_terminal.resize_terminal(
            session_id=session_id,
            terminal_id=terminal_id,
            cols=cols,
            rows=rows,
        )

    def close_session_terminal(
        self,
        *,
        session_id: str,
        terminal_id: str,
        user_id: str | None = None,
    ) -> bool:
        if user_id is not None:
            session = self.sessions.get(session_id)
            if not session or session.user_id != user_id:
                raise PermissionError("Session not found")
        return self._sandbox_terminal.close_terminal(
            session_id=session_id,
            terminal_id=terminal_id,
        )

    def get_session_sandbox(self, session_id: str) -> dict[str, Any]:
        return self._sandbox_admin.get_session_sandbox(session_id)

    def get_session_sandbox_status(
        self, session_id: str, user_id: str
    ) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if not session or session.user_id != user_id:
            raise PermissionError("Session not found")

        runtime = self._runtime_context_for_session(user_id, session_id)
        sandbox_runtime = ((runtime.get("toolkits") or {}).get("sandbox") or {}).get(
            "runtime"
        ) or {}
        sandbox_lifecycle = ((runtime.get("toolkits") or {}).get("sandbox") or {}).get(
            "lifecycle"
        ) or {}

        sandbox = self.get_session_sandbox(session_id)
        runtime_resolution = self.sandbox_lifecycle.get_session_runtime_resolution(
            session_id
        )
        resolved_runtime = dict(
            (runtime_resolution or {}).get("resolved_runtime") or {}
        )
        runtime_source = (
            "active_lease"
            if bool(sandbox.get("has_active_lease"))
            else ("resolved_runtime" if resolved_runtime else "configured_runtime")
        )
        active_runtime_template = str(
            sandbox.get("template_name") or ""
        ).strip() or str(
            resolved_runtime.get("template_name")
            or sandbox_runtime.get("template_name")
            or ""
        )
        active_runtime_namespace = str(sandbox.get("namespace") or "").strip() or str(
            resolved_runtime.get("namespace") or sandbox_runtime.get("namespace") or ""
        )
        active_runtime_profile = str(
            resolved_runtime.get("profile") or sandbox_runtime.get("profile") or ""
        )
        active_runtime_mode = str(
            resolved_runtime.get("mode") or sandbox_runtime.get("mode") or ""
        )
        active_runtime_execution_model = str(
            resolved_runtime.get("execution_model")
            or sandbox_lifecycle.get("execution_model")
            or ""
        )

        workspace_status = self.get_workspace_status(user_id)
        return {
            "session_id": session_id,
            "sandbox": sandbox,
            "sandbox_policy": dict(session.sandbox_policy or {}),
            "effective": {
                "runtime": sandbox_runtime,
                "lifecycle": sandbox_lifecycle,
            },
            "active_runtime": {
                "source": runtime_source,
                "mode": active_runtime_mode,
                "profile": active_runtime_profile,
                "template_name": active_runtime_template,
                "namespace": active_runtime_namespace,
                "execution_model": active_runtime_execution_model,
                "has_active_lease": bool(sandbox.get("has_active_lease")),
                "fallback_active": bool(
                    (runtime_resolution or {}).get("fallback_active")
                ),
                "fallback_reason_code": (runtime_resolution or {}).get(
                    "fallback_reason_code"
                ),
            },
            "runtime_resolution": runtime_resolution,
            "workspace_status": workspace_status,
            "available_sandboxes": self.list_available_sandboxes(user_id),
        }

    def perform_session_sandbox_action(
        self,
        session_id: str,
        user_id: str,
        *,
        action: str,
        wait: bool = False,
    ) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if not session or session.user_id != user_id:
            raise PermissionError("Session not found")

        normalized = str(action or "").strip().lower()
        if normalized == "release_lease":
            released = self.sandbox_lease_facade.release_session(session_id)
            return {
                "action": normalized,
                "released": released,
                "status": self.get_session_sandbox_status(session_id, user_id),
            }

        if normalized in {"reconcile_workspace", "ensure_workspace_async"}:
            workspace, started = self.ensure_workspace_async(
                user_id,
                reconcile_ready=True,
            )
            if wait:
                workspace = self.ensure_workspace(user_id)
                started = False
            return {
                "action": normalized,
                "started": started,
                "workspace": workspace,
                "status": self.get_session_sandbox_status(session_id, user_id),
            }

        if normalized == "ensure_workspace":
            workspace = self.ensure_workspace(user_id)
            return {
                "action": normalized,
                "started": False,
                "workspace": workspace,
                "status": self.get_session_sandbox_status(session_id, user_id),
            }

        raise ValueError(
            "Unsupported action. Use release_lease, reconcile_workspace, ensure_workspace_async, or ensure_workspace."
        )

    def _tool_user_id_for_session(self, session_id: str) -> str:
        session = self.sessions.get(session_id)
        if not session or not session.user_id:
            raise RuntimeError("Session not found")
        return session.user_id

    def get_session_sandbox_status_for_tools(self, session_id: str) -> dict[str, Any]:
        user_id = self._tool_user_id_for_session(session_id)
        return self.get_session_sandbox_status(session_id, user_id)

    def get_workspace_status_for_tools(self, session_id: str) -> dict[str, Any]:
        user_id = self._tool_user_id_for_session(session_id)
        return self.get_workspace_status(user_id)

    def list_available_sandboxes_for_tools(self, session_id: str) -> dict[str, Any]:
        user_id = self._tool_user_id_for_session(session_id)
        return self.list_available_sandboxes(user_id)

    def open_interactive_shell_for_tools(self, session_id: str) -> dict[str, Any]:
        user_id = self._tool_user_id_for_session(session_id)
        self._assert_authorized_feature(user_id, "terminal.open")
        return {
            "session_id": session_id,
            "open_terminal_path": f"/api/sessions/{session_id}/sandbox/terminal/open",
            "message": "Interactive shell panel is available for this session.",
        }

    def set_session_sandbox_policy_for_tools(
        self, session_id: str, policy_updates: dict[str, Any]
    ) -> dict[str, Any]:
        user_id = self._tool_user_id_for_session(session_id)
        clear = bool(policy_updates.get("clear"))
        updated = self.update_session_sandbox_policy(
            session_id,
            user_id,
            policy_updates,
            clear=clear,
        )
        updated["status"] = self.get_session_sandbox_status(session_id, user_id)
        return updated

    def release_session_sandbox_for_tools(self, session_id: str) -> dict[str, Any]:
        user_id = self._tool_user_id_for_session(session_id)
        released = self.sandbox_lease_facade.release_session(session_id)
        return {
            "released": released,
            "status": self.get_session_sandbox_status(session_id, user_id),
        }

    def reconcile_workspace_for_tools(
        self, session_id: str, *, wait: bool = False
    ) -> dict[str, Any]:
        user_id = self._tool_user_id_for_session(session_id)
        workspace, started = self.ensure_workspace_async(user_id, reconcile_ready=True)
        if wait:
            workspace = self.ensure_workspace(user_id)
            started = False
        return {
            "started": started,
            "workspace": workspace,
            "status": self.get_session_sandbox_status(session_id, user_id),
        }

    def create_share(self, session_id: str, user_id: str) -> str | None:
        return self._sharing_service.create_share(session_id, user_id)

    def get_shared_session(self, share_id: str) -> dict[str, Any] | None:
        return self._sharing_service.get_shared_session(share_id)

    def get_shared_session_markdown(self, share_id: str) -> str | None:
        return self._sharing_service.get_shared_session_markdown(share_id)

    def close(self) -> None:
        """Release background resources owned by the agent runtime."""
        self._sandbox_terminal.close_all()
        self._workspace_async_service.shutdown(wait=False, timeout_seconds=1.0)
