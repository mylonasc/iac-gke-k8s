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
    main_module.authorization_service.reset_to_default_policy()
    with agent.session_store._connect() as connection:
        connection.execute("DELETE FROM sessions")
        connection.execute("DELETE FROM assets")
        connection.execute("DELETE FROM sandbox_leases")
        connection.execute("DELETE FROM user_workspaces")
        connection.execute("DELETE FROM user_configs")
        connection.execute("DELETE FROM users")
    shutil.rmtree(os.environ["ASSET_STORE_PATH"], ignore_errors=True)


def _create_session(*, headers: dict[str, str] | None = None) -> str:
    created = client.post("/api/sessions", headers=headers, json={})
    assert created.status_code == 200
    return str(created.json()["session_id"])


def _terminal_open_payload(session_id: str) -> dict[str, str]:
    return {
        "terminal_id": "term-1",
        "session_id": session_id,
        "lease_id": "lease-1",
        "claim_name": "sandbox-claim-1",
        "namespace": "alt-default",
        "pod_name": "sandbox-pod-1",
        "connect_token": "tok-1",
        "token_expires_at": "2026-01-01T00:00:45+00:00",
    }


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
    assert update_payload["toolkits"]["sandbox"]["runtime"]["mode"] == "cluster"


def test_config_endpoint_does_not_query_workspace_overrides(monkeypatch) -> None:
    monkeypatch.setattr(
        agent._workspace_service,
        "get_workspace_for_user",
        lambda user_id: (_ for _ in ()).throw(
            AssertionError("workspace lookup should not happen on /api/config")
        ),
    )

    response = client.get("/api/config")

    assert response.status_code == 200


def test_me_endpoint_returns_user_tier() -> None:
    response = client.get("/api/me")
    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"]
    assert payload["tier"] == "default"


def test_me_endpoint_includes_roles_and_capabilities(monkeypatch) -> None:
    monkeypatch.setattr(main_module.auth_config, "enabled", True)
    monkeypatch.setattr(
        main_module.token_verifier,
        "verify",
        lambda token: {"sub": "user-1", "groups": ["sra-terminal"]},
    )

    response = client.get("/api/me", headers={"Authorization": "Bearer token-1"})
    assert response.status_code == 200
    payload = response.json()
    assert "roles" in payload
    assert "capabilities" in payload
    assert "terminal.open" in payload["capabilities"]


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
    assert payload_a["toolkits"]["sandbox"]["runtime"]["mode"] == "cluster"
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


def test_config_updates_sandbox_profile() -> None:
    response = client.post(
        "/api/config",
        json={
            "sandbox_profile": "transient",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["toolkits"]["sandbox"]["runtime"]["profile"] == "transient"


def test_admin_workspace_jobs_endpoint_roundtrip(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_admin_workspace_jobs(
        *, limit: int, include_terminal: bool
    ) -> dict[str, object]:
        captured["limit"] = limit
        captured["include_terminal"] = include_terminal
        return {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "limit": limit,
            "include_terminal": include_terminal,
            "summary": {"total_jobs": 0},
            "jobs": [],
        }

    monkeypatch.setattr(agent, "get_admin_workspace_jobs", _fake_admin_workspace_jobs)

    response = client.get(
        "/api/admin/ops/workspace-jobs?limit=123&include_terminal=false"
    )

    assert response.status_code == 200
    payload = response.json()
    assert captured == {"limit": 123, "include_terminal": False}
    assert payload["limit"] == 123
    assert payload["include_terminal"] is False


def test_admin_users_search_endpoint_roundtrip(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_search_admin_users(query: str, *, limit: int) -> dict[str, object]:
        captured["query"] = query
        captured["limit"] = limit
        return {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "query": query,
            "limit": limit,
            "users": [
                {
                    "user_id": "user-alpha",
                    "tier": "default",
                    "workspace_status": "ready",
                }
            ],
        }

    monkeypatch.setattr(agent, "search_admin_users", _fake_search_admin_users)

    response = client.get("/api/admin/ops/users/search?q=alpha&limit=15")

    assert response.status_code == 200
    payload = response.json()
    assert captured == {"query": "alpha", "limit": 15}
    assert payload["query"] == "alpha"
    assert payload["limit"] == 15
    assert payload["users"][0]["user_id"] == "user-alpha"


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


def test_sandbox_release_requires_admin_write_capability(monkeypatch) -> None:
    read_only_admin_policy = """
version: 1
default_roles:
  authenticated: [authenticated]
  unauthenticated: [anonymous]
role_mappings:
  groups:
    sra-admins: [ops_admin]
roles:
  authenticated:
    capabilities: []
  ops_admin:
    capabilities: [admin.ops.read]
feature_rules:
  admin.ops.read:
    any_capabilities: [admin.ops.read]
  admin.ops.write:
    any_capabilities: [admin.ops.write]
""".strip()
    main_module.authorization_service.set_policy_from_yaml_text(
        read_only_admin_policy,
        persist=True,
    )

    monkeypatch.setattr(main_module.auth_config, "enabled", True)
    monkeypatch.setattr(main_module, "OPS_ADMIN_ALLOW_ALL_AUTHENTICATED", False)
    monkeypatch.setattr(main_module, "OPS_ADMIN_USER_ID_ALLOWLIST", set())
    monkeypatch.setattr(main_module, "OPS_ADMIN_EMAIL_ALLOWLIST", set())
    monkeypatch.setattr(main_module, "OPS_ADMIN_GROUP_ALLOWLIST", set())
    monkeypatch.setattr(
        main_module.token_verifier,
        "verify",
        lambda token: {"sub": "admin-1", "groups": ["sra-admins"]},
    )
    monkeypatch.setattr(agent, "list_sandboxes", lambda: [])
    monkeypatch.setattr(agent, "release_sandbox", lambda lease_id: True)

    listed = client.get("/api/sandboxes", headers={"Authorization": "Bearer token-1"})
    assert listed.status_code == 200

    released = client.post(
        "/api/sandboxes/lease-123/release",
        headers={"Authorization": "Bearer token-1"},
    )
    assert released.status_code == 403


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


def test_session_sandbox_status_policy_and_actions_endpoints(monkeypatch) -> None:
    created = client.post("/api/sessions", json={})
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    status_payload = {
        "session_id": session_id,
        "sandbox": {"has_active_lease": False, "status": None},
        "sandbox_policy": {"profile": "persistent_workspace"},
        "effective": {"runtime": {"profile": "persistent_workspace"}, "lifecycle": {}},
        "workspace_status": {"workspace": None, "provisioning_pending": False},
        "available_sandboxes": {"profiles": ["persistent_workspace", "transient"]},
    }

    monkeypatch.setattr(
        agent,
        "get_session_sandbox_status",
        lambda session_id_value, user_id: status_payload,
    )
    monkeypatch.setattr(
        agent,
        "get_session_sandbox_policy",
        lambda session_id_value, user_id: {"profile": "persistent_workspace"},
    )
    monkeypatch.setattr(
        agent,
        "update_session_sandbox_policy",
        lambda session_id_value, user_id, policy_updates, clear=False: {
            "session_id": session_id_value,
            "sandbox_policy": policy_updates,
            "lease_released": True,
        },
    )
    monkeypatch.setattr(
        agent,
        "perform_session_sandbox_action",
        lambda session_id_value, user_id, action, wait=False: {
            "action": action,
            "wait": wait,
            "status": status_payload,
        },
    )

    status_response = client.get(f"/api/sessions/{session_id}/sandbox/status")
    assert status_response.status_code == 200
    assert status_response.json()["session_id"] == session_id

    policy_response = client.get(f"/api/sessions/{session_id}/sandbox/policy")
    assert policy_response.status_code == 200
    assert policy_response.json()["sandbox_policy"]["profile"] == "persistent_workspace"

    patch_response = client.patch(
        f"/api/sessions/{session_id}/sandbox/policy",
        json={"profile": "transient", "template_name": "python-runtime-template-small"},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["sandbox_policy"]["profile"] == "transient"

    action_response = client.post(
        f"/api/sessions/{session_id}/sandbox/actions",
        json={"action": "release_lease", "wait": False},
    )
    assert action_response.status_code == 200
    assert action_response.json()["action"] == "release_lease"


def test_terminal_open_and_close_endpoints(monkeypatch) -> None:
    session_id = _create_session()

    monkeypatch.setattr(
        agent,
        "open_session_terminal",
        lambda sid, uid: _terminal_open_payload(sid),
    )
    monkeypatch.setattr(agent, "close_session_terminal", lambda **kwargs: True)

    opened = client.post(f"/api/sessions/{session_id}/sandbox/terminal/open")
    assert opened.status_code == 200
    payload = opened.json()
    assert payload["terminal_id"] == "term-1"
    assert payload["websocket_path"].endswith("/ws?token=tok-1")

    closed = client.delete(f"/api/sessions/{session_id}/sandbox/terminal/term-1")
    assert closed.status_code == 200
    assert closed.json()["closed"] is True

    opened_dev = client.post(f"/api/dev/sessions/{session_id}/terminal/open")
    assert opened_dev.status_code == 200
    assert "/api/dev/sessions/" in opened_dev.json()["websocket_path"]

    closed_dev = client.delete(f"/api/dev/sessions/{session_id}/terminal/term-1")
    assert closed_dev.status_code == 200
    assert closed_dev.json()["closed"] is True


def test_terminal_open_enforces_session_ownership(monkeypatch) -> None:
    monkeypatch.setattr(main_module.auth_config, "enabled", True)
    monkeypatch.setattr(
        main_module.token_verifier,
        "verify",
        lambda token: {"sub": "user-a" if token == "token-a" else "user-b"},
    )

    session_id = _create_session(headers={"Authorization": "Bearer token-a"})

    monkeypatch.setattr(
        agent,
        "open_session_terminal",
        lambda sid, uid: _terminal_open_payload(sid),
    )

    forbidden = client.post(
        f"/api/sessions/{session_id}/sandbox/terminal/open",
        headers={"Authorization": "Bearer token-b"},
    )
    assert forbidden.status_code == 404
    assert forbidden.json()["detail"] == "Session not found"


def test_terminal_open_requires_terminal_capability(monkeypatch) -> None:
    strict_policy = """
version: 1
default_roles:
  authenticated: [authenticated]
  unauthenticated: [anonymous]
role_mappings:
  groups:
    sra-terminal: [terminal_user]
roles:
  authenticated:
    capabilities: []
  terminal_user:
    capabilities: [terminal.open]
feature_rules:
  terminal.open:
    any_capabilities: [terminal.open]
""".strip()
    main_module.authorization_service.set_policy_from_yaml_text(
        strict_policy, persist=True
    )

    monkeypatch.setattr(main_module.auth_config, "enabled", True)
    monkeypatch.setattr(
        main_module.token_verifier,
        "verify",
        lambda token: {"sub": "user-a", "groups": []},
    )

    session_id = _create_session(headers={"Authorization": "Bearer token-a"})
    denied = client.post(
        f"/api/sessions/{session_id}/sandbox/terminal/open",
        headers={"Authorization": "Bearer token-a"},
    )
    assert denied.status_code == 403


def test_sandbox_status_filters_restricted_templates(monkeypatch) -> None:
    monkeypatch.setattr(main_module.auth_config, "enabled", True)
    monkeypatch.setattr(
        main_module.token_verifier,
        "verify",
        lambda token: {"sub": "user-a", "groups": []},
    )
    monkeypatch.setattr(
        agent,
        "_available_cluster_templates",
        lambda namespace: [
            {"name": "python-runtime-template-small", "namespace": namespace},
            {"name": "python-runtime-template-pydata", "namespace": namespace},
        ],
    )

    session_id = _create_session(headers={"Authorization": "Bearer token-a"})
    response = client.get(
        f"/api/sessions/{session_id}/sandbox/status",
        headers={"Authorization": "Bearer token-a"},
    )
    assert response.status_code == 200
    templates = response.json()["available_sandboxes"]["templates"]
    names = [item["name"] for item in templates]
    assert "python-runtime-template-small" in names
    assert "python-runtime-template-pydata" not in names


def test_terminal_open_returns_json_for_unexpected_errors(monkeypatch) -> None:
    session_id = _create_session()

    def _raise_runtime_error(_session_id: str, _user_id: str):
        raise RuntimeError("boom")

    monkeypatch.setattr(agent, "open_session_terminal", _raise_runtime_error)

    opened = client.post(f"/api/sessions/{session_id}/sandbox/terminal/open")
    assert opened.status_code == 500
    assert opened.headers["content-type"].startswith("application/json")
    assert opened.json()["detail"] == "Failed to open terminal session"

    opened_dev = client.post(f"/api/dev/sessions/{session_id}/terminal/open")
    assert opened_dev.status_code == 500
    assert opened_dev.headers["content-type"].startswith("application/json")
    assert opened_dev.json()["detail"] == "Failed to open terminal session"


def test_terminal_websocket_stream_roundtrip(monkeypatch) -> None:
    created = client.post("/api/sessions", json={})
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    reads = {"count": 0}
    writes: list[str] = []
    resizes: list[tuple[int, int]] = []
    closes: list[str] = []

    monkeypatch.setattr(
        agent,
        "connect_session_terminal",
        lambda **kwargs: {
            "terminal_id": kwargs["terminal_id"],
            "session_id": kwargs["session_id"],
        },
    )

    def _read_output(**kwargs):
        reads["count"] += 1
        if reads["count"] == 1:
            return [{"type": "stdout", "data": "ready\\n"}]
        return []

    monkeypatch.setattr(agent, "read_session_terminal_output", _read_output)
    monkeypatch.setattr(
        agent,
        "write_session_terminal_input",
        lambda **kwargs: writes.append(kwargs["data"]),
    )
    monkeypatch.setattr(
        agent,
        "resize_session_terminal",
        lambda **kwargs: resizes.append((kwargs["cols"], kwargs["rows"])),
    )
    monkeypatch.setattr(
        agent,
        "close_session_terminal",
        lambda **kwargs: closes.append(kwargs["terminal_id"]) or True,
    )

    with client.websocket_connect(
        f"/api/sessions/{session_id}/sandbox/terminal/term-1/ws?token=tok-1"
    ) as websocket:
        status_event = websocket.receive_json()
        output_event = websocket.receive_json()
        websocket.send_json({"type": "stdin", "data": "ls\\n"})
        websocket.send_json({"type": "resize", "cols": 132, "rows": 40})

    assert status_event == {"type": "status", "status": "connected"}
    assert output_event["type"] == "stdout"
    assert output_event["data"] == "ready\\n"
    assert writes == ["ls\\n"]
    assert resizes in ([], [(132, 40)])
    assert closes in ([], ["term-1"])


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
        controller.state["sandbox_updates"] = [
            {
                "id": "s-1",
                "stage": "lease",
                "status": "completed",
                "code": "claim_ready",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "payload": {"claim_name": "claim-1"},
            }
        ]
        controller.state["sandbox_live"] = controller.state["sandbox_updates"][-1]

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
    assert "claim_ready" in response.text


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
    def fake_run_python(*, session_id, tool_call_id, code, runtime_config, created_at):
        from app.agents.tool_payloads import ToolExecutionPayload

        stored_assets = [
            {
                "asset_id": "asset-plot",
                "filename": "sinusoid_plot.png",
                "mime_type": "image/png",
                "size_bytes": 68,
                "sha256": "fake",
                "created_at": created_at,
                "url": "/api/assets/asset-plot/content",
            }
        ]
        payload = ToolExecutionPayload(
            tool="sandbox_exec_python",
            ok=True,
            stdout="created sinusoid",
            stderr="",
            exit_code=0,
            assets=[
                {
                    "path": "/tmp/sinusoid_plot.png",
                    "filename": "sinusoid_plot.png",
                    "mime_type": "image/png",
                    "asset_id": "asset-plot",
                    "url": "/api/assets/asset-plot/content",
                }
            ],
        )
        return payload, stored_assets

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
