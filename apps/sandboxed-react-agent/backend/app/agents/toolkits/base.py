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

    def default_config(self) -> dict[str, Any]: ...

    def merge_config(
        self, defaults: dict[str, Any], stored: dict[str, Any]
    ) -> dict[str, Any]: ...

    def apply_updates(
        self,
        current: dict[str, Any],
        *,
        toolkit_updates: dict[str, Any] | None = None,
        legacy_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def requires_session_recycle(
        self, previous: dict[str, Any], updated: dict[str, Any]
    ) -> bool: ...

    def build_runtime(
        self,
        *,
        session_id: str,
        runtime_config: dict[str, Any],
        now_iso: Any,
        event_sink: Any = None,
    ) -> ToolRuntime: ...
