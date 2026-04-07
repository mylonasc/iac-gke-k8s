import os
import base64
from pathlib import Path
import shutil
import json
import asyncio
from types import SimpleNamespace
import jwt

from fastapi.testclient import TestClient

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("SESSION_STORE_PATH", "/tmp/sandboxed-react-agent-test.db")
os.environ.setdefault("ASSET_STORE_PATH", "/tmp/sandboxed-react-agent-assets")
os.environ.setdefault(
    "FRONTEND_LIB_CACHE_PATH", "/tmp/sandboxed-react-agent-frontend-libs"
)
os.environ.setdefault("ANON_IDENTITY_ENABLED", "1")
os.environ.setdefault("ANON_IDENTITY_SECRET", "test-anon-secret")

Path(os.environ["SESSION_STORE_PATH"]).unlink(missing_ok=True)
Path(os.environ["FRONTEND_LIB_CACHE_PATH"]).mkdir(parents=True, exist_ok=True)
(Path(os.environ["FRONTEND_LIB_CACHE_PATH"]) / "highcharts.js").write_text(
    "window.Highcharts = window.Highcharts || {};",
    encoding="utf-8",
)

from app.main import agent, app
import app.main as main_module
from app.agents.tool_payloads import ToolExecutionPayload


client = TestClient(app)


def setup_function() -> None:
    agent.sessions.clear()
    with agent.session_store._connect() as connection:
        connection.execute("DELETE FROM sessions")
        connection.execute("DELETE FROM assets")
        connection.execute("DELETE FROM sandbox_leases")
        connection.execute("DELETE FROM user_configs")
        connection.execute("DELETE FROM users")
    shutil.rmtree(os.environ["ASSET_STORE_PATH"], ignore_errors=True)


def test_auth_middleware_rejects_missing_bearer_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(main_module.auth_config, "enabled", True)

    response = client.get("/api/sessions")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing Authorization header"


def test_auth_middleware_accepts_valid_bearer_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(main_module.auth_config, "enabled", True)
    monkeypatch.setattr(
        main_module.token_verifier,
        "verify",
        lambda token: {"sub": "user-1", "token": token},
    )

    response = client.get(
        "/api/sessions",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert response.status_code == 200
    assert "sessions" in response.json()


def test_auth_middleware_rejects_invalid_bearer_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(main_module.auth_config, "enabled", True)

    def _raise_invalid(_token: str):
        raise jwt.InvalidTokenError("bad token")

    monkeypatch.setattr(main_module.token_verifier, "verify", _raise_invalid)

    response = client.get(
        "/api/sessions",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid token"


def test_auth_middleware_keeps_public_share_routes_open(monkeypatch) -> None:
    monkeypatch.setattr(main_module.auth_config, "enabled", True)

    response = client.get("/api/public/non-existent")
    assert response.status_code == 404


def test_config_roundtrip() -> None:
    response = client.get("/api/config")
    assert response.status_code == 200
    payload = response.json()
    assert "agent" in payload
    assert "toolkits" in payload

    update = client.post(
        "/api/config",
        json={
            "agent": {
                "model": "gpt-4o-mini",
                "max_tool_calls_per_turn": 3,
            },
            "toolkits": {"sandbox": {"runtime": {"mode": "local"}}},
        },
    )
    assert update.status_code == 200
    update_payload = update.json()
    assert update_payload["agent"]["max_tool_calls_per_turn"] == 3
    assert update_payload["toolkits"]["sandbox"]["runtime"]["mode"] == "local"


def test_me_endpoint_returns_user_tier() -> None:
    response = client.get("/api/me")
    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"]
    assert payload["tier"] == "default"


def test_workspace_endpoints_roundtrip(monkeypatch) -> None:
    monkeypatch.setattr(
        agent,
        "get_workspace",
        lambda user_id: None,
    )
    monkeypatch.setattr(
        agent,
        "get_workspace_status",
        lambda user_id: {
            "workspace": None,
            "provisioning_pending": False,
            "active_session_leases": [],
        },
    )
    monkeypatch.setattr(
        agent,
        "ensure_workspace_async",
        lambda user_id: (
            {
                "workspace_id": "ws-1",
                "user_id": user_id,
                "status": "pending",
            },
            True,
        ),
    )
    monkeypatch.setattr(
        agent,
        "ensure_workspace",
        lambda user_id: {
            "workspace_id": "ws-1",
            "user_id": user_id,
            "status": "ready",
        },
    )
    monkeypatch.setattr(
        agent, "delete_workspace", lambda user_id, delete_data=False: True
    )

    response = client.get("/api/workspace")
    assert response.status_code == 200
    assert response.json() == {"workspace": None}

    status_response = client.get("/api/workspace/status")
    assert status_response.status_code == 200
    assert status_response.json() == {
        "workspace": None,
        "provisioning_pending": False,
        "active_session_leases": [],
    }

    async_response = client.post("/api/workspace", json={"wait": False})
    assert async_response.status_code == 200
    assert async_response.json()["started"] is True
    assert async_response.json()["workspace"]["status"] == "pending"

    sync_response = client.post("/api/workspace", json={"wait": True})
    assert sync_response.status_code == 200
    assert sync_response.json()["started"] is False
    assert sync_response.json()["workspace"]["status"] == "ready"

    delete_response = client.request(
        "DELETE", "/api/workspace", json={"delete_data": True}
    )
    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted": True, "delete_data": True}


def test_workspace_endpoint_returns_503_for_disabled_provisioning(monkeypatch) -> None:
    monkeypatch.setattr(
        agent,
        "ensure_workspace_async",
        lambda user_id: (_ for _ in ()).throw(
            RuntimeError("workspace provisioning is disabled")
        ),
    )

    response = client.post("/api/workspace", json={"wait": False})
    assert response.status_code == 503
    assert response.json()["detail"] == "workspace provisioning is disabled"


def test_config_is_isolated_per_user(monkeypatch) -> None:
    monkeypatch.setattr(main_module.auth_config, "enabled", True)
    monkeypatch.setattr(
        main_module.token_verifier,
        "verify",
        lambda token: {"sub": "user-a" if token == "token-a" else "user-b"},
    )

    update_a = client.post(
        "/api/config",
        headers={"Authorization": "Bearer token-a"},
        json={
            "model": "gpt-4.1-mini",
            "max_tool_calls_per_turn": 2,
            "sandbox_mode": "local",
        },
    )
    assert update_a.status_code == 200

    update_b = client.post(
        "/api/config",
        headers={"Authorization": "Bearer token-b"},
        json={
            "model": "gpt-4o-mini",
            "max_tool_calls_per_turn": 6,
            "sandbox_mode": "cluster",
        },
    )
    assert update_b.status_code == 200

    get_a = client.get("/api/config", headers={"Authorization": "Bearer token-a"})
    get_b = client.get("/api/config", headers={"Authorization": "Bearer token-b"})
    assert get_a.status_code == 200
    assert get_b.status_code == 200
    payload_a = get_a.json()
    payload_b = get_b.json()
    assert payload_a["agent"]["model"] == "gpt-4.1-mini"
    assert payload_a["agent"]["max_tool_calls_per_turn"] == 2
    assert payload_a["toolkits"]["sandbox"]["runtime"]["mode"] == "local"
    assert payload_b["agent"]["model"] == "gpt-4o-mini"
    assert payload_b["agent"]["max_tool_calls_per_turn"] == 6
    assert payload_b["toolkits"]["sandbox"]["runtime"]["mode"] == "cluster"


def test_config_change_recycles_user_session_leases(monkeypatch) -> None:
    created = client.post("/api/sessions", json={})
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    calls: list[tuple[str, str]] = []

    def _fake_release_scope(scope_type: str, scope_key: str) -> bool:
        calls.append((scope_type, scope_key))
        return True

    monkeypatch.setattr(agent.sandbox_lifecycle, "release_scope", _fake_release_scope)

    response = client.post(
        "/api/config",
        json={"sandbox_template_name": "python-runtime-template-large"},
    )
    assert response.status_code == 200
    assert ("session", session_id) in calls


def test_config_updates_sandbox_lifecycle_mode() -> None:
    response = client.post(
        "/api/config",
        json={
            "toolkits": {
                "sandbox": {
                    "lifecycle": {
                        "execution_model": "session",
                        "session_idle_ttl_seconds": 900,
                    }
                }
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["toolkits"]["sandbox"]["lifecycle"]["execution_model"] == "session"
    assert (
        payload["toolkits"]["sandbox"]["lifecycle"]["session_idle_ttl_seconds"] == 900
    )


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
    created = client.post("/api/sessions", json={})
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    response = client.post(f"/api/sessions/{session_id}/reset")
    assert response.status_code == 200
    assert response.json()["reset"] is True

    missing = client.post(f"/api/sessions/{session_id}/reset")
    assert missing.status_code == 404


def test_session_sandbox_endpoint() -> None:
    created = client.post("/api/sessions", json={})
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    response = client.get(f"/api/sessions/{session_id}/sandbox")
    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session_id
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

    async def wrapper(payload, controller, user_id):
        assert isinstance(user_id, str)
        assert user_id
        await fake_run_assistant_transport(payload, controller)

    monkeypatch.setattr(agent, "run_assistant_transport", wrapper)

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
    created = client.post("/api/sessions", json={"title": "resume me"})
    assert created.status_code == 200
    session_id = created.json()["session_id"]
    session = agent.sessions[session_id]
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

    fetched = client.get(f"/api/sessions/{session_id}")
    assert fetched.status_code == 200
    messages = fetched.json()["messages"]
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["status"]["type"] == "complete"


def test_asset_endpoints_serve_uploaded_file() -> None:
    created = client.post("/api/sessions", json={"title": "asset test"})
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    asset = agent.asset_manager.store_base64_asset(
        session_id=session_id,
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
    created = client.post("/api/sessions", json={"title": "asset persistence"})
    assert created.status_code == 200
    session_id = created.json()["session_id"]
    session = agent.sessions[session_id]
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

    asyncio.run(
        agent.run_assistant_transport(payload, controller, user_id=session.user_id)
    )

    fetched = client.get(f"/api/sessions/{session_id}")
    assert fetched.status_code == 200
    messages = fetched.json()["messages"]
    old_assistant = next(m for m in messages if m.get("id") == "a-old")
    part_types = [part.get("type") for part in old_assistant.get("content", [])]
    assert "tool-call" in part_types
    assert "image" in part_types


def test_html_asset_endpoint_sets_security_headers() -> None:
    created = client.post("/api/sessions", json={"title": "html asset test"})
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    html = "<html><body><h1>Hello widget</h1></body></html>"
    asset = agent.asset_manager.store_base64_asset(
        session_id=session_id,
        tool_call_id="tool-html-1",
        filename="widget.html",
        mime_type="text/html",
        base64_data=base64.b64encode(html.encode("utf-8")).decode("ascii"),
        created_at="2026-03-10T00:00:00Z",
    )

    response = client.get(asset["view_url"])
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "content-security-policy" in response.headers
    assert (
        "script-src 'self' 'unsafe-inline' https:"
        in response.headers["content-security-policy"]
    )
    assert response.headers.get("x-frame-options") == "SAMEORIGIN"


def test_python_tool_expose_html_widget_helper() -> None:
    agent.sandbox_manager.mode = "local"
    code = (
        "html = '<!doctype html><html><body><button onclick=\"this.textContent=\\'clicked\\'\">Click</button></body></html>'\n"
        "expose_html_widget(html, 'mini-widget.html')\n"
        "print('widget ready')"
    )
    result = agent.sandbox_manager.exec_python(code)
    assert result.ok is True
    assert any(
        asset.get("filename") == "mini-widget.html"
        and asset.get("mime_type") == "text/html"
        for asset in result.assets or []
    )


def test_frontend_vendor_library_is_served_from_static_route() -> None:
    response = client.get("/static/vendor/highcharts.js")

    assert response.status_code == 200
    assert "window.Highcharts" in response.text


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
    share_id = agent.create_share(session.session_id, user_id="")
    assert share_id is not None

    markdown_response = client.get(f"/api/public/{share_id}/markdown")
    assert markdown_response.status_code == 200
    markdown = markdown_response.text
    assert "#### Tool assets" in markdown
    assert f"![plot.png](/api/public/{share_id}/assets/asset-png)" in markdown
    assert f"[report.csv](/api/public/{share_id}/assets/asset-csv/download)" in markdown


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
    updated = client.post("/api/config", json={"sandbox_mode": "local"})
    assert updated.status_code == 200

    calls = {"count": 0}

    async def fake_completion(_messages, model):
        assert isinstance(model, str)
        calls["count"] += 1
        if calls["count"] == 1:
            code = (
                "import base64\n"
                "png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5x8t8AAAAASUVORK5CYII='\n"
                "open('/tmp/sinusoid_plot.png','wb').write(base64.b64decode(png))\n"
                "expose_asset('/tmp/sinusoid_plot.png')\n"
                "print('created sinusoid')"
            )
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="",
                            tool_calls=[
                                {
                                    "id": "tool-plot",
                                    "type": "function",
                                    "function": {
                                        "name": "sandbox_exec_python",
                                        "arguments": json.dumps({"code": code}),
                                    },
                                }
                            ],
                        )
                    )
                ]
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Plot generated and attached.",
                        tool_calls=[],
                    )
                )
            ]
        )

    monkeypatch.setattr(agent, "_create_completion_async", fake_completion)

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


def test_assistant_transport_deduplicates_immediate_identical_tool_retries(
    monkeypatch,
) -> None:
    calls = {"count": 0}
    tool_runs = {"count": 0}

    async def fake_completion(_messages, model):
        assert isinstance(model, str)
        calls["count"] += 1
        if calls["count"] == 1:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="",
                            tool_calls=[
                                {
                                    "id": "tool-first",
                                    "type": "function",
                                    "function": {
                                        "name": "sandbox_exec_python",
                                        "arguments": json.dumps(
                                            {"code": "result = 12 * 13\nresult"}
                                        ),
                                    },
                                }
                            ],
                        )
                    )
                ]
            )
        if calls["count"] == 2:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="",
                            tool_calls=[
                                {
                                    "id": "tool-duplicate",
                                    "type": "function",
                                    "function": {
                                        "name": "sandbox_exec_python",
                                        "arguments": json.dumps(
                                            {"code": "result = 12 * 13\nresult"}
                                        ),
                                    },
                                }
                            ],
                        )
                    )
                ]
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="The result is 156.",
                        tool_calls=[],
                    )
                )
            ]
        )

    def fake_run_python(*, session_id, tool_call_id, code, runtime_config, created_at):
        tool_runs["count"] += 1
        payload = ToolExecutionPayload(
            tool="sandbox_exec_python",
            ok=True,
            stdout="156",
            stderr="",
            exit_code=0,
        )
        return payload, []

    monkeypatch.setattr(agent, "_create_completion_async", fake_completion)
    monkeypatch.setattr(agent.session_sandbox_facade, "run_python", fake_run_python)

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
                                "text": "Use python to calculate 12*13 and tell me the result.",
                            }
                        ],
                    },
                }
            ],
            "state": {"messages": [], "tool_updates": []},
        },
    )

    assert response.status_code == 200
    assert tool_runs["count"] == 1
    assert response.text.count('"toolCallId"') == 1
    assert "The result is 156." in response.text


def test_sessions_are_scoped_per_authenticated_user(monkeypatch) -> None:
    monkeypatch.setattr(main_module.auth_config, "enabled", True)
    monkeypatch.setattr(
        main_module.token_verifier,
        "verify",
        lambda token: {"sub": token, "token": token},
    )

    created = client.post(
        "/api/sessions",
        json={},
        headers={"Authorization": "Bearer user-a"},
    )
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    own_list = client.get("/api/sessions", headers={"Authorization": "Bearer user-a"})
    assert own_list.status_code == 200
    assert any(item["session_id"] == session_id for item in own_list.json()["sessions"])

    other_list = client.get("/api/sessions", headers={"Authorization": "Bearer user-b"})
    assert other_list.status_code == 200
    assert all(
        item["session_id"] != session_id for item in other_list.json()["sessions"]
    )

    other_get = client.get(
        f"/api/sessions/{session_id}", headers={"Authorization": "Bearer user-b"}
    )
    assert other_get.status_code == 404


def test_public_session_rewrites_asset_urls_and_serves_assets() -> None:
    session = agent.create_session(title="shared assets", user_id="owner-1")
    asset = agent.asset_manager.store_base64_asset(
        session_id=session.session_id,
        tool_call_id="tool-1",
        filename="pixel.png",
        mime_type="image/png",
        base64_data="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5x8t8AAAAASUVORK5CYII=",
        created_at="2026-03-10T00:00:00Z",
    )
    session.ui_messages = [
        {
            "id": "a1",
            "role": "assistant",
            "status": {"type": "complete"},
            "content": [
                {"type": "image", "image": asset["view_url"]},
                {
                    "type": "tool-call",
                    "toolCallId": "tool-1",
                    "toolName": "sandbox_exec_python",
                    "argsText": "{}",
                    "result": {
                        "ok": True,
                        "assets": [
                            {
                                "asset_id": asset["asset_id"],
                                "filename": asset["filename"],
                                "mime_type": asset["mime_type"],
                                "view_url": asset["view_url"],
                                "download_url": asset["download_url"],
                            }
                        ],
                    },
                },
            ],
        }
    ]
    agent._persist_session(session)
    share_id = agent.create_share(session.session_id, user_id="owner-1")
    assert share_id is not None

    shared = client.get(f"/api/public/{share_id}")
    assert shared.status_code == 200
    payload = shared.json()
    image_url = payload["messages"][0]["content"][0]["image"]
    assert image_url == f"/api/public/{share_id}/assets/{asset['asset_id']}"

    public_asset = client.get(image_url)
    assert public_asset.status_code == 200
    assert public_asset.headers["content-type"].startswith("image/png")


def test_private_assets_are_not_accessible_across_users(monkeypatch) -> None:
    monkeypatch.setattr(main_module.auth_config, "enabled", True)
    monkeypatch.setattr(
        main_module.token_verifier,
        "verify",
        lambda token: {"sub": token, "token": token},
    )

    session = agent.create_session(title="private assets", user_id="user-a")
    asset = agent.asset_manager.store_base64_asset(
        session_id=session.session_id,
        tool_call_id="tool-1",
        filename="pixel.png",
        mime_type="image/png",
        base64_data="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5x8t8AAAAASUVORK5CYII=",
        created_at="2026-03-10T00:00:00Z",
    )

    response = client.get(asset["view_url"], headers={"Authorization": "Bearer user-b"})
    assert response.status_code == 404


def test_sessions_are_scoped_per_anonymous_identity_cookie() -> None:
    client_a = TestClient(app)
    client_b = TestClient(app)

    created = client_a.post("/api/sessions", json={"title": "anon-a"})
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    own_list = client_a.get("/api/sessions")
    assert own_list.status_code == 200
    assert any(item["session_id"] == session_id for item in own_list.json()["sessions"])

    other_list = client_b.get("/api/sessions")
    assert other_list.status_code == 200
    assert all(
        item["session_id"] != session_id for item in other_list.json()["sessions"]
    )

    other_get = client_b.get(f"/api/sessions/{session_id}")
    assert other_get.status_code == 404
