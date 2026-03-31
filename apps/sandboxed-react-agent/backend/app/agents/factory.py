from typing import Any, Awaitable, Callable

from langgraph.graph import END, StateGraph

from .state import AgentGraphState
from .toolkits.sandbox import SandboxToolkit


class AgentFactory:
    """Builds agent graphs and per-run toolkit instances."""

    def __init__(
        self,
        *,
        model_node: Callable[[AgentGraphState], Awaitable[AgentGraphState]],
        tools_node: Callable[[AgentGraphState], Awaitable[AgentGraphState]],
        route_after_model: Callable[[AgentGraphState], str],
        route_after_tools: Callable[[AgentGraphState], str],
    ) -> None:
        self.model_node = model_node
        self.tools_node = tools_node
        self.route_after_model = route_after_model
        self.route_after_tools = route_after_tools

    def build_graph(self):
        graph = StateGraph(AgentGraphState)
        graph.add_node("model", self.model_node)
        graph.add_node("tools", self.tools_node)
        graph.set_entry_point("model")
        graph.add_conditional_edges("model", self.route_after_model)
        graph.add_conditional_edges("tools", self.route_after_tools)
        return graph.compile()

    def build_sandbox_toolkit(
        self,
        *,
        session_sandbox: Any,
        session_id: str,
        runtime_config: dict[str, Any],
        now_iso: Callable[[], str],
        event_sink: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> SandboxToolkit:
        return SandboxToolkit(
            session_sandbox=session_sandbox,
            session_id=session_id,
            runtime_config=runtime_config,
            now_iso=now_iso,
            event_sink=event_sink,
        )
