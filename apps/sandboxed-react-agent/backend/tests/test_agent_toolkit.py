import os
import json
from pathlib import Path
from types import SimpleNamespace

from app.agents.factory import AgentFactory
from app.agents.integrations.sandbox_leases import SandboxLeaseFacade
from app.agents.integrations.sandbox_sessions import SessionSandboxFacade
from app.agents.runtime import AgentRuntime
from app.agents.toolkits.highcharts import HighchartsToolkit, HighchartsToolkitProvider
from app.agents.toolkits.runtime import CompositeToolRuntime
from app.agents.toolkits.sandbox import SandboxToolkit
from app.asset_manager import AssetManager
from app.frontend_libs import FrontendLibraryCache
from app.sandbox_lifecycle import SandboxLifecycleService
from app.sandbox_manager import SandboxExecutionResult
from app.session_store import SessionStore


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


class _FakeToolRuntime:
    def get_openai_tools(self) -> list[dict[str, object]]:
        return []

    async def run_tool_call(
        self,
        *,
        tool_call_id: str | None,
        name: str,
        arguments_json: str,
    ) -> tuple[str, list[dict[str, str]]]:
        raise AssertionError("No tool calls expected")


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

    names = [tool["function"]["name"] for tool in tools]
    assert "sandbox_exec_python" in names
    assert "sandbox_exec_shell" in names
    assert "sandbox_get_session_status" in names
    assert "sandbox_set_session_policy" in names
    assert tools[0]["function"]["parameters"]["required"] == ["code"]
    assert tools[1]["function"]["parameters"]["required"] == ["command"]


def test_sandbox_toolkit_supports_diagnostic_and_mutating_controls() -> None:
    session_sandbox = SessionSandboxFacade(_FakeLeaseFacade(), _FakeAssetFacade())
    callback_calls: list[tuple[str, object]] = []

    toolkit = SandboxToolkit(
        session_sandbox=session_sandbox,
        session_id="session-ctrl",
        runtime_config={"mode": "cluster"},
        now_iso=lambda: "2026-01-01T00:00:00+00:00",
        get_session_status=lambda session_id: {
            "session_id": session_id,
            "sandbox": {"status": "ready"},
        },
        set_session_policy=lambda session_id, policy: (
            callback_calls.append((session_id, policy))
            or {"session_id": session_id, "sandbox_policy": policy}
        ),
    )

    status_payload_json, status_assets = __import__("asyncio").run(
        toolkit.run_tool_call(
            tool_call_id="tool-status",
            name="sandbox_get_session_status",
            arguments_json=json.dumps({}),
        )
    )
    status_payload = json.loads(status_payload_json)
    assert status_payload["ok"] is True
    assert status_assets == []
    assert "session-ctrl" in status_payload["stdout"]

    policy_payload_json, _ = __import__("asyncio").run(
        toolkit.run_tool_call(
            tool_call_id="tool-policy",
            name="sandbox_set_session_policy",
            arguments_json=json.dumps(
                {
                    "profile": "transient",
                    "template_name": "python-runtime-template-large",
                }
            ),
        )
    )
    policy_payload = json.loads(policy_payload_json)
    assert policy_payload["ok"] is True
    assert callback_calls == [
        (
            "session-ctrl",
            {
                "clear": False,
                "profile": "transient",
                "template_name": "python-runtime-template-large",
            },
        )
    ]


def test_sandbox_toolkit_reports_missing_workspace_template_and_starts_reconcile() -> (
    None
):
    class _Repo:
        def list_active(self):
            return []

        def upsert(self, lease):
            return None

        def list_expired(self, now_iso):
            return []

        def get(self, lease_id):
            return None

        def get_active_for_scope(self, scope_type, scope_key):
            return None

        def mark_released(
            self, lease_id, *, released_at, status="released", last_error=None
        ):
            return None

    class _Manager:
        def __init__(self) -> None:
            self.mode = "cluster"
            self.api_url = "http://sandbox-router"
            self.template_name = "python-runtime-template-small"
            self.namespace = "alt-default"
            self.server_port = 8888
            self.sandbox_ready_timeout = 420
            self.gateway_ready_timeout = 180
            self.max_output_chars = 6000
            self.local_timeout_seconds = 20

        def exec_python(self, code, runtime_config=None):
            return SandboxExecutionResult(
                tool_name="sandbox_exec_python",
                ok=True,
                stdout=code,
                stderr="",
                exit_code=0,
            )

        def exec_shell(self, command, runtime_config=None):
            return SandboxExecutionResult(
                tool_name="sandbox_exec_shell",
                ok=True,
                stdout=command,
                stderr="",
                exit_code=0,
            )

        def exec_python_with_sandbox(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("should not execute when template is missing")

        def exec_shell_with_sandbox(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("should not execute when template is missing")

    reconcile_calls: list[tuple[str, bool]] = []
    lifecycle = SandboxLifecycleService(
        sandbox_manager=_Manager(),
        sandbox_lease_repository=_Repo(),
        get_user_id_for_session=lambda session_id: "user-1",
        get_workspace_for_user=lambda user_id: {
            "workspace_id": "ws-1",
            "user_id": user_id,
            "status": "ready",
            "derived_template_name": "python-runtime-template-user-missing",
            "claim_namespace": "alt-default",
        },
        ensure_workspace_async_for_user=lambda user_id, reconcile_ready=False: (
            reconcile_calls.append((user_id, reconcile_ready))
            or ({"workspace_id": "ws-1", "user_id": user_id, "status": "ready"}, True)
        ),
    )
    lifecycle._sandbox_template_exists = lambda **kwargs: False  # type: ignore[method-assign]

    toolkit = SandboxToolkit(
        session_sandbox=SessionSandboxFacade(
            SandboxLeaseFacade(lifecycle),
            _FakeAssetFacade(),
        ),
        session_id="session-x",
        runtime_config={"mode": "cluster"},
        now_iso=lambda: "2026-01-01T00:00:00+00:00",
    )

    payload_json, stored_assets = __import__("asyncio").run(
        toolkit.run_tool_call(
            tool_call_id="tool-missing-template",
            name="sandbox_exec_python",
            arguments_json=json.dumps({"code": "print('hello')"}),
        )
    )

    payload = json.loads(payload_json)
    assert payload["ok"] is False
    assert (
        payload["error"]
        == "Workspace template missing. Reconciliation started; retry in a few seconds."
    )
    assert stored_assets == []
    assert reconcile_calls == [("user-1", True)]


def test_sandbox_toolkit_reports_missing_workspace_template_while_reconcile_in_progress() -> (
    None
):
    class _Repo:
        def list_active(self):
            return []

        def upsert(self, lease):
            return None

        def list_expired(self, now_iso):
            return []

        def get(self, lease_id):
            return None

        def get_active_for_scope(self, scope_type, scope_key):
            return None

        def mark_released(
            self, lease_id, *, released_at, status="released", last_error=None
        ):
            return None

    class _Manager:
        def __init__(self) -> None:
            self.mode = "cluster"
            self.api_url = "http://sandbox-router"
            self.template_name = "python-runtime-template-small"
            self.namespace = "alt-default"
            self.server_port = 8888
            self.sandbox_ready_timeout = 420
            self.gateway_ready_timeout = 180
            self.max_output_chars = 6000
            self.local_timeout_seconds = 20

        def exec_python(self, code, runtime_config=None):
            return SandboxExecutionResult(
                tool_name="sandbox_exec_python",
                ok=True,
                stdout=code,
                stderr="",
                exit_code=0,
            )

        def exec_shell(self, command, runtime_config=None):
            return SandboxExecutionResult(
                tool_name="sandbox_exec_shell",
                ok=True,
                stdout=command,
                stderr="",
                exit_code=0,
            )

        def exec_python_with_sandbox(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("should not execute when template is missing")

        def exec_shell_with_sandbox(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("should not execute when template is missing")

    reconcile_calls: list[tuple[str, bool]] = []
    lifecycle = SandboxLifecycleService(
        sandbox_manager=_Manager(),
        sandbox_lease_repository=_Repo(),
        get_user_id_for_session=lambda session_id: "user-1",
        get_workspace_for_user=lambda user_id: {
            "workspace_id": "ws-1",
            "user_id": user_id,
            "status": "ready",
            "derived_template_name": "python-runtime-template-user-missing",
            "claim_namespace": "alt-default",
        },
        ensure_workspace_async_for_user=lambda user_id, reconcile_ready=False: (
            reconcile_calls.append((user_id, reconcile_ready))
            or ({"workspace_id": "ws-1", "user_id": user_id, "status": "ready"}, False)
        ),
    )
    lifecycle._sandbox_template_exists = lambda **kwargs: False  # type: ignore[method-assign]

    toolkit = SandboxToolkit(
        session_sandbox=SessionSandboxFacade(
            SandboxLeaseFacade(lifecycle),
            _FakeAssetFacade(),
        ),
        session_id="session-x",
        runtime_config={"mode": "cluster"},
        now_iso=lambda: "2026-01-01T00:00:00+00:00",
    )

    payload_json, stored_assets = __import__("asyncio").run(
        toolkit.run_tool_call(
            tool_call_id="tool-missing-template-in-progress",
            name="sandbox_exec_python",
            arguments_json=json.dumps({"code": "print('hello')"}),
        )
    )

    payload = json.loads(payload_json)
    assert payload["ok"] is False
    assert (
        payload["error"]
        == "Workspace template missing. Reconciliation in progress; retry in a few seconds."
    )
    assert stored_assets == []
    assert reconcile_calls == [("user-1", True)]


def test_composite_tool_runtime_dispatches_to_registered_toolkit() -> None:
    toolkit = SandboxToolkit(
        session_sandbox=SessionSandboxFacade(_FakeLeaseFacade(), _FakeAssetFacade()),
        session_id="session-4",
        runtime_config={"mode": "local"},
        now_iso=lambda: "2026-01-01T00:00:00+00:00",
    )
    runtime = CompositeToolRuntime([("sandbox", toolkit)])

    payload_json, stored_assets = __import__("asyncio").run(
        runtime.run_tool_call(
            tool_call_id="tool-4",
            name="sandbox_exec_python",
            arguments_json=json.dumps({"code": "print('hi')"}),
        )
    )

    payload = json.loads(payload_json)
    assert payload["tool"] == "sandbox_exec_python"
    assert payload["ok"] is True
    assert stored_assets[0]["asset_id"] == "asset-1"


def test_composite_tool_runtime_rejects_duplicate_tool_names() -> None:
    toolkit = SandboxToolkit(
        session_sandbox=SessionSandboxFacade(_FakeLeaseFacade(), _FakeAssetFacade()),
        session_id="session-5",
        runtime_config={"mode": "local"},
        now_iso=lambda: "2026-01-01T00:00:00+00:00",
    )

    try:
        CompositeToolRuntime([("sandbox-a", toolkit), ("sandbox-b", toolkit)])
    except ValueError as exc:
        assert "Duplicate tool name" in str(exc)
        return

    raise AssertionError("Expected duplicate tool registration to fail")


def test_agent_runtime_uses_streaming_model_path_when_enabled() -> None:
    events: list[dict[str, object]] = []

    async def _notify_tool_event(event: dict[str, object]) -> None:
        events.append(event)

    async def _create_completion_streaming(
        messages: list[dict[str, object]], model: str, tools: list[dict[str, object]]
    ) -> dict[str, object]:
        assert model == "gpt-4o-mini"
        assert tools == []
        return {"content": "streamed reply", "tool_calls": []}

    async def _create_completion(*_args, **_kwargs):
        raise AssertionError("Expected streaming completion path")

    runtime = AgentRuntime(
        build_tool_runtime=lambda _session_id, _runtime_config: _FakeToolRuntime(),
        notify_tool_event=_notify_tool_event,
        should_stream_model=lambda: True,
        get_create_completion=lambda: _create_completion,
        get_create_completion_streaming=lambda: _create_completion_streaming,
        tool_error_output=lambda **_kwargs: "{}",
    )

    result = __import__("asyncio").run(
        runtime.graph_model_node(
            {
                "session_id": "session-1",
                "messages": [{"role": "user", "content": "hello"}],
                "runtime_config": {
                    "agent": {
                        "model": "gpt-4o-mini",
                        "max_tool_calls_per_turn": 4,
                    }
                },
                "max_tool_calls_per_turn": 4,
                "pending_tool_calls": [],
                "turn_tool_calls": [],
                "tool_events": [],
                "tool_call_count": 0,
                "final_reply": "",
                "error": "",
                "limit_reached": False,
            }
        )
    )

    assert result["final_reply"] == "streamed reply"
    assert result["messages"][-1] == {"role": "assistant", "content": "streamed reply"}
    assert events == []


def test_session_store_roundtrips_nested_runtime_config(tmp_path) -> None:
    store = SessionStore(db_path=str(tmp_path / "sessions.db"))
    store.upsert_user_config(
        "user-1",
        {
            "agent": {
                "model": "gpt-4o-mini",
                "max_tool_calls_per_turn": 3,
                "enabled_toolkits": ["sandbox"],
            },
            "toolkits": {
                "sandbox": {
                    "enabled": True,
                    "runtime": {
                        "mode": "local",
                        "api_url": "",
                        "template_name": "python-runtime-template-small",
                        "namespace": "alt-default",
                        "server_port": 8888,
                        "max_output_chars": 6000,
                        "local_timeout_seconds": 20,
                    },
                    "lifecycle": {
                        "execution_model": "session",
                        "session_idle_ttl_seconds": 1800,
                    },
                }
            },
        },
    )

    stored = store.get_user_config("user-1")

    assert stored is not None
    assert stored["agent"]["max_tool_calls_per_turn"] == 3
    assert stored["toolkits"]["sandbox"]["runtime"]["mode"] == "local"


def test_session_store_reads_legacy_runtime_config_rows(tmp_path) -> None:
    store = SessionStore(db_path=str(tmp_path / "legacy.db"))
    store.ensure_user("user-legacy")

    with store._connect() as connection:
        connection.execute(
            """
            INSERT INTO user_configs (
                user_id,
                model,
                max_tool_calls_per_turn,
                sandbox_mode,
                sandbox_api_url,
                sandbox_template_name,
                sandbox_namespace,
                sandbox_server_port,
                sandbox_max_output_chars,
                sandbox_local_timeout_seconds,
                sandbox_execution_model,
                sandbox_session_idle_ttl_seconds,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "user-legacy",
                "gpt-4o-mini",
                5,
                "cluster",
                "https://sandbox.example.test",
                "python-runtime-template-small",
                "alt-default",
                8888,
                6000,
                20,
                "session",
                1200,
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )

    stored = store.get_user_config("user-legacy")

    assert stored is not None
    assert stored["agent"]["model"] == "gpt-4o-mini"
    assert (
        stored["toolkits"]["sandbox"]["runtime"]["api_url"]
        == "https://sandbox.example.test"
    )
    assert (
        stored["toolkits"]["sandbox"]["lifecycle"]["session_idle_ttl_seconds"] == 1200
    )


def test_highcharts_toolkit_creates_html_and_component_assets(tmp_path) -> None:
    os.environ["ASSET_STORE_PATH"] = str(tmp_path / "assets")
    store = SessionStore(db_path=str(tmp_path / "charts.db"))
    asset_manager = AssetManager(store)
    toolkit = HighchartsToolkit(
        asset_manager=asset_manager,
        session_id="session-chart",
        runtime_config={"runtime": {"library_url": "/static/vendor/highcharts.js"}},
        now_iso=lambda: "2026-01-01T00:00:00+00:00",
    )

    payload_json, stored_assets = __import__("asyncio").run(
        toolkit.run_tool_call(
            tool_call_id="tool-chart",
            name="highcharts_create_timeseries_chart",
            arguments_json=json.dumps(
                {
                    "title": "Revenue over time",
                    "series": [
                        {
                            "name": "Revenue",
                            "data": [
                                {"x": "2026-01-01T00:00:00Z", "y": 10},
                                {"x": "2026-01-02T00:00:00Z", "y": 12},
                            ],
                        },
                        {
                            "name": "Costs",
                            "data": [
                                {"x": "2026-01-01T00:00:00Z", "y": 7},
                                {"x": "2026-01-02T00:00:00Z", "y": 8},
                            ],
                        },
                    ],
                    "data_source_name": "warehouse.daily_metrics",
                    "export_component": True,
                    "component_name": "RevenueTimeChart",
                }
            ),
        )
    )

    payload = json.loads(payload_json)
    assert payload["ok"] is True
    assert len(stored_assets) == 2
    html_asset = next(
        asset for asset in stored_assets if asset["filename"].endswith(".html")
    )
    component_asset = next(
        asset for asset in stored_assets if asset["filename"].endswith(".tsx")
    )

    html_record = store.get_asset(html_asset["asset_id"])
    component_record = store.get_asset(component_asset["asset_id"])
    assert html_record is not None
    assert component_record is not None

    html_content = __import__("pathlib").Path(html_record["storage_path"]).read_text()
    component_content = (
        __import__("pathlib").Path(component_record["storage_path"]).read_text()
    )
    assert "/static/vendor/highcharts.js" in html_content
    assert "Revenue over time" in html_content
    assert "Highcharts.chart('container', options);" in html_content
    assert "export function RevenueTimeChart" in component_content
    assert (
        'export const sourceDataName = "warehouse.daily_metrics";' in component_content
    )


def test_highcharts_toolkit_uses_prefixed_library_url_in_html(tmp_path) -> None:
    os.environ["ASSET_STORE_PATH"] = str(tmp_path / "assets")
    store = SessionStore(db_path=str(tmp_path / "charts-prefixed.db"))
    asset_manager = AssetManager(store)
    toolkit = HighchartsToolkit(
        asset_manager=asset_manager,
        session_id="session-chart",
        runtime_config={
            "runtime": {
                "library_url": "/sandboxed-react-agent/static/vendor/highcharts.js"
            }
        },
        now_iso=lambda: "2026-01-01T00:00:00+00:00",
    )

    _, stored_assets = __import__("asyncio").run(
        toolkit.run_tool_call(
            tool_call_id="tool-chart",
            name="highcharts_create_bar_chart",
            arguments_json=json.dumps(
                {
                    "title": "Revenue by region",
                    "categories": ["EMEA", "AMER"],
                    "series": [{"name": "Revenue", "data": [10, 12]}],
                }
            ),
        )
    )

    html_asset = next(
        asset for asset in stored_assets if asset["filename"].endswith(".html")
    )
    html_record = store.get_asset(html_asset["asset_id"])
    assert html_record is not None

    html_content = __import__("pathlib").Path(html_record["storage_path"]).read_text()
    assert "/sandboxed-react-agent/static/vendor/highcharts.js" in html_content


def test_highcharts_toolkit_exposes_expected_chart_tools(tmp_path) -> None:
    os.environ["ASSET_STORE_PATH"] = str(tmp_path / "assets")
    store = SessionStore(db_path=str(tmp_path / "schemas.db"))
    toolkit = HighchartsToolkit(
        asset_manager=AssetManager(store),
        session_id="session-schema",
        runtime_config={},
        now_iso=lambda: "2026-01-01T00:00:00+00:00",
    )

    tools = toolkit.get_openai_tools()

    assert [tool["function"]["name"] for tool in tools] == [
        "highcharts_create_timeseries_chart",
        "highcharts_create_bar_chart",
        "highcharts_create_pie_chart",
    ]


def test_agent_factory_respects_enabled_toolkits(tmp_path) -> None:
    os.environ["ASSET_STORE_PATH"] = str(tmp_path / "assets")
    os.environ["FRONTEND_LIB_CACHE_PATH"] = str(tmp_path / "frontend-libs")
    store = SessionStore(db_path=str(tmp_path / "factory.db"))
    factory = AgentFactory(
        model_node=lambda state: state,
        tools_node=lambda state: state,
        route_after_model=lambda state: "model",
        route_after_tools=lambda state: "model",
    )

    runtime = factory.build_tool_runtime(
        toolkit_providers=[
            HighchartsToolkitProvider(AssetManager(store), FrontendLibraryCache())
        ],
        session_id="session-factory",
        runtime_config={
            "agent": {"enabled_toolkits": []},
            "toolkits": {"highcharts": {"enabled": True}},
        },
        now_iso=lambda: "2026-01-01T00:00:00+00:00",
    )

    assert runtime.get_openai_tools() == []


def test_frontend_library_cache_downloads_manifest_entries(
    tmp_path, monkeypatch
) -> None:
    cache = FrontendLibraryCache(cache_dir=str(tmp_path / "vendor"))

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self):
            return b"window.Highcharts = {};"

    monkeypatch.setattr(
        "app.frontend_libs.urlopen", lambda request, timeout=30: _FakeResponse()
    )

    cache.ensure_libraries()

    cached = Path(cache.cache_dir) / "highcharts.js"
    assert cached.exists()
    assert cached.read_text() == "window.Highcharts = {};"
    assert cache.get_library_url("highcharts") == "/static/vendor/highcharts.js"


def test_frontend_library_cache_tolerates_download_failures(
    tmp_path, monkeypatch
) -> None:
    cache = FrontendLibraryCache(cache_dir=str(tmp_path / "vendor"))

    def _boom(request, timeout=30):
        raise RuntimeError("download blocked")

    monkeypatch.setattr("app.frontend_libs.urlopen", _boom)

    cache.ensure_libraries()

    assert not (Path(cache.cache_dir) / "highcharts.js").exists()


def test_frontend_library_cache_seeds_from_vendored_copy(tmp_path, monkeypatch) -> None:
    vendored_dir = tmp_path / "vendored"
    vendored_dir.mkdir(parents=True, exist_ok=True)
    (vendored_dir / "highcharts.js").write_text(
        "window.Highcharts = { vendored: true };"
    )
    monkeypatch.setenv("FRONTEND_LIB_VENDOR_PATH", str(vendored_dir))
    cache = FrontendLibraryCache(cache_dir=str(tmp_path / "vendor"))

    cache.ensure_libraries()

    cached = Path(cache.cache_dir) / "highcharts.js"
    assert cached.exists()
    assert cached.read_text() == "window.Highcharts = { vendored: true };"


def test_frontend_library_cache_falls_back_to_secondary_source(
    tmp_path, monkeypatch
) -> None:
    cache = FrontendLibraryCache(cache_dir=str(tmp_path / "vendor"))
    seen_urls: list[str] = []

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self):
            return b"window.Highcharts = { fallback: true };"

    def _fake_urlopen(request, timeout=30):
        seen_urls.append(request.full_url)
        if len(seen_urls) == 1:
            raise RuntimeError("primary blocked")
        return _FakeResponse()

    monkeypatch.setattr("app.frontend_libs.urlopen", _fake_urlopen)

    cache.ensure_libraries()

    cached = Path(cache.cache_dir) / "highcharts.js"
    assert cached.exists()
    assert seen_urls[0] == "https://code.highcharts.com/highcharts.js"
    assert seen_urls[1] == "https://cdn.jsdelivr.net/npm/highcharts@12/highcharts.js"


def test_frontend_library_cache_prefixes_library_url_with_public_base_path(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("APP_PUBLIC_BASE_PATH", "/sandboxed-react-agent/")
    cache = FrontendLibraryCache(cache_dir=str(tmp_path / "vendor"))

    assert (
        cache.get_library_url("highcharts")
        == "/sandboxed-react-agent/static/vendor/highcharts.js"
    )


def test_highcharts_provider_upgrades_legacy_default_library_url(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("APP_PUBLIC_BASE_PATH", "/sandboxed-react-agent")
    store = SessionStore(db_path=str(tmp_path / "provider.db"))
    provider = HighchartsToolkitProvider(
        asset_manager=AssetManager(store),
        frontend_library_cache=FrontendLibraryCache(cache_dir=str(tmp_path / "vendor")),
    )

    merged = provider.merge_config(
        provider.default_config(),
        {"enabled": True, "runtime": {"library_url": "/static/vendor/highcharts.js"}},
    )

    assert (
        merged["runtime"]["library_url"]
        == "/sandboxed-react-agent/static/vendor/highcharts.js"
    )


def test_highcharts_provider_preserves_custom_library_url(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("APP_PUBLIC_BASE_PATH", "/sandboxed-react-agent")
    store = SessionStore(db_path=str(tmp_path / "provider-custom.db"))
    provider = HighchartsToolkitProvider(
        asset_manager=AssetManager(store),
        frontend_library_cache=FrontendLibraryCache(cache_dir=str(tmp_path / "vendor")),
    )

    merged = provider.merge_config(
        provider.default_config(),
        {
            "enabled": True,
            "runtime": {"library_url": "https://cdn.example.test/highcharts.js"},
        },
    )

    assert merged["runtime"]["library_url"] == "https://cdn.example.test/highcharts.js"
