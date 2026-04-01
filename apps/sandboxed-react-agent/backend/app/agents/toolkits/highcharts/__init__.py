import base64
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from ....asset_manager import AssetManager
from ...tool_events import tool_end_event, tool_start_event
from ...tool_payloads import ToolExecutionAsset, ToolExecutionPayload


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value.strip()).strip("-").lower()
    return cleaned or "chart"


def _pascal_case(value: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", value)
    return "".join(part[:1].upper() + part[1:] for part in parts) or "HighchartsChart"


def _to_timestamp_ms(value: str) -> int:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _js(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=True, indent=2)


class TimeSeriesPoint(BaseModel):
    x: str | int | float = Field(
        description="ISO timestamp or unix timestamp in milliseconds"
    )
    y: float


class TimeSeriesSeries(BaseModel):
    name: str
    data: list[TimeSeriesPoint]


class HighchartsTimeseriesInput(BaseModel):
    title: str
    subtitle: str | None = None
    y_axis_title: str | None = None
    series: list[TimeSeriesSeries]
    data_source_name: str | None = Field(
        default=None,
        description="Name of the upstream source used to create this chart",
    )
    export_component: bool = False
    component_name: str | None = None


class CategorySeries(BaseModel):
    name: str
    data: list[float]


class HighchartsBarChartInput(BaseModel):
    title: str
    subtitle: str | None = None
    categories: list[str]
    series: list[CategorySeries]
    y_axis_title: str | None = None
    data_source_name: str | None = None
    export_component: bool = False
    component_name: str | None = None


class PiePoint(BaseModel):
    name: str
    y: float


class HighchartsPieChartInput(BaseModel):
    title: str
    subtitle: str | None = None
    series_name: str = "Share"
    data: list[PiePoint]
    data_source_name: str | None = None
    export_component: bool = False
    component_name: str | None = None


@dataclass
class _ChartArtifact:
    filename: str
    mime_type: str
    content: str


class HighchartsToolkit:
    """Generates Highcharts HTML previews and optional TSX component exports."""

    def __init__(
        self,
        *,
        asset_manager: AssetManager,
        session_id: str,
        runtime_config: dict[str, Any],
        now_iso: Callable[[], str],
        event_sink: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self.asset_manager = asset_manager
        self.session_id = session_id
        self.runtime_config = runtime_config
        self.now_iso = now_iso
        self.event_sink = event_sink
        self._tools = {
            "highcharts_create_timeseries_chart": HighchartsTimeseriesInput,
            "highcharts_create_bar_chart": HighchartsBarChartInput,
            "highcharts_create_pie_chart": HighchartsPieChartInput,
        }

    def get_openai_tools(self) -> list[dict[str, Any]]:
        descriptions = {
            "highcharts_create_timeseries_chart": (
                "Create a Highcharts multi-series timeseries line chart and store it as an HTML asset."
            ),
            "highcharts_create_bar_chart": (
                "Create a Highcharts bar chart and store it as an HTML asset."
            ),
            "highcharts_create_pie_chart": (
                "Create a Highcharts pie chart and store it as an HTML asset."
            ),
        }
        tools: list[dict[str, Any]] = []
        for name, schema_model in self._tools.items():
            schema = schema_model.model_json_schema()
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": descriptions[name],
                        "parameters": {
                            "type": "object",
                            "properties": dict(schema.get("properties") or {}),
                            "required": list(schema.get("required") or []),
                        },
                    },
                }
            )
        return tools

    async def run_tool_call(
        self,
        *,
        tool_call_id: str | None,
        name: str,
        arguments_json: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        try:
            parsed = json.loads(arguments_json or "{}")
        except json.JSONDecodeError as exc:
            return self._error_output(
                name, f"Invalid tool arguments JSON: {exc.msg}"
            ), []

        if not isinstance(parsed, dict):
            return self._error_output(name, "Invalid tool arguments payload type"), []

        if self.event_sink is not None:
            await self.event_sink(
                tool_start_event(tool_call_id or "", name, arguments_json)
            )

        try:
            payload, stored_assets = self._invoke(
                name, parsed, tool_call_id=tool_call_id
            )
        except Exception as exc:
            payload = ToolExecutionPayload(
                tool=name,
                ok=False,
                stdout="",
                stderr="",
                exit_code=None,
                error=f"Tool execution failed: {exc}",
            )
            stored_assets = []

        if self.event_sink is not None:
            await self.event_sink(
                tool_end_event(
                    tool_call_id=tool_call_id or "",
                    tool_name=name,
                    args_text=arguments_json,
                    args=parsed,
                    result=payload.as_dict(),
                    is_error=not payload.ok,
                    stored_assets=stored_assets,
                )
            )
        return payload.as_json(), stored_assets

    def _invoke(
        self, name: str, parsed: dict[str, Any], *, tool_call_id: str | None
    ) -> tuple[ToolExecutionPayload, list[dict[str, Any]]]:
        if name == "highcharts_create_timeseries_chart":
            input_model = HighchartsTimeseriesInput.model_validate(parsed)
            chart_options = self._timeseries_options(input_model)
            artifacts = self._chart_artifacts(
                chart_type="timeseries",
                title=input_model.title,
                chart_options=chart_options,
                data_source_name=input_model.data_source_name,
                export_component=input_model.export_component,
                component_name=input_model.component_name,
            )
        elif name == "highcharts_create_bar_chart":
            input_model = HighchartsBarChartInput.model_validate(parsed)
            chart_options = self._bar_options(input_model)
            artifacts = self._chart_artifacts(
                chart_type="bar",
                title=input_model.title,
                chart_options=chart_options,
                data_source_name=input_model.data_source_name,
                export_component=input_model.export_component,
                component_name=input_model.component_name,
            )
        elif name == "highcharts_create_pie_chart":
            input_model = HighchartsPieChartInput.model_validate(parsed)
            chart_options = self._pie_options(input_model)
            artifacts = self._chart_artifacts(
                chart_type="pie",
                title=input_model.title,
                chart_options=chart_options,
                data_source_name=input_model.data_source_name,
                export_component=input_model.export_component,
                component_name=input_model.component_name,
            )
        else:
            raise ValueError(f"Unsupported tool: {name}")

        stored_assets = [
            self.asset_manager.store_base64_asset(
                session_id=self.session_id,
                tool_call_id=tool_call_id,
                filename=artifact.filename,
                mime_type=artifact.mime_type,
                base64_data=base64.b64encode(artifact.content.encode("utf-8")).decode(
                    "ascii"
                ),
                created_at=self.now_iso(),
            )
            for artifact in artifacts
        ]
        payload_assets = [
            ToolExecutionAsset(
                asset_id=asset["asset_id"],
                filename=asset["filename"],
                mime_type=asset["mime_type"],
                view_url=asset["view_url"],
                download_url=asset["download_url"],
            )
            for asset in stored_assets
        ]
        return (
            ToolExecutionPayload(
                tool=name,
                ok=True,
                stdout=(
                    f"Created {artifacts[0].filename}"
                    + (
                        f" and exported {artifacts[1].filename}"
                        if len(artifacts) > 1
                        else ""
                    )
                ),
                stderr="",
                assets=payload_assets,
            ),
            stored_assets,
        )

    def _chart_artifacts(
        self,
        *,
        chart_type: str,
        title: str,
        chart_options: dict[str, Any],
        data_source_name: str | None,
        export_component: bool,
        component_name: str | None,
    ) -> list[_ChartArtifact]:
        slug = _slug(title)
        html = self._render_html(chart_options)
        artifacts = [
            _ChartArtifact(
                filename=f"{slug}-{chart_type}.html",
                mime_type="text/html",
                content=html,
            )
        ]
        if export_component:
            component = self._render_component(
                component_name=component_name or f"{_pascal_case(title)}Chart",
                chart_options=chart_options,
                data_source_name=data_source_name or "generated-data-source",
            )
            artifacts.append(
                _ChartArtifact(
                    filename=f"{slug}-{chart_type}.tsx",
                    mime_type="text/plain",
                    content=component,
                )
            )
        return artifacts

    def _render_html(self, chart_options: dict[str, Any]) -> str:
        library_url = str(
            ((self.runtime_config.get("runtime") or {}).get("library_url"))
            or "/static/vendor/highcharts.js"
        )
        options_text = _js(chart_options)
        return f"""<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>{chart_options.get("title", {}).get("text", "Highcharts Chart")}</title>
    <style>
      body {{ margin: 0; font-family: Inter, system-ui, sans-serif; background: #0f172a; color: #e2e8f0; }}
      #container {{ width: 100%; min-height: 420px; }}
    </style>
    <script src=\"{library_url}\"></script>
  </head>
  <body>
    <div id=\"container\"></div>
    <script>
      const options = {options_text};
      Highcharts.chart('container', options);
    </script>
  </body>
</html>
"""

    def _render_component(
        self,
        *,
        component_name: str,
        chart_options: dict[str, Any],
        data_source_name: str,
    ) -> str:
        options_text = _js(chart_options)
        return f"""import Highcharts from 'highcharts';
import {{ useEffect, useRef }} from 'react';

export const sourceDataName = {json.dumps(data_source_name, ensure_ascii=True)};
export const defaultChartOptions = {options_text} as const;

type {component_name}Props = {{
  options?: Highcharts.Options;
}};

export function {component_name}({{ options }}: {component_name}Props) {{
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {{
    if (!containerRef.current) {{
      return;
    }}
    const chart = Highcharts.chart(containerRef.current, (options ?? defaultChartOptions) as Highcharts.Options);
    return () => chart.destroy();
  }}, [options]);

  return <div data-source-name={{sourceDataName}} ref={{containerRef}} style={{{{ width: '100%', minHeight: 420 }}}} />;
}}
"""

    def _timeseries_options(
        self, input_model: HighchartsTimeseriesInput
    ) -> dict[str, Any]:
        return {
            "chart": {"type": "line", "zoomType": "x"},
            "title": {"text": input_model.title},
            **(
                {"subtitle": {"text": input_model.subtitle}}
                if input_model.subtitle
                else {}
            ),
            "xAxis": {"type": "datetime"},
            "yAxis": {"title": {"text": input_model.y_axis_title or "Value"}},
            "tooltip": {"shared": True},
            "series": [
                {
                    "name": series.name,
                    "data": [
                        [
                            _to_timestamp_ms(str(point.x))
                            if isinstance(point.x, str)
                            else int(point.x),
                            point.y,
                        ]
                        for point in series.data
                    ],
                }
                for series in input_model.series
            ],
            "credits": {"enabled": False},
        }

    def _bar_options(self, input_model: HighchartsBarChartInput) -> dict[str, Any]:
        return {
            "chart": {"type": "bar"},
            "title": {"text": input_model.title},
            **(
                {"subtitle": {"text": input_model.subtitle}}
                if input_model.subtitle
                else {}
            ),
            "xAxis": {"categories": input_model.categories, "title": {"text": None}},
            "yAxis": {"title": {"text": input_model.y_axis_title or "Value"}},
            "legend": {"reversed": False},
            "plotOptions": {"series": {"dataLabels": {"enabled": True}}},
            "series": [
                {"name": series.name, "data": list(series.data)}
                for series in input_model.series
            ],
            "credits": {"enabled": False},
        }

    def _pie_options(self, input_model: HighchartsPieChartInput) -> dict[str, Any]:
        return {
            "chart": {"type": "pie"},
            "title": {"text": input_model.title},
            **(
                {"subtitle": {"text": input_model.subtitle}}
                if input_model.subtitle
                else {}
            ),
            "tooltip": {"pointFormat": "<b>{point.percentage:.1f}%</b>"},
            "plotOptions": {
                "pie": {
                    "allowPointSelect": True,
                    "cursor": "pointer",
                    "dataLabels": {
                        "enabled": True,
                        "format": "{point.name}: {point.y}",
                    },
                }
            },
            "series": [
                {
                    "name": input_model.series_name,
                    "colorByPoint": True,
                    "data": [point.model_dump() for point in input_model.data],
                }
            ],
            "credits": {"enabled": False},
        }

    def _error_output(self, tool_name: str, error: str) -> str:
        return ToolExecutionPayload(
            tool=tool_name,
            ok=False,
            stdout="",
            stderr="",
            exit_code=None,
            error=error,
        ).as_json()


class HighchartsToolkitProvider:
    toolkit_id = "highcharts"

    def __init__(self, asset_manager: AssetManager) -> None:
        self.asset_manager = asset_manager

    def build_runtime(
        self,
        *,
        session_id: str,
        runtime_config: dict[str, Any],
        now_iso: Callable[[], str],
        event_sink: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> HighchartsToolkit:
        toolkit_config = (runtime_config.get("toolkits") or {}).get("highcharts") or {}
        return HighchartsToolkit(
            asset_manager=self.asset_manager,
            session_id=session_id,
            runtime_config=toolkit_config,
            now_iso=now_iso,
            event_sink=event_sink,
        )
