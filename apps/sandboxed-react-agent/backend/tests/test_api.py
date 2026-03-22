import os
from pathlib import Path
import shutil
import json
import asyncio
from types import SimpleNamespace

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
        connection.execute("DELETE FROM sandbox_leases")
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


def test_config_updates_sandbox_lifecycle_mode() -> None:
    response = client.post(
        "/api/config",
        json={
            "sandbox_execution_model": "session",
            "sandbox_session_idle_ttl_seconds": 900,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["sandbox"]["execution_model"] == "session"
    assert payload["sandbox"]["session_idle_ttl_seconds"] == 900


def test_sandbox_lifecycle_endpoints_roundtrip(monkeypatch) -> None:
    fake_lease = {
        "lease_id": "lease-123",
        "scope_type": "session",
        "scope_key": "s1",
        "status": "ready",
        "claim_name": "sandbox-claim-abc",
        "template_name": "python-runtime-template-small",
        "namespace": "alt-default",
        "metadata": {},
        "created_at": "2026-03-20T10:00:00+00:00",
        "last_used_at": "2026-03-20T10:01:00+00:00",
        "expires_at": "2026-03-20T10:31:00+00:00",
        "released_at": None,
        "last_error": None,
    }

    monkeypatch.setattr(agent, "list_sandboxes", lambda: [fake_lease])
    monkeypatch.setattr(
        agent,
        "get_sandbox",
        lambda lease_id: fake_lease if lease_id == "lease-123" else None,
    )
    monkeypatch.setattr(
        agent, "release_sandbox", lambda lease_id: lease_id == "lease-123"
    )

    listed = client.get("/api/sandboxes")
    assert listed.status_code == 200
    assert listed.json()["sandboxes"][0]["lease_id"] == "lease-123"

    fetched = client.get("/api/sandboxes/lease-123")
    assert fetched.status_code == 200
    assert fetched.json()["claim_name"] == "sandbox-claim-abc"

    released = client.post("/api/sandboxes/lease-123/release")
    assert released.status_code == 200
    assert released.json()["released"] is True

    missing = client.get("/api/sandboxes/does-not-exist")
    assert missing.status_code == 404


def test_reset_session_endpoint() -> None:
    session = agent.create_session()

    response = client.post(f"/api/sessions/{session.session_id}/reset")
    assert response.status_code == 200
    assert response.json()["reset"] is True

    missing = client.post(f"/api/sessions/{session.session_id}/reset")
    assert missing.status_code == 404


def test_session_sandbox_endpoint() -> None:
    session = agent.create_session()
    response = client.get(f"/api/sessions/{session.session_id}/sandbox")
    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session.session_id
    assert payload["sandbox"]["has_active_lease"] is False


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


def test_transport_uses_server_session_messages_as_source_of_truth(monkeypatch) -> None:
    session = agent.create_session(title="asset persistence")
    session.ui_messages = [
        {
            "id": "u-old",
            "role": "user",
            "content": [{"type": "text", "text": "create image"}],
        },
        {
            "id": "a-old",
            "role": "assistant",
            "status": {"type": "complete"},
            "content": [
                {
                    "type": "tool-call",
                    "toolCallId": "tool-old",
                    "toolName": "sandbox_exec_python",
                    "argsText": "{}",
                    "result": {
                        "ok": True,
                        "assets": [
                            {
                                "asset_id": "asset-old",
                                "filename": "chart.png",
                                "mime_type": "image/png",
                                "view_url": "/api/assets/asset-old",
                                "download_url": "/api/assets/asset-old/download",
                            }
                        ],
                    },
                },
                {"type": "image", "image": "/api/assets/asset-old"},
            ],
        },
    ]
    agent._persist_session(session)

    async def fake_run_graph(messages, session_id):
        return {
            "session_id": session_id,
            "messages": list(messages) + [{"role": "assistant", "content": "ok"}],
            "pending_tool_calls": [],
            "turn_tool_calls": [],
            "tool_events": [],
            "tool_call_count": 0,
            "final_reply": "ok",
            "error": "",
            "limit_reached": False,
        }

    monkeypatch.setattr(agent, "_run_agent_graph_async", fake_run_graph)

    payload = SimpleNamespace(
        commands=[
            SimpleNamespace(
                type="add-message",
                message=SimpleNamespace(
                    parts=[SimpleNamespace(type="text", text="continue")],
                    content=[],
                    id="u-new",
                ),
            )
        ],
        state={
            "session_id": session.session_id,
            "messages": [
                {
                    "id": "client-only",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "truncated"}],
                }
            ],
            "tool_updates": [],
        },
    )
    controller = SimpleNamespace(state={"messages": [], "tool_updates": []})

    asyncio.run(agent.run_assistant_transport(payload, controller))

    fetched = client.get(f"/api/sessions/{session.session_id}")
    assert fetched.status_code == 200
    messages = fetched.json()["messages"]
    old_assistant = next(m for m in messages if m.get("id") == "a-old")
    part_types = [part.get("type") for part in old_assistant.get("content", [])]
    assert "tool-call" in part_types
    assert "image" in part_types


def test_shared_markdown_includes_tool_asset_links() -> None:
    session = agent.create_session(title="markdown assets")
    session.ui_messages = [
        {
            "id": "a-assets",
            "role": "assistant",
            "status": {"type": "complete"},
            "content": [
                {
                    "type": "tool-call",
                    "toolCallId": "tool-asset",
                    "toolName": "sandbox_exec_python",
                    "argsText": "{}",
                    "result": {
                        "ok": True,
                        "assets": [
                            {
                                "asset_id": "asset-png",
                                "filename": "plot.png",
                                "mime_type": "image/png",
                                "view_url": "/api/assets/asset-png",
                                "download_url": "/api/assets/asset-png/download",
                            },
                            {
                                "asset_id": "asset-csv",
                                "filename": "report.csv",
                                "mime_type": "text/csv",
                                "view_url": "/api/assets/asset-csv",
                                "download_url": "/api/assets/asset-csv/download",
                            },
                        ],
                    },
                }
            ],
        }
    ]
    agent._persist_session(session)
    share_id = agent.create_share(session.session_id)
    assert share_id is not None

    markdown_response = client.get(f"/api/public/{share_id}/markdown")
    assert markdown_response.status_code == 200
    markdown = markdown_response.text
    assert "#### Tool assets" in markdown
    assert "![plot.png](/api/assets/asset-png)" in markdown
    assert "[report.csv](/api/assets/asset-csv/download)" in markdown


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

    monkeypatch.setattr(agent.async_client.chat.completions, "create", fake_create)

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
