import os
from pathlib import Path
import shutil
import json

from fastapi.testclient import TestClient

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("SESSION_STORE_PATH", "/tmp/sandboxed-react-agent-test.db")
os.environ.setdefault("ASSET_STORE_PATH", "/tmp/sandboxed-react-agent-assets")

Path(os.environ["SESSION_STORE_PATH"]).unlink(missing_ok=True)

from app.main import agent, app


client = TestClient(app)


def setup_function() -> None:
    agent.sessions.clear()
    with agent.session_store._connect() as connection:
        connection.execute("DELETE FROM sessions")
        connection.execute("DELETE FROM assets")
    shutil.rmtree(os.environ["ASSET_STORE_PATH"], ignore_errors=True)


def test_config_roundtrip() -> None:
    response = client.get("/api/config")
    assert response.status_code == 200
    payload = response.json()
    assert "model" in payload
    assert "sandbox" in payload

    update = client.post(
        "/api/config",
        json={
            "model": "gpt-4o-mini",
            "max_tool_calls_per_turn": 3,
            "sandbox_mode": "local",
        },
    )
    assert update.status_code == 200
    update_payload = update.json()
    assert update_payload["max_tool_calls_per_turn"] == 3
    assert update_payload["sandbox"]["mode"] == "local"


def test_reset_session_endpoint() -> None:
    session = agent.create_session()

    response = client.post(f"/api/sessions/{session.session_id}/reset")
    assert response.status_code == 200
    assert response.json()["reset"] is True

    missing = client.post(f"/api/sessions/{session.session_id}/reset")
    assert missing.status_code == 404


def test_sessions_list_and_share() -> None:
    created = client.post("/api/sessions", json={})
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    sessions = client.get("/api/sessions")
    assert sessions.status_code == 200
    assert any(item["session_id"] == session_id for item in sessions.json()["sessions"])

    share = client.post(f"/api/sessions/{session_id}/share")
    assert share.status_code == 200
    share_id = share.json()["share_id"]

    public_session = client.get(f"/api/public/{share_id}")
    assert public_session.status_code == 200
    assert public_session.json()["session_id"] == session_id

    markdown_response = client.get(f"/api/public/{share_id}/markdown")
    assert markdown_response.status_code == 200
    assert "text/markdown" in markdown_response.headers["content-type"]


def test_assistant_endpoint_streams_transport_state(monkeypatch) -> None:
    async def fake_run_assistant_transport(payload, controller):
        if controller.state is None:
            controller.state = {}
        controller.state["session_id"] = "session-test"
        controller.state["messages"] = [
            {
                "id": "user-1",
                "role": "user",
                "content": [{"type": "text", "text": "Hello"}],
            },
            {
                "id": "assistant-1",
                "role": "assistant",
                "status": {"type": "complete"},
                "content": [
                    {"type": "reasoning", "text": "Planning..."},
                    {"type": "text", "text": "Hi there"},
                ],
            },
        ]
        controller.state["tool_updates"] = [
            {
                "id": "u-1",
                "stage": "model",
                "status": "completed",
                "detail": "Completed response",
            }
        ]

    monkeypatch.setattr(agent, "run_assistant_transport", fake_run_assistant_transport)

    response = client.post(
        "/api/assistant",
        json={
            "commands": [
                {
                    "type": "add-message",
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": "Hello"}],
                    },
                }
            ],
            "state": {"messages": [], "tool_updates": []},
        },
    )

    assert response.status_code == 200
    assert "aui-state:" in response.text
    assert "session-test" in response.text
    assert "Completed response" in response.text


def test_loading_session_normalizes_stale_running_status() -> None:
    session = agent.create_session(title="resume me")
    session.ui_messages = [
        {
            "id": "u1",
            "role": "user",
            "content": [{"type": "text", "text": "hello"}],
        },
        {
            "id": "a1",
            "role": "assistant",
            "status": {"type": "running"},
            "content": [{"type": "text", "text": "partial"}],
        },
    ]
    agent._persist_session(session)

    fetched = client.get(f"/api/sessions/{session.session_id}")
    assert fetched.status_code == 200
    messages = fetched.json()["messages"]
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["status"]["type"] == "complete"


def test_asset_endpoints_serve_uploaded_file() -> None:
    session = agent.create_session(title="asset test")
    asset = agent.asset_manager.store_base64_asset(
        session_id=session.session_id,
        tool_call_id="tool-1",
        filename="pixel.png",
        mime_type="image/png",
        base64_data="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5x8t8AAAAASUVORK5CYII=",
        created_at="2026-03-10T00:00:00Z",
    )

    view = client.get(asset["view_url"])
    assert view.status_code == 200
    assert view.headers["content-type"].startswith("image/png")

    download = client.get(asset["download_url"])
    assert download.status_code == 200
    assert "attachment" in download.headers.get("content-disposition", "").lower()


def test_python_tool_auto_exposes_detected_image_path() -> None:
    agent.sandbox_manager.mode = "local"
    code = (
        "import base64\n"
        "data='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5x8t8AAAAASUVORK5CYII='\n"
        "open('/tmp/auto_exposed.png','wb').write(base64.b64decode(data))\n"
        "print('/tmp/auto_exposed.png')"
    )
    result = agent.sandbox_manager.exec_python(code)
    assert result.ok is True
    assert any(
        asset.get("filename") == "auto_exposed.png" for asset in result.assets or []
    )


def test_assistant_transport_emits_image_asset_in_message(monkeypatch) -> None:
    agent.sandbox_manager.mode = "local"

    class FakeFunction:
        def __init__(self, name: str, arguments: str) -> None:
            self.name = name
            self.arguments = arguments

    class FakeToolCall:
        def __init__(self, call_id: str, name: str, arguments: str) -> None:
            self.id = call_id
            self.function = FakeFunction(name, arguments)

    class FakeMessage:
        def __init__(self, content: str, tool_calls: list | None = None) -> None:
            self.content = content
            self.tool_calls = tool_calls or []

    class FakeChoice:
        def __init__(self, message) -> None:
            self.message = message

    class FakeCompletion:
        def __init__(self, message) -> None:
            self.choices = [FakeChoice(message)]

    calls = {"count": 0}

    def fake_create(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            code = (
                "import base64\n"
                "png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5x8t8AAAAASUVORK5CYII='\n"
                "open('/tmp/sinusoid_plot.png','wb').write(base64.b64decode(png))\n"
                "expose_asset('/tmp/sinusoid_plot.png')\n"
                "print('created sinusoid')"
            )
            return FakeCompletion(
                FakeMessage(
                    "",
                    [
                        FakeToolCall(
                            "tool-plot",
                            "sandbox_exec_python",
                            json.dumps({"code": code}),
                        )
                    ],
                )
            )
        return FakeCompletion(FakeMessage("Plot generated and attached."))

    monkeypatch.setattr(agent.client.chat.completions, "create", fake_create)

    response = client.post(
        "/api/assistant",
        json={
            "commands": [
                {
                    "type": "add-message",
                    "message": {
                        "role": "user",
                        "parts": [
                            {
                                "type": "text",
                                "text": "Create a sinusoid plot and show it in chat.",
                            }
                        ],
                    },
                }
            ],
            "state": {"messages": [], "tool_updates": []},
        },
    )

    assert response.status_code == 200
    assert "/api/assets/" in response.text
    assert "Plot generated and attached" in response.text
