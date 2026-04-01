import os
import json
from pathlib import Path
from types import SimpleNamespace

from app.agents.factory import AgentFactory
from app.agents.integrations.sandbox_sessions import SessionSandboxFacade
from app.agents.toolkits.highcharts import HighchartsToolkit, HighchartsToolkitProvider
from app.agents.toolkits.runtime import CompositeToolRuntime
from app.agents.toolkits.sandbox import SandboxToolkit
from app.asset_manager import AssetManager
from app.frontend_libs import FrontendLibraryCache
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
    store = SessionStore(db_path=str(tmp_path / "factory.db"))
    factory = AgentFactory(
        model_node=lambda state: state,
        tools_node=lambda state: state,
        route_after_model=lambda state: "model",
        route_after_tools=lambda state: "model",
    )

    runtime = factory.build_tool_runtime(
        toolkit_providers=[HighchartsToolkitProvider(AssetManager(store))],
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
