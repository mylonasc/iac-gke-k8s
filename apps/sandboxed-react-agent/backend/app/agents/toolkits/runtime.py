from typing import Any

from .base import ToolRuntime


class CompositeToolRuntime:
    """Combines multiple toolkit runtimes behind one dispatch surface."""

    def __init__(self, runtimes: list[tuple[str, ToolRuntime]]) -> None:
        self._runtimes = list(runtimes)
        self._tool_to_runtime: dict[str, ToolRuntime] = {}
        self._openai_tools: list[dict[str, Any]] = []

        for toolkit_id, runtime in self._runtimes:
            for tool in runtime.get_openai_tools():
                tool_name = str(((tool.get("function") or {}).get("name")) or "")
                if not tool_name:
                    raise ValueError(
                        f"Toolkit '{toolkit_id}' exposed a tool without a name"
                    )
                if tool_name in self._tool_to_runtime:
                    raise ValueError(f"Duplicate tool name registered: {tool_name}")
                self._tool_to_runtime[tool_name] = runtime
                self._openai_tools.append(tool)

    def get_openai_tools(self) -> list[dict[str, Any]]:
        return list(self._openai_tools)

    async def run_tool_call(
        self,
        *,
        tool_call_id: str | None,
        name: str,
        arguments_json: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        runtime = self._tool_to_runtime.get(name)
        if runtime is None:
            raise ValueError(f"Unsupported tool: {name}")
        return await runtime.run_tool_call(
            tool_call_id=tool_call_id,
            name=name,
            arguments_json=arguments_json,
        )
