from types import SimpleNamespace

from app.agent import SandboxedReactAgent


class _CaptureTerminalService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def open_terminal(
        self,
        *,
        session_id: str,
        user_id: str,
        runtime_config: dict[str, object],
    ) -> dict[str, object]:
        self.calls.append(
            {
                "session_id": session_id,
                "user_id": user_id,
                "runtime_config": runtime_config,
            }
        )
        return {"terminal_id": "term-1"}


def test_open_session_terminal_flattens_runtime_and_lifecycle() -> None:
    terminal_service = _CaptureTerminalService()
    agent = SandboxedReactAgent.__new__(SandboxedReactAgent)
    agent.sessions = {"session-1": SimpleNamespace(user_id="user-1")}
    agent._sandbox_terminal = terminal_service
    agent._runtime_context_for_session = lambda _user_id, _session_id: {
        "agent": {"model": "gpt-4o-mini"},
        "toolkits": {
            "sandbox": {
                "runtime": {
                    "mode": "cluster",
                    "profile": "persistent_workspace",
                    "api_url": "http://host.docker.internal:18080",
                    "template_name": "python-runtime-template-small",
                    "namespace": "alt-default",
                },
                "lifecycle": {
                    "execution_model": "session",
                    "session_idle_ttl_seconds": 1800,
                },
            }
        },
    }

    opened = agent.open_session_terminal("session-1", "user-1")

    assert opened["terminal_id"] == "term-1"
    assert terminal_service.calls == [
        {
            "session_id": "session-1",
            "user_id": "user-1",
            "runtime_config": {
                "mode": "cluster",
                "profile": "persistent_workspace",
                "api_url": "http://host.docker.internal:18080",
                "template_name": "python-runtime-template-small",
                "namespace": "alt-default",
                "execution_model": "session",
                "session_idle_ttl_seconds": 1800,
            },
        }
    ]
