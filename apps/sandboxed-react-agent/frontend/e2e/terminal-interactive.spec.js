import { expect, test } from "@playwright/test";

const session = {
  session_id: "session-1",
  title: "Terminal integration",
  preview: "Interactive shell tool",
  sandbox: {
    status: "ready",
    has_active_claim: true,
    claim_name: "claim-terminal-1",
  },
  sandbox_policy: {},
  messages: [
    {
      id: "assistant-1",
      role: "assistant",
      status: { type: "complete" },
      content: [
        { type: "text", text: "I opened an interactive shell for this session." },
        {
          type: "tool-call",
          toolCallId: "tool-shell-open-1",
          toolName: "sandbox_open_interactive_shell",
          argsText: JSON.stringify({}, null, 2),
          result: {
            status: "opened",
            data: { session_id: "session-1" },
          },
        },
      ],
    },
  ],
};

async function mockApi(page) {
  let openCount = 0;
  await page.route("http://127.0.0.1:4173/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const { pathname } = url;

    if (pathname.endsWith("/api/sessions") && request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          sessions: [
            {
              session_id: session.session_id,
              title: session.title,
              preview: session.preview,
            },
          ],
        }),
      });
      return;
    }

    if (pathname.endsWith(`/api/sessions/${session.session_id}`) && request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(session),
      });
      return;
    }

    if (pathname.endsWith(`/api/sessions/${session.session_id}/sandbox/status`) && request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          sandbox: session.sandbox,
          effective: {
            runtime: {
              profile: "persistent_workspace",
              template_name: "python-runtime-template-small",
            },
            lifecycle: {
              execution_model: "session",
            },
          },
          runtime_resolution: {
            fallback_active: false,
          },
          sandbox_policy: {},
        }),
      });
      return;
    }

    if (pathname.endsWith(`/api/sessions/${session.session_id}/sandbox/terminal/open`) && request.method() === "POST") {
      openCount += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          terminal_id: `term-${openCount}`,
          websocket_path: `/api/sessions/${session.session_id}/sandbox/terminal/term-${openCount}/ws?token=tok-${openCount}`,
          close_path: `/api/sessions/${session.session_id}/sandbox/terminal/term-${openCount}`,
        }),
      });
      return;
    }

    if (
      pathname.match(
        new RegExp(`/api/sessions/${session.session_id}/sandbox/terminal/term-\\d+$`)
      ) &&
      request.method() === "DELETE"
    ) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ closed: true }),
      });
      return;
    }

    if (pathname.endsWith("/api/config") && request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          model: "gpt-4o-mini",
          max_tool_calls_per_turn: 4,
          sandbox: { template_name: "python-runtime-template-small" },
        }),
      });
      return;
    }

    if (pathname.endsWith("/api/me") && request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ user_id: "tester-1", tier: "default" }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({}),
    });
  });
}

test("opens terminal from tool payload, reconnects, and survives theme toggle", async ({
  page,
}) => {
  const pageErrors = [];
  page.on("pageerror", (error) => {
    pageErrors.push(String(error));
  });

  await page.addInitScript(() => {
    window.localStorage.setItem("sandboxed-react-agent-theme-v2", "light");
    window.__sraMockSockets = [];

    class MockWebSocket {
      static CONNECTING = 0;
      static OPEN = 1;
      static CLOSING = 2;
      static CLOSED = 3;

      constructor(url) {
        this.url = String(url || "");
        this.readyState = MockWebSocket.CONNECTING;
        this.sent = [];
        this.onopen = null;
        this.onclose = null;
        this.onerror = null;
        this.onmessage = null;
        window.__sraMockSockets.push(this);
      }

      send(payload) {
        this.sent.push(payload);
      }

      close() {
        this.readyState = MockWebSocket.CLOSED;
        if (typeof this.onclose === "function") {
          this.onclose();
        }
      }
    }

    window.WebSocket = MockWebSocket;
  });

  await mockApi(page);
  await page.goto("/");

  const interactiveToolCard = page.locator(".tool-card").filter({ hasText: "Interactive Shell" }).first();
  await expect(interactiveToolCard).toBeVisible();
  await interactiveToolCard.getByRole("button", { name: "Expand" }).click();
  await interactiveToolCard.getByRole("button", { name: "Open terminal panel" }).click();

  await expect(page.getByRole("dialog", { name: "Sandbox terminal" })).toBeVisible();

  const terminalShell = page.locator(".terminal-shell");
  await terminalShell.getByRole("button", { name: "Open" }).click();

  const terminalSocketCount = () =>
    page.evaluate(
      () =>
        window.__sraMockSockets.filter((socket) =>
          String(socket?.url || "").includes("/api/sessions/")
        ).length
    );

  await expect
    .poll(terminalSocketCount, {
      timeout: 10_000,
      intervals: [100, 250, 500],
    })
    .toBe(1);

  await page.evaluate(() => {
    const firstSocket = window.__sraMockSockets.find((socket) =>
      String(socket?.url || "").includes("/api/sessions/")
    );
    firstSocket.readyState = window.WebSocket.OPEN;
    if (typeof firstSocket.onopen === "function") firstSocket.onopen();
  });

  await expect(terminalShell.locator(".terminal-shell-header .pill")).toHaveText("Connected");

  await page.evaluate(() => {
    const firstSocket = window.__sraMockSockets.find((socket) =>
      String(socket?.url || "").includes("/api/sessions/")
    );
    firstSocket.close();
  });

  await expect
    .poll(terminalSocketCount, {
      timeout: 10_000,
      intervals: [100, 250, 500],
    })
    .toBe(2);

  await page.evaluate(() => {
    const terminalSockets = window.__sraMockSockets.filter((socket) =>
      String(socket?.url || "").includes("/api/sessions/")
    );
    const secondSocket = terminalSockets[1];
    secondSocket.readyState = window.WebSocket.OPEN;
    if (typeof secondSocket.onopen === "function") secondSocket.onopen();
  });

  await expect(terminalShell.locator(".terminal-shell-header .pill")).toHaveText("Connected");
  await expect(terminalShell.getByText(/Connection lost\. Reconnecting in/)).toHaveCount(0);

  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.evaluate(() => {
    const darkToggle = Array.from(document.querySelectorAll("button")).find(
      (element) => element.textContent?.trim() === "Dark"
    );
    if (!(darkToggle instanceof HTMLButtonElement)) {
      throw new Error("Missing app theme toggle");
    }
    darkToggle.click();
  });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  await expect(terminalShell.locator(".terminal-shell-header .pill")).toHaveText("Connected");
  expect(pageErrors).toHaveLength(0);
});
