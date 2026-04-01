from typing import Any, Awaitable, Protocol


class ToolRuntime(Protocol):
    def get_openai_tools(self) -> list[dict[str, Any]]: ...

    async def run_tool_call(
        self,
        *,
        tool_call_id: str | None,
        name: str,
        arguments_json: str,
    ) -> tuple[str, list[dict[str, Any]]]: ...


class ToolkitProvider(Protocol):
    toolkit_id: str

    def build_runtime(
        self,
        *,
        session_id: str,
        runtime_config: dict[str, Any],
        now_iso: Any,
        event_sink: Any = None,
    ) -> ToolRuntime: ...
