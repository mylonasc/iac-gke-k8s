import { execFileSync } from "node:child_process";

import { expect, test } from "@playwright/test";

const APP_ROOT = "/home/charilaos/Workspace/iac-gke-k8s/apps/sandboxed-react-agent";

function seedHighchartsSession({ userId, sessionId, title }) {
  const pythonScript = String.raw`
import asyncio
import json
import uuid
from datetime import datetime, timezone

from app.agent import SandboxedReactAgent
from app.agents.toolkits.highcharts import HighchartsToolkit

user_id = ${JSON.stringify(userId)}
session_id = ${JSON.stringify(sessionId)}
title = ${JSON.stringify(title)}
agent = SandboxedReactAgent()
session = agent.session_store.get_session(session_id)
if not session:
    raise RuntimeError(f"Session not found: {session_id}")
toolkit = HighchartsToolkit(
    asset_manager=agent.asset_manager,
    session_id=session_id,
    runtime_config={"runtime": {"library_url": "/static/vendor/highcharts.js"}},
    now_iso=lambda: datetime.now(timezone.utc).isoformat(),
)
payload_json, stored_assets = asyncio.run(
    toolkit.run_tool_call(
        tool_call_id="tool-e2e",
        name="highcharts_create_timeseries_chart",
        arguments_json=json.dumps(
            {
                "title": "Revenue over time",
                "subtitle": "End-to-end Highcharts rendering check",
                "y_axis_title": "USD",
                "series": [
                    {
                        "name": "Revenue",
                        "data": [
                            {"x": "2026-01-01T00:00:00Z", "y": 10},
                            {"x": "2026-01-02T00:00:00Z", "y": 12},
                            {"x": "2026-01-03T00:00:00Z", "y": 14},
                        ],
                    },
                    {
                        "name": "Costs",
                        "data": [
                            {"x": "2026-01-01T00:00:00Z", "y": 7},
                            {"x": "2026-01-02T00:00:00Z", "y": 8},
                            {"x": "2026-01-03T00:00:00Z", "y": 9},
                        ],
                    },
                ],
                "data_source_name": "warehouse.daily_metrics",
                "export_component": False,
            }
        ),
    )
)
payload = json.loads(payload_json)
session["title"] = title
session["ui_messages"] = [
    {
        "id": str(uuid.uuid4()),
        "role": "assistant",
        "status": {"type": "complete"},
        "content": [
            {"type": "text", "text": "Generated a Highcharts timeseries plot."},
            {
                "type": "tool-call",
                "toolCallId": "tool-e2e",
                "toolName": "highcharts_create_timeseries_chart",
                "argsText": "{}",
                "result": payload,
            },
        ],
    }
]
session["updated_at"] = datetime.now(timezone.utc).isoformat()
agent.session_store.upsert_session(session)
print(json.dumps({"session_id": session_id, "asset_url": stored_assets[0]["view_url"], "title": title}))
`;
  const output = execFileSync(
    "docker",
    [
      "compose",
      "exec",
      "-T",
      "backend",
      "python",
      "-c",
      pythonScript,
    ],
    { cwd: APP_ROOT, encoding: "utf-8" }
  );
  const lines = output
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  return JSON.parse(lines[lines.length - 1]);
}

test("renders a Highcharts widget end to end", async ({ page }) => {
  await page.goto("/");

  const me = await page.evaluate(async () => {
    const response = await fetch("/api/me", { credentials: "include" });
    return response.json();
  });
  expect(typeof me.user_id).toBe("string");
  expect(me.user_id.length).toBeGreaterThan(0);

  const title = `Highcharts E2E ${Date.now()}`;
  const createdSession = await page.evaluate(async (nextTitle) => {
    const response = await fetch("/api/sessions", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: nextTitle }),
    });
    return response.json();
  }, title);
  expect(typeof createdSession.session_id).toBe("string");

  const seeded = seedHighchartsSession({
    userId: me.user_id,
    sessionId: createdSession.session_id,
    title,
  });

  const assetHtml = await page.evaluate(async (assetUrl) => {
    const response = await fetch(assetUrl, { credentials: "include" });
    return response.text();
  }, seeded.asset_url);
  expect(assetHtml).toContain("/static/vendor/highcharts.js");

  await page.goto(seeded.asset_url);
  await expect(page.locator("#container")).toBeVisible();
  await expect(page.locator(".highcharts-container")).toBeVisible();
  await expect(page.getByText("Revenue over time")).toBeVisible();
  await expect(page.getByText("Revenue", { exact: true })).toBeVisible();
  await expect(page.getByText("Costs", { exact: true })).toBeVisible();
});
