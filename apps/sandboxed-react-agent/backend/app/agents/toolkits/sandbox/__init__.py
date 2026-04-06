import copy
import json
from typing import Any, Awaitable, Callable

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..base import ToolkitProvider
from ...tool_events import tool_end_event, tool_start_event
from ...tool_payloads import ToolExecutionPayload
from ...integrations.sandbox_sessions import SessionSandboxFacade
from ....sandbox_lifecycle import SandboxLifecycleService
from ....sandbox_manager import SandboxManager


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
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


class SandboxToolkit:
    """Stateful sandbox toolkit that exposes LangGraph-compatible tools."""

    def __init__(
        self,
        *,
        session_sandbox: SessionSandboxFacade,
        session_id: str,
        runtime_config: dict[str, Any],
        now_iso: Callable[[], str],
        event_sink: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self.session_sandbox = session_sandbox
        self.session_id = session_id
        self.runtime_config = runtime_config
        self.now_iso = now_iso
        self.event_sink = event_sink
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
        ]
        self._tool_by_name = {tool.name: tool for tool in self._tools}

    def get_tools(self) -> list[StructuredTool]:
        return list(self._tools)

    def get_openai_tools(self) -> list[dict[str, Any]]:
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
            payload, stored_assets = self._invoke(
                name, parsed, tool_call_id=tool_call_id
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
        if name == "sandbox_exec_python":
            return self.session_sandbox.run_python(
                session_id=self.session_id,
                tool_call_id=tool_call_id,
                code=str(parsed.get("code", "")),
                runtime_config=self.runtime_config,
                created_at=self.now_iso(),
            )
        if name == "sandbox_exec_shell":
            return self.session_sandbox.run_shell(
                session_id=self.session_id,
                tool_call_id=tool_call_id,
                command=str(parsed.get("command", "")),
                runtime_config=self.runtime_config,
                created_at=self.now_iso(),
            )
        raise ValueError(f"Unsupported tool: {name}")

    def _exec_python(self, code: str) -> dict[str, Any]:
        payload, _ = self.session_sandbox.run_python(
            session_id=self.session_id,
            tool_call_id=None,
            code=code,
            runtime_config=self.runtime_config,
            created_at=self.now_iso(),
        )
        return payload.as_dict()

    def _exec_shell(self, command: str) -> dict[str, Any]:
        payload, _ = self.session_sandbox.run_shell(
            session_id=self.session_id,
            tool_call_id=None,
            command=command,
            runtime_config=self.runtime_config,
            created_at=self.now_iso(),
        )
        return payload.as_dict()

    def _error_output(self, tool_name: str, error: str) -> str:
        return ToolExecutionPayload(
            tool=tool_name,
            ok=False,
            stdout="",
            stderr="",
            exit_code=None,
            error=error,
        ).as_json()


class SandboxToolkitProvider:
    toolkit_id = "sandbox"

    def __init__(
        self,
        session_sandbox: SessionSandboxFacade,
        sandbox_manager: SandboxManager,
        sandbox_lifecycle: SandboxLifecycleService,
    ) -> None:
        self.session_sandbox = session_sandbox
        self.sandbox_manager = sandbox_manager
        self.sandbox_lifecycle = sandbox_lifecycle

    def default_config(self) -> dict[str, Any]:
        sandbox_config = self.sandbox_manager.get_config()
        sandbox_config.update(self.sandbox_lifecycle.get_config())
        return {
            "enabled": True,
            "runtime": {
                "mode": sandbox_config.get("mode", "cluster"),
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
        return _deep_merge(defaults, stored)

    def apply_updates(
        self,
        current: dict[str, Any],
        *,
        toolkit_updates: dict[str, Any] | None = None,
        legacy_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        updated = self.merge_config(current, toolkit_updates or {})
        runtime = updated.setdefault("runtime", {})
        lifecycle = updated.setdefault("lifecycle", {})
        legacy = legacy_updates or {}

        if legacy.get("sandbox_mode") is not None:
            normalized_mode = str(legacy["sandbox_mode"]).strip().lower()
            if normalized_mode not in {"cluster", "local"}:
                raise ValueError("sandbox_mode must be 'cluster' or 'local'")
            runtime["mode"] = normalized_mode
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
        return updated

    def requires_session_recycle(
        self, previous: dict[str, Any], updated: dict[str, Any]
    ) -> bool:
        previous_runtime = previous.get("runtime") or {}
        updated_runtime = updated.get("runtime") or {}
        previous_lifecycle = previous.get("lifecycle") or {}
        updated_lifecycle = updated.get("lifecycle") or {}
        return any(
            previous_runtime.get(key) != updated_runtime.get(key)
            for key in ["mode", "api_url", "template_name", "namespace", "server_port"]
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
            session_id=session_id,
            runtime_config=merged_config,
            now_iso=now_iso,
            event_sink=event_sink,
        )
