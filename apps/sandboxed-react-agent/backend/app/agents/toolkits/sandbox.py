import json
from typing import Any, Awaitable, Callable

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..tool_events import tool_end_event, tool_start_event
from ..tool_payloads import ToolExecutionPayload
from ..integrations.sandbox_sessions import SessionSandboxFacade


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
