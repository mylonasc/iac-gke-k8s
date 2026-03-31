import json
from types import SimpleNamespace

from app.agents.integrations.sandbox_sessions import SessionSandboxFacade
from app.agents.toolkits.sandbox import SandboxToolkit


class _FakeLeaseFacade:
    def __init__(self) -> None:
        self.python_calls: list[tuple[str, str, dict[str, object] | None]] = []
        self.shell_calls: list[tuple[str, str, dict[str, object] | None]] = []

    def exec_python_for_session(
        self,
        session_id: str,
        code: str,
        *,
        runtime_config: dict[str, object] | None = None,
    ):
        self.python_calls.append((session_id, code, runtime_config))
        return SimpleNamespace(
            tool_name="sandbox_exec_python",
            ok=True,
            stdout="python ok",
            stderr="",
            exit_code=0,
            error=None,
            lease_id="lease-1",
            claim_name="claim-1",
            assets=[
                {
                    "filename": "plot.png",
                    "mime_type": "image/png",
                    "base64": "ZmFrZQ==",
                }
            ],
        )

    def exec_shell_for_session(
        self,
        session_id: str,
        command: str,
        *,
        runtime_config: dict[str, object] | None = None,
    ):
        self.shell_calls.append((session_id, command, runtime_config))
        return SimpleNamespace(
            tool_name="sandbox_exec_shell",
            ok=True,
            stdout="shell ok",
            stderr="",
            exit_code=0,
            error=None,
            lease_id="lease-2",
            claim_name="claim-2",
            assets=[],
        )


class _FakeAssetFacade:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, list[dict[str, str]] | None, str]] = []

    def store_execution_assets(
        self,
        *,
        session_id: str,
        tool_call_id: str | None,
        assets: list[dict[str, str]] | None,
        created_at: str,
    ) -> list[dict[str, str]]:
        self.calls.append((session_id, tool_call_id, assets, created_at))
        if not assets:
            return []
        return [
            {
                "asset_id": "asset-1",
                "filename": assets[0]["filename"],
                "mime_type": assets[0]["mime_type"],
                "view_url": "/api/assets/asset-1",
                "download_url": "/api/assets/asset-1/download",
            }
        ]


def test_session_sandbox_facade_runs_python_and_persists_assets() -> None:
    lease_facade = _FakeLeaseFacade()
    asset_facade = _FakeAssetFacade()
    facade = SessionSandboxFacade(lease_facade, asset_facade)

    payload, stored_assets = facade.run_python(
        session_id="session-1",
        tool_call_id="tool-1",
        code="print('hi')",
        runtime_config={"mode": "local"},
        created_at="2026-01-01T00:00:00+00:00",
    )

    assert lease_facade.python_calls == [
        ("session-1", "print('hi')", {"mode": "local"})
    ]
    assert asset_facade.calls[0][0] == "session-1"
    assert asset_facade.calls[0][1] == "tool-1"
    assert payload.tool == "sandbox_exec_python"
    assert payload.ok is True
    assert payload.assets[0].view_url == "/api/assets/asset-1"
    assert stored_assets[0]["asset_id"] == "asset-1"


def test_sandbox_toolkit_emits_events_and_routes_shell_calls() -> None:
    lease_facade = _FakeLeaseFacade()
    asset_facade = _FakeAssetFacade()
    session_sandbox = SessionSandboxFacade(lease_facade, asset_facade)
    events: list[dict[str, object]] = []

    async def _event_sink(event: dict[str, object]) -> None:
        events.append(event)

    toolkit = SandboxToolkit(
        session_sandbox=session_sandbox,
        session_id="session-2",
        runtime_config={"mode": "local"},
        now_iso=lambda: "2026-01-01T00:00:00+00:00",
        event_sink=_event_sink,
    )

    payload_json, stored_assets = __import__("asyncio").run(
        toolkit.run_tool_call(
            tool_call_id="tool-2",
            name="sandbox_exec_shell",
            arguments_json=json.dumps({"command": "pwd"}),
        )
    )

    payload = json.loads(payload_json)
    assert lease_facade.shell_calls == [("session-2", "pwd", {"mode": "local"})]
    assert payload["tool"] == "sandbox_exec_shell"
    assert payload["ok"] is True
    assert stored_assets == []
    assert [event["phase"] for event in events] == ["start", "end"]
    assert events[0]["tool_name"] == "sandbox_exec_shell"
    assert events[1]["result"]["stdout"] == "shell ok"


def test_sandbox_toolkit_exposes_openai_tool_schemas() -> None:
    toolkit = SandboxToolkit(
        session_sandbox=SessionSandboxFacade(_FakeLeaseFacade(), _FakeAssetFacade()),
        session_id="session-3",
        runtime_config={"mode": "local"},
        now_iso=lambda: "2026-01-01T00:00:00+00:00",
    )

    tools = toolkit.get_openai_tools()

    assert [tool["function"]["name"] for tool in tools] == [
        "sandbox_exec_python",
        "sandbox_exec_shell",
    ]
    assert tools[0]["function"]["parameters"]["required"] == ["code"]
    assert tools[1]["function"]["parameters"]["required"] == ["command"]
