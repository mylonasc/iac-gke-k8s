import asyncio
import copy
import json
import time
from contextlib import nullcontext
from typing import Any, Awaitable, Callable

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..base import ToolkitProvider
from ...tool_events import tool_end_event, tool_start_event
from ...tool_payloads import ToolExecutionPayload
from ...integrations.sandbox_sessions import SessionSandboxFacade
from ....public_path import with_public_base
from ....sandbox_lifecycle import SandboxLifecycleService
from ....sandbox_manager import SandboxManager


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge nested dictionaries while skipping ``None`` updates.

    Args:
        base: Base dictionary.
        updates: Update dictionary.

    Returns:
        Merged dictionary copy.
    """
    merged = copy.deepcopy(base)
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged.get(key) or {}), value)
        else:
            merged[key] = value
    return merged


class SandboxExecPythonInput(BaseModel):
    code: str = Field(
        description=(
            "Python code to execute. REQUIRED: after creating any image/file you want "
            "in chat, call expose_asset('/absolute/or/relative/path'). For HTML/JS widgets "
            "call expose_asset(path, mime_type='text/html')."
        )
    )


class SandboxExecShellInput(BaseModel):
    command: str = Field(
        description=(
            "Shell command to execute. If files are created, run a python helper that calls "
            "expose_asset(path) so assets are available to API/UI. Use mime_type='text/html' "
            "for HTML widget previews."
        )
    )


class SandboxNoArgsInput(BaseModel):
    pass


class SandboxSetSessionPolicyInput(BaseModel):
    clear: bool = False
    mode: str | None = None
    profile: str | None = None
    template_name: str | None = None
    namespace: str | None = None
    execution_model: str | None = None
    session_idle_ttl_seconds: int | None = Field(default=None, ge=1, le=86400)


class SandboxReconcileWorkspaceInput(BaseModel):
    wait: bool = False


class SandboxWaitWorkspaceReadyInput(BaseModel):
    timeout_seconds: int = Field(default=90, ge=5, le=900)
    poll_interval_seconds: int = Field(default=3, ge=1, le=30)


class SandboxToolkit:
    """Stateful sandbox toolkit that exposes LangGraph-compatible tools."""

    def __init__(
        self,
        *,
        session_sandbox: SessionSandboxFacade,
        session_id: str,
        runtime_config: dict[str, Any],
        now_iso: Callable[[], str],
        sandbox_lifecycle: SandboxLifecycleService | None = None,
        event_sink: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        get_session_status: Callable[[str], dict[str, Any]] | None = None,
        get_workspace_status: Callable[[str], dict[str, Any]] | None = None,
        list_available_sandboxes: Callable[[str], dict[str, Any]] | None = None,
        set_session_policy: Callable[[str, dict[str, Any]], dict[str, Any]]
        | None = None,
        release_session_lease: Callable[[str], dict[str, Any]] | None = None,
        reconcile_workspace: Callable[[str, bool], dict[str, Any]] | None = None,
        open_interactive_shell: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        """Initialize toolkit runtime wrapper.

        Args:
            session_sandbox: Session-aware execution facade.
            session_id: Current session identifier.
            runtime_config: Effective sandbox runtime configuration.
            now_iso: Callable providing current timestamp.
            sandbox_lifecycle: Optional lifecycle service for sandbox progress events.
            event_sink: Optional async sink for tool start/end events.
            get_session_status: Optional callback for session sandbox status.
            get_workspace_status: Optional callback for workspace status.
            list_available_sandboxes: Optional callback for available templates.
            set_session_policy: Optional callback to update session sandbox policy.
            release_session_lease: Optional callback to release current session lease.
            reconcile_workspace: Optional callback to reconcile/ensure workspace.
            open_interactive_shell: Optional callback to expose interactive shell hint.
        """
        self.session_sandbox = session_sandbox
        self.sandbox_lifecycle = sandbox_lifecycle
        self.session_id = session_id
        self.runtime_config = runtime_config
        self.now_iso = now_iso
        self.event_sink = event_sink
        self.get_session_status = get_session_status
        self.get_workspace_status = get_workspace_status
        self.list_available_sandboxes = list_available_sandboxes
        self.set_session_policy = set_session_policy
        self.release_session_lease = release_session_lease
        self.reconcile_workspace = reconcile_workspace
        self.open_interactive_shell = open_interactive_shell
        self._tools = [
            StructuredTool.from_function(
                func=self._exec_python,
                name="sandbox_exec_python",
                description="Run Python code in an isolated Agent Sandbox runtime.",
                args_schema=SandboxExecPythonInput,
            ),
            StructuredTool.from_function(
                func=self._exec_shell,
                name="sandbox_exec_shell",
                description="Run a shell command in an isolated Agent Sandbox runtime.",
                args_schema=SandboxExecShellInput,
            ),
            StructuredTool.from_function(
                func=self._get_session_status,
                name="sandbox_get_session_status",
                description="Get effective sandbox policy, lease status, and workspace state for this session.",
                args_schema=SandboxNoArgsInput,
            ),
            StructuredTool.from_function(
                func=self._get_workspace_status,
                name="sandbox_get_workspace_status",
                description="Get persistent workspace provisioning status and active session leases for this user.",
                args_schema=SandboxNoArgsInput,
            ),
            StructuredTool.from_function(
                func=self._list_available_sandboxes,
                name="sandbox_list_available_sandboxes",
                description="List available sandbox profiles, execution models, and templates.",
                args_schema=SandboxNoArgsInput,
            ),
            StructuredTool.from_function(
                func=self._set_session_policy,
                name="sandbox_set_session_policy",
                description="Mutate this session's sandbox policy (profile/template/execution model) explicitly.",
                args_schema=SandboxSetSessionPolicyInput,
            ),
            StructuredTool.from_function(
                func=self._release_session_lease,
                name="sandbox_release_session_lease",
                description="Release the active sandbox lease for this session.",
                args_schema=SandboxNoArgsInput,
            ),
            StructuredTool.from_function(
                func=self._reconcile_workspace,
                name="sandbox_reconcile_workspace",
                description="Start or run workspace reconciliation/provisioning for this user.",
                args_schema=SandboxReconcileWorkspaceInput,
            ),
            StructuredTool.from_function(
                func=self._wait_for_workspace_ready,
                name="sandbox_wait_for_workspace_ready",
                description="Poll workspace state until ready, error, or timeout.",
                args_schema=SandboxWaitWorkspaceReadyInput,
            ),
            StructuredTool.from_function(
                func=self._open_interactive_shell,
                name="sandbox_open_interactive_shell",
                description=(
                    "Open an interactive shell panel for this session's sandbox in the UI."
                ),
                args_schema=SandboxNoArgsInput,
            ),
        ]
        self._tool_by_name = {tool.name: tool for tool in self._tools}

    def get_tools(self) -> list[StructuredTool]:
        """Return LangChain structured tools.

        Returns:
            Structured tool list.
        """
        return list(self._tools)

    def get_openai_tools(self) -> list[dict[str, Any]]:
        """Return OpenAI tool schema list.

        Returns:
            Tool definitions in OpenAI function-calling format.
        """
        schemas: list[dict[str, Any]] = []
        for tool in self._tools:
            schema = tool.args_schema.model_json_schema()
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": {
                            "type": "object",
                            "properties": dict(schema.get("properties") or {}),
                            "required": list(schema.get("required") or []),
                        },
                    },
                }
            )
        return schemas

    async def run_tool_call(
        self,
        *,
        tool_call_id: str | None,
        name: str,
        arguments_json: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Execute one tool call with serialized payload output.

        Args:
            tool_call_id: Optional tool call identifier.
            name: Tool name.
            arguments_json: Tool argument payload as JSON string.

        Returns:
            Tuple of serialized tool payload and persisted asset records.
        """
        try:
            parsed = json.loads(arguments_json or "{}")
        except json.JSONDecodeError as exc:
            return self._error_output(
                name, f"Invalid tool arguments JSON: {exc.msg}"
            ), []

        if not isinstance(parsed, dict):
            return self._error_output(name, "Invalid tool arguments payload type"), []

        if self.event_sink is not None:
            await self.event_sink(
                tool_start_event(
                    tool_call_id or "",
                    name,
                    arguments_json,
                )
            )

        try:
            payload, stored_assets = await asyncio.to_thread(
                self._invoke,
                name,
                parsed,
                tool_call_id=tool_call_id,
            )
        except Exception as exc:
            payload = ToolExecutionPayload(
                tool=name,
                ok=False,
                stdout="",
                stderr="",
                exit_code=None,
                error=f"Tool execution failed: {exc}",
            )
            stored_assets = []

        if self.event_sink is not None:
            await self.event_sink(
                tool_end_event(
                    tool_call_id=tool_call_id or "",
                    tool_name=name,
                    args_text=arguments_json,
                    args=parsed,
                    result=payload.as_dict(),
                    is_error=not payload.ok,
                    stored_assets=stored_assets,
                )
            )
        return payload.as_json(), stored_assets

    def _invoke(
        self, name: str, parsed: dict[str, Any], *, tool_call_id: str | None
    ) -> tuple[ToolExecutionPayload, list[dict[str, Any]]]:
        """Dispatch parsed tool request to concrete execution facade.

        Args:
            name: Tool name.
            parsed: Parsed argument object.
            tool_call_id: Optional tool call identifier.

        Returns:
            Execution payload and persisted assets.

        Raises:
            ValueError: If the tool name is not supported.
        """
        if name == "sandbox_exec_python":
            listener = self._sandbox_progress_listener()
            listener_context = (
                self.sandbox_lifecycle.bind_progress_listener(listener)
                if self.sandbox_lifecycle is not None
                else nullcontext()
            )
            with listener_context:
                return self.session_sandbox.run_python(
                    session_id=self.session_id,
                    tool_call_id=tool_call_id,
                    code=str(parsed.get("code", "")),
                    runtime_config=self.runtime_config,
                    created_at=self.now_iso(),
                )
        if name == "sandbox_exec_shell":
            listener = self._sandbox_progress_listener()
            listener_context = (
                self.sandbox_lifecycle.bind_progress_listener(listener)
                if self.sandbox_lifecycle is not None
                else nullcontext()
            )
            with listener_context:
                return self.session_sandbox.run_shell(
                    session_id=self.session_id,
                    tool_call_id=tool_call_id,
                    command=str(parsed.get("command", "")),
                    runtime_config=self.runtime_config,
                    created_at=self.now_iso(),
                )
        if name == "sandbox_get_session_status":
            return self._payload_only(self._get_session_status())
        if name == "sandbox_get_workspace_status":
            return self._payload_only(self._get_workspace_status())
        if name == "sandbox_list_available_sandboxes":
            return self._payload_only(self._list_available_sandboxes())
        if name == "sandbox_set_session_policy":
            return self._payload_only(
                self._set_session_policy(
                    clear=bool(parsed.get("clear", False)),
                    mode=parsed.get("mode"),
                    profile=parsed.get("profile"),
                    template_name=parsed.get("template_name"),
                    namespace=parsed.get("namespace"),
                    execution_model=parsed.get("execution_model"),
                    session_idle_ttl_seconds=parsed.get("session_idle_ttl_seconds"),
                )
            )
        if name == "sandbox_release_session_lease":
            return self._payload_only(self._release_session_lease())
        if name == "sandbox_reconcile_workspace":
            return self._payload_only(
                self._reconcile_workspace(wait=bool(parsed.get("wait", False)))
            )
        if name == "sandbox_wait_for_workspace_ready":
            return self._payload_only(
                self._wait_for_workspace_ready(
                    timeout_seconds=int(parsed.get("timeout_seconds", 90)),
                    poll_interval_seconds=int(parsed.get("poll_interval_seconds", 3)),
                )
            )
        if name == "sandbox_open_interactive_shell":
            return self._payload_only(self._open_interactive_shell())
        raise ValueError(f"Unsupported tool: {name}")

    def _sandbox_progress_listener(self) -> Callable[[dict[str, Any]], None] | None:
        if self.event_sink is None:
            return None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return None

        def _listener(event: dict[str, Any]) -> None:
            if self.event_sink is None:
                return
            future = asyncio.run_coroutine_threadsafe(self.event_sink(event), loop)

            def _consume_exception(done_future) -> None:
                try:
                    done_future.result()
                except Exception:
                    return

            future.add_done_callback(_consume_exception)

        return _listener

    def _exec_python(self, code: str) -> dict[str, Any]:
        """LangChain adapter for Python tool execution.

        Args:
            code: Python source code.

        Returns:
            Tool payload dictionary.
        """
        payload, _ = self.session_sandbox.run_python(
            session_id=self.session_id,
            tool_call_id=None,
            code=code,
            runtime_config=self.runtime_config,
            created_at=self.now_iso(),
        )
        return payload.as_dict()

    def _exec_shell(self, command: str) -> dict[str, Any]:
        """LangChain adapter for shell tool execution.

        Args:
            command: Shell command string.

        Returns:
            Tool payload dictionary.
        """
        payload, _ = self.session_sandbox.run_shell(
            session_id=self.session_id,
            tool_call_id=None,
            command=command,
            runtime_config=self.runtime_config,
            created_at=self.now_iso(),
        )
        return payload.as_dict()

    def _payload_only(
        self, payload: ToolExecutionPayload
    ) -> tuple[ToolExecutionPayload, list[dict[str, Any]]]:
        return payload, []

    def _ok_payload(
        self,
        tool_name: str,
        data: dict[str, Any],
        *,
        message: str = "",
    ) -> ToolExecutionPayload:
        return ToolExecutionPayload(
            tool=tool_name,
            ok=True,
            stdout=message or json.dumps(data, ensure_ascii=True),
            stderr="",
            exit_code=0,
            data=data,
        )

    def _error_payload(self, tool_name: str, error: str) -> ToolExecutionPayload:
        return ToolExecutionPayload(
            tool=tool_name,
            ok=False,
            stdout="",
            stderr="",
            exit_code=None,
            error=error,
        )

    def _get_session_status(self) -> ToolExecutionPayload:
        tool_name = "sandbox_get_session_status"
        if self.get_session_status is None:
            return self._error_payload(
                tool_name, "Session status callback is not configured"
            )
        try:
            status = self.get_session_status(self.session_id)
            return self._ok_payload(tool_name, status)
        except Exception as exc:
            return self._error_payload(tool_name, str(exc))

    def _get_workspace_status(self) -> ToolExecutionPayload:
        tool_name = "sandbox_get_workspace_status"
        if self.get_workspace_status is None:
            return self._error_payload(
                tool_name, "Workspace status callback is not configured"
            )
        try:
            status = self.get_workspace_status(self.session_id)
            return self._ok_payload(tool_name, status)
        except Exception as exc:
            return self._error_payload(tool_name, str(exc))

    def _list_available_sandboxes(self) -> ToolExecutionPayload:
        tool_name = "sandbox_list_available_sandboxes"
        if self.list_available_sandboxes is None:
            return self._error_payload(
                tool_name, "Available sandbox callback is not configured"
            )
        try:
            status = self.list_available_sandboxes(self.session_id)
            return self._ok_payload(tool_name, status)
        except Exception as exc:
            return self._error_payload(tool_name, str(exc))

    def _set_session_policy(
        self,
        *,
        clear: bool = False,
        mode: str | None = None,
        profile: str | None = None,
        template_name: str | None = None,
        namespace: str | None = None,
        execution_model: str | None = None,
        session_idle_ttl_seconds: int | None = None,
    ) -> ToolExecutionPayload:
        tool_name = "sandbox_set_session_policy"
        if self.set_session_policy is None:
            return self._error_payload(
                tool_name, "Session policy callback is not configured"
            )
        updates = {
            "clear": clear,
            "mode": mode,
            "profile": profile,
            "template_name": template_name,
            "namespace": namespace,
            "execution_model": execution_model,
            "session_idle_ttl_seconds": session_idle_ttl_seconds,
        }
        updates = {k: v for k, v in updates.items() if v is not None or k == "clear"}
        try:
            result = self.set_session_policy(self.session_id, updates)
            return self._ok_payload(
                tool_name, result, message="Session sandbox policy updated."
            )
        except Exception as exc:
            return self._error_payload(tool_name, str(exc))

    def _release_session_lease(self) -> ToolExecutionPayload:
        tool_name = "sandbox_release_session_lease"
        if self.release_session_lease is None:
            return self._error_payload(
                tool_name, "Session release callback is not configured"
            )
        try:
            result = self.release_session_lease(self.session_id)
            return self._ok_payload(
                tool_name, result, message="Session lease release requested."
            )
        except Exception as exc:
            return self._error_payload(tool_name, str(exc))

    def _reconcile_workspace(self, *, wait: bool = False) -> ToolExecutionPayload:
        tool_name = "sandbox_reconcile_workspace"
        if self.reconcile_workspace is None:
            return self._error_payload(
                tool_name, "Workspace reconcile callback is not configured"
            )
        try:
            result = self.reconcile_workspace(self.session_id, wait)
            return self._ok_payload(
                tool_name, result, message="Workspace reconcile requested."
            )
        except Exception as exc:
            return self._error_payload(tool_name, str(exc))

    def _wait_for_workspace_ready(
        self,
        *,
        timeout_seconds: int = 90,
        poll_interval_seconds: int = 3,
    ) -> ToolExecutionPayload:
        tool_name = "sandbox_wait_for_workspace_ready"
        if self.get_workspace_status is None:
            return self._error_payload(
                tool_name, "Workspace status callback is not configured"
            )

        deadline = time.time() + max(1, int(timeout_seconds))
        interval = max(1, int(poll_interval_seconds))
        latest: dict[str, Any] = {}

        while time.time() < deadline:
            try:
                latest = self.get_workspace_status(self.session_id)
            except Exception as exc:
                return self._error_payload(tool_name, str(exc))

            workspace = latest.get("workspace") if isinstance(latest, dict) else None
            status = str((workspace or {}).get("status") or "")
            if status == "ready":
                return self._ok_payload(
                    tool_name, latest, message="Workspace is ready."
                )
            if status == "error":
                return self._error_payload(
                    tool_name,
                    str(
                        (workspace or {}).get("last_error")
                        or "workspace provisioning failed"
                    ),
                )
            time.sleep(interval)

        return self._error_payload(
            tool_name,
            f"Timed out waiting for workspace readiness after {timeout_seconds}s",
        )

    def _open_interactive_shell(self) -> ToolExecutionPayload:
        tool_name = "sandbox_open_interactive_shell"
        if self.open_interactive_shell is not None:
            try:
                payload = self.open_interactive_shell(self.session_id)
                return self._ok_payload(
                    tool_name,
                    payload,
                    message="Interactive shell is available in the session panel.",
                )
            except Exception as exc:
                return self._error_payload(tool_name, str(exc))

        payload = {
            "session_id": self.session_id,
            "open_terminal_path": with_public_base(
                f"/api/sessions/{self.session_id}/sandbox/terminal/open"
            ),
            "message": "Interactive shell is available in the session panel.",
        }
        return self._ok_payload(
            tool_name,
            payload,
            message="Interactive shell is available in the session panel.",
        )

    def _error_output(self, tool_name: str, error: str) -> str:
        """Build serialized error payload for tool-level validation errors.

        Args:
            tool_name: Tool name.
            error: Error message.

        Returns:
            JSON-serialized tool execution payload.
        """
        return ToolExecutionPayload(
            tool=tool_name,
            ok=False,
            stdout="",
            stderr="",
            exit_code=None,
            error=error,
        ).as_json()


class SandboxToolkitProvider:
    """Toolkit provider that owns sandbox runtime config normalization."""

    toolkit_id = "sandbox"

    def __init__(
        self,
        session_sandbox: SessionSandboxFacade,
        sandbox_manager: SandboxManager,
        sandbox_lifecycle: SandboxLifecycleService,
        allow_local_mode: bool = False,
        get_session_status: Callable[[str], dict[str, Any]] | None = None,
        get_workspace_status: Callable[[str], dict[str, Any]] | None = None,
        list_available_sandboxes: Callable[[str], dict[str, Any]] | None = None,
        set_session_policy: Callable[[str, dict[str, Any]], dict[str, Any]]
        | None = None,
        release_session_lease: Callable[[str], dict[str, Any]] | None = None,
        reconcile_workspace: Callable[[str, bool], dict[str, Any]] | None = None,
        open_interactive_shell: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        """Initialize provider dependencies.

        Args:
            session_sandbox: Session sandbox facade.
            sandbox_manager: Runtime execution manager.
            sandbox_lifecycle: Lease lifecycle service.
            allow_local_mode: Whether local mode can be selected by users.
            get_session_status: Optional session status callback.
            get_workspace_status: Optional workspace status callback.
            list_available_sandboxes: Optional available sandbox callback.
            set_session_policy: Optional session policy mutation callback.
            release_session_lease: Optional lease release callback.
            reconcile_workspace: Optional workspace reconcile callback.
            open_interactive_shell: Optional interactive shell callback.
        """
        self.session_sandbox = session_sandbox
        self.sandbox_manager = sandbox_manager
        self.sandbox_lifecycle = sandbox_lifecycle
        self.allow_local_mode = allow_local_mode
        self.get_session_status = get_session_status
        self.get_workspace_status = get_workspace_status
        self.list_available_sandboxes = list_available_sandboxes
        self.set_session_policy = set_session_policy
        self.release_session_lease = release_session_lease
        self.reconcile_workspace = reconcile_workspace
        self.open_interactive_shell = open_interactive_shell

    def _normalize_mode(self, value: Any) -> str:
        """Validate and normalize runtime mode value.

        Args:
            value: Raw mode value.

        Returns:
            Normalized mode.

        Raises:
            ValueError: If mode is invalid.
        """
        normalized = str(value or "cluster").strip().lower()
        if normalized not in {"cluster", "local"}:
            raise ValueError("sandbox_mode must be 'cluster' or 'local'")
        if normalized == "local" and not self.allow_local_mode:
            return "cluster"
        return normalized

    def _normalize_profile(self, value: Any) -> str:
        """Validate and normalize sandbox profile value.

        Args:
            value: Raw profile value.

        Returns:
            Normalized profile.

        Raises:
            ValueError: If profile is invalid.
        """
        normalized = str(value or "persistent_workspace").strip().lower()
        if normalized not in {"persistent_workspace", "transient"}:
            raise ValueError(
                "sandbox_profile must be 'persistent_workspace' or 'transient'"
            )
        return normalized

    def default_config(self) -> dict[str, Any]:
        """Build default toolkit config from runtime services.

        Returns:
            Default toolkit configuration object.
        """
        sandbox_config = self.sandbox_manager.get_config()
        sandbox_config.update(self.sandbox_lifecycle.get_config())
        return {
            "enabled": True,
            "runtime": {
                "mode": self._normalize_mode(sandbox_config.get("mode", "cluster")),
                "profile": self._normalize_profile(
                    sandbox_config.get("profile", "persistent_workspace")
                ),
                "api_url": sandbox_config.get("api_url", ""),
                "template_name": sandbox_config.get(
                    "template_name", "python-runtime-template-small"
                ),
                "namespace": sandbox_config.get("namespace", "alt-default"),
                "server_port": int(sandbox_config.get("server_port", 8888)),
                "max_output_chars": int(sandbox_config.get("max_output_chars", 6000)),
                "local_timeout_seconds": int(
                    sandbox_config.get("local_timeout_seconds", 20)
                ),
            },
            "lifecycle": {
                "execution_model": sandbox_config.get("execution_model", "session"),
                "session_idle_ttl_seconds": int(
                    sandbox_config.get("session_idle_ttl_seconds", 1800)
                ),
                "sandbox_ready_timeout": int(
                    sandbox_config.get("sandbox_ready_timeout", 420)
                ),
                "gateway_ready_timeout": int(
                    sandbox_config.get("gateway_ready_timeout", 180)
                ),
                "max_lease_ttl_seconds": int(
                    sandbox_config.get("max_lease_ttl_seconds", 21600)
                ),
            },
        }

    def merge_config(
        self, defaults: dict[str, Any], stored: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge stored toolkit config with defaults and normalize values.

        Args:
            defaults: Default config values.
            stored: Persisted user config values.

        Returns:
            Merged and normalized config.
        """
        merged = _deep_merge(defaults, stored)
        runtime = merged.setdefault("runtime", {})
        runtime["mode"] = self._normalize_mode(runtime.get("mode", "cluster"))
        runtime["profile"] = self._normalize_profile(
            runtime.get("profile", "persistent_workspace")
        )
        return merged

    def apply_updates(
        self,
        current: dict[str, Any],
        *,
        toolkit_updates: dict[str, Any] | None = None,
        legacy_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Apply toolkit and legacy config updates with validation.

        Args:
            current: Current toolkit config.
            toolkit_updates: Toolkit-scoped partial updates.
            legacy_updates: Legacy flat updates from older API schema.

        Returns:
            Updated toolkit config.

        Raises:
            ValueError: If any supplied value fails validation.
        """
        updated = self.merge_config(current, toolkit_updates or {})
        runtime = updated.setdefault("runtime", {})
        lifecycle = updated.setdefault("lifecycle", {})
        legacy = legacy_updates or {}

        if legacy.get("sandbox_mode") is not None:
            runtime["mode"] = self._normalize_mode(legacy["sandbox_mode"])
        if legacy.get("sandbox_profile") is not None:
            runtime["profile"] = self._normalize_profile(legacy["sandbox_profile"])
        if legacy.get("sandbox_api_url") is not None:
            runtime["api_url"] = legacy["sandbox_api_url"]
        if legacy.get("sandbox_template_name") is not None:
            runtime["template_name"] = legacy["sandbox_template_name"]
        if legacy.get("sandbox_namespace") is not None:
            runtime["namespace"] = legacy["sandbox_namespace"]
        if legacy.get("sandbox_server_port") is not None:
            if int(legacy["sandbox_server_port"]) <= 0:
                raise ValueError("sandbox_server_port must be > 0")
            runtime["server_port"] = int(legacy["sandbox_server_port"])
        if legacy.get("sandbox_max_output_chars") is not None:
            if int(legacy["sandbox_max_output_chars"]) < 100:
                raise ValueError("sandbox_max_output_chars must be >= 100")
            runtime["max_output_chars"] = int(legacy["sandbox_max_output_chars"])
        if legacy.get("sandbox_local_timeout_seconds") is not None:
            if int(legacy["sandbox_local_timeout_seconds"]) <= 0:
                raise ValueError("sandbox_local_timeout_seconds must be > 0")
            runtime["local_timeout_seconds"] = int(
                legacy["sandbox_local_timeout_seconds"]
            )
        if legacy.get("sandbox_execution_model") is not None:
            normalized_model = str(legacy["sandbox_execution_model"]).strip().lower()
            if normalized_model not in {"ephemeral", "session"}:
                raise ValueError(
                    "sandbox_execution_model must be 'ephemeral' or 'session'"
                )
            lifecycle["execution_model"] = normalized_model
        if legacy.get("sandbox_session_idle_ttl_seconds") is not None:
            if int(legacy["sandbox_session_idle_ttl_seconds"]) <= 0:
                raise ValueError("sandbox_session_idle_ttl_seconds must be > 0")
            lifecycle["session_idle_ttl_seconds"] = int(
                legacy["sandbox_session_idle_ttl_seconds"]
            )
        runtime["mode"] = self._normalize_mode(runtime.get("mode", "cluster"))
        runtime["profile"] = self._normalize_profile(
            runtime.get("profile", "persistent_workspace")
        )
        return updated

    def requires_session_recycle(
        self, previous: dict[str, Any], updated: dict[str, Any]
    ) -> bool:
        """Determine if session runtime must be rebuilt after config change.

        Args:
            previous: Previous toolkit config.
            updated: Updated toolkit config.

        Returns:
            ``True`` if sessions should recycle runtime instances.
        """
        previous_runtime = previous.get("runtime") or {}
        updated_runtime = updated.get("runtime") or {}
        previous_lifecycle = previous.get("lifecycle") or {}
        updated_lifecycle = updated.get("lifecycle") or {}
        return any(
            previous_runtime.get(key) != updated_runtime.get(key)
            for key in [
                "mode",
                "profile",
                "api_url",
                "template_name",
                "namespace",
                "server_port",
            ]
        ) or (
            previous_lifecycle.get("execution_model")
            != updated_lifecycle.get("execution_model")
        )

    def build_runtime(
        self,
        *,
        session_id: str,
        runtime_config: dict[str, Any],
        now_iso: Callable[[], str],
        event_sink: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> SandboxToolkit:
        """Build session-scoped ``SandboxToolkit`` from resolved app config.

        Args:
            session_id: Session identifier.
            runtime_config: Full resolved runtime config document.
            now_iso: Timestamp provider.
            event_sink: Optional async event sink.

        Returns:
            Configured sandbox toolkit instance.
        """
        sandbox_config = (
            (runtime_config.get("toolkits") or {}).get("sandbox") or {}
        ).get("runtime") or {}
        sandbox_lifecycle = (
            (runtime_config.get("toolkits") or {}).get("sandbox") or {}
        ).get("lifecycle") or {}
        merged_config = dict(sandbox_config)
        merged_config.update(sandbox_lifecycle)
        return SandboxToolkit(
            session_sandbox=self.session_sandbox,
            sandbox_lifecycle=self.sandbox_lifecycle,
            session_id=session_id,
            runtime_config=merged_config,
            now_iso=now_iso,
            event_sink=event_sink,
            get_session_status=self.get_session_status,
            get_workspace_status=self.get_workspace_status,
            list_available_sandboxes=self.list_available_sandboxes,
            set_session_policy=self.set_session_policy,
            release_session_lease=self.release_session_lease,
            reconcile_workspace=self.reconcile_workspace,
            open_interactive_shell=self.open_interactive_shell,
        )
