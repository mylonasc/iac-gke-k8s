import { devices, expect, test } from "@playwright/test";

const longAssistantText = [
  ...Array.from({ length: 9 }, (_, index) => `Line ${index + 1}: assistant response content for layout verification.`),
  "",
  "```python",
  "import math",
  "for angle in range(0, 360, 30):",
  "    print(angle, round(math.sin(math.radians(angle)), 3))",
  "```",
].join("\n");

const session = {
  session_id: "session-1",
  title: "Layout verification",
  preview: "Long assistant answer",
  sandbox: {
    status: "ready",
    has_active_claim: true,
    claim_name: "claim-ui-test",
  },
  messages: [
    {
      id: "user-1",
      role: "user",
      status: { type: "complete" },
      content: [{ type: "text", text: "Plot me a sinusoid." }],
    },
    {
      id: "assistant-1",
      role: "assistant",
      status: { type: "complete" },
      content: [
        { type: "text", text: longAssistantText },
        {
          type: "tool-call",
          toolCallId: "tool-shell-1",
          toolName: "sandbox_exec_shell",
          argsText: JSON.stringify({ command: "printf 'hello from shell'" }, null, 2),
          result: {
            stdout: "hello from shell\n",
            exit_code: 0,
          },
        },
        {
          type: "tool-call",
          toolCallId: "tool-widget-1",
          toolName: "sandbox_exec_shell",
          argsText: JSON.stringify({ command: "generate widget" }, null, 2),
          result: {
            exit_code: 0,
            assets: [
              {
                asset_id: "asset-widget-1",
                mime_type: "text/html",
                filename: "widget.html",
                view_url: "/api/assets/widget-preview",
                download_url: "/api/assets/widget-preview",
              },
            ],
          },
        },
      ],
    },
  ],
};

async function mockAppApi(page) {
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

    if (pathname.endsWith(`/api/sessions/${session.session_id}/sandbox`) && request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ sandbox: session.sandbox }),
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

    if (pathname.endsWith("/api/assets/widget-preview") && request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "<!doctype html><html><body style='margin:0;font-family:sans-serif'><div style='padding:16px'>Widget preview</div></body></html>",
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

test.describe("chat layout", () => {
  test("centers desktop user and assistant turns in a shared reading column", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1100 });
    await mockAppApi(page);
    await page.goto("/");

    const assistantColumn = page.locator(".message-column-assistant").first();
    const userColumn = page.locator(".message-column-user").first();
    await expect(assistantColumn).toBeVisible();
    await expect(userColumn).toBeVisible();
    await expect(page.getByRole("button", { name: "Collapse" })).toBeVisible();
    await expect(page.locator(".message-fade-block.expanded").first()).toBeVisible();

    const metrics = await page.evaluate(() => {
      const assistant = document.querySelector(".message-column-assistant");
      const assistantText = document.querySelector(".message-column-assistant > .message-markdown");
      const user = document.querySelector(".message-column-user");
      const bubble = document.querySelector(".message-bubble-user");
      const viewport = document.querySelector(".thread-viewport");

      if (!assistant || !assistantText || !user || !bubble || !viewport) {
        throw new Error("Expected desktop chat elements to be present");
      }

      const assistantRect = assistant.getBoundingClientRect();
      const assistantTextRect = assistantText.getBoundingClientRect();
      const userRect = user.getBoundingClientRect();
      const bubbleRect = bubble.getBoundingClientRect();
      const viewportRect = viewport.getBoundingClientRect();
      const assistantStyles = getComputedStyle(assistant);
      return {
        assistantWidth: assistantRect.width,
        assistantTextWidth: assistantTextRect.width,
        userWidth: userRect.width,
        assistantLeftGap: assistantTextRect.left - viewportRect.left,
        assistantRightGap: viewportRect.right - assistantTextRect.right,
        userLeftGap: userRect.left - viewportRect.left,
        userRightGap: viewportRect.right - userRect.right,
        bubbleRightInset: userRect.right - bubbleRect.right,
        assistantBackground: assistantStyles.backgroundColor,
      };
    });

    expect(metrics.assistantWidth).toBeGreaterThan(760);
    expect(metrics.assistantTextWidth).toBeGreaterThan(500);
    expect(metrics.assistantTextWidth).toBeLessThanOrEqual(790);
    expect(metrics.userWidth).toBeGreaterThan(500);
    expect(metrics.userWidth).toBeLessThanOrEqual(790);
    expect(Math.abs(metrics.assistantLeftGap - metrics.assistantRightGap)).toBeLessThan(40);
    expect(Math.abs(metrics.userLeftGap - metrics.userRightGap)).toBeLessThan(40);
    expect(metrics.bubbleRightInset).toBeLessThan(4);
    expect(metrics.assistantBackground).toBe("rgba(0, 0, 0, 0)");
    await expect(page.getByRole("button", { name: "Copy" }).first()).toBeVisible();

    const copyButtonCount = await page.getByRole("button", { name: "Copy" }).count();
    const lineNumberCount = await page.locator(".code-block-shell .linenumber.react-syntax-highlighter-line-number").count();
    expect(copyButtonCount).toBeGreaterThan(0);
    expect(lineNumberCount).toBeGreaterThanOrEqual(3);

    await page.getByRole("button", { name: "Collapse" }).click();
    await expect(page.getByRole("button", { name: "Expand" }).first()).toBeVisible();

    const widgetToolExpand = page.locator(".tool-card").filter({ hasText: "UI Widget" }).getByRole("button", { name: "Expand" });
    await widgetToolExpand.click();

    const expandedCopyCount = await page.locator(".tool-card[data-state='expanded']").getByRole("button", { name: "Copy" }).count();
    expect(expandedCopyCount).toBeGreaterThan(1);

    const toolMetrics = await page.evaluate(() => {
      const viewport = document.querySelector(".thread-viewport");
      const assistantColumn = document.querySelector(".message-column-assistant");
      const expandedCard = document.querySelector(".tool-card[data-state='expanded']");
      const shellCard = expandedCard?.querySelector(".tool-code-block");
      const widgetCard = expandedCard?.querySelector(".tool-widget-wrap");
      const widgetFrame = expandedCard?.querySelector(".tool-widget-frame");
      const collapsedCard = document.querySelector(".tool-card[data-state='collapsed']");

      if (!viewport || !assistantColumn || !expandedCard || !collapsedCard || !shellCard || !widgetCard || !widgetFrame) {
        throw new Error("Expected expanded tool UI elements to be present");
      }

      const assistantRect = assistantColumn.getBoundingClientRect();
      const viewportRect = viewport.getBoundingClientRect();
      const expandedRect = expandedCard.getBoundingClientRect();
      const collapsedRect = collapsedCard.getBoundingClientRect();
      const shellRect = shellCard.getBoundingClientRect();
      const widgetRect = widgetCard.getBoundingClientRect();
      const frameRect = widgetFrame.getBoundingClientRect();
      return {
        assistantWidth: assistantRect.width,
        viewportWidth: viewportRect.width,
        expandedWidth: expandedRect.width,
        collapsedWidth: collapsedRect.width,
        viewportLeft: viewportRect.left,
        viewportRight: viewportRect.right,
        expandedLeft: expandedRect.left,
        expandedRight: expandedRect.right,
        shellLeft: shellRect.left,
        shellRight: shellRect.right,
        widgetLeft: widgetRect.left,
        widgetRight: widgetRect.right,
        frameLeft: frameRect.left,
        frameRight: frameRect.right,
      };
    });

    expect(toolMetrics.collapsedWidth).toBeLessThanOrEqual(toolMetrics.assistantWidth + 1);
    expect(toolMetrics.expandedWidth).toBeGreaterThan(toolMetrics.viewportWidth - 40);
    expect(toolMetrics.expandedLeft).toBeGreaterThanOrEqual(toolMetrics.viewportLeft - 1);
    expect(toolMetrics.expandedRight).toBeLessThanOrEqual(toolMetrics.viewportRight + 1);

    expect(toolMetrics.shellLeft).toBeGreaterThanOrEqual(toolMetrics.viewportLeft - 1);
    expect(toolMetrics.shellRight).toBeLessThanOrEqual(toolMetrics.viewportRight + 1);
    expect(toolMetrics.widgetLeft).toBeGreaterThanOrEqual(toolMetrics.viewportLeft - 1);
    expect(toolMetrics.widgetRight).toBeLessThanOrEqual(toolMetrics.viewportRight + 1);
    expect(toolMetrics.frameLeft).toBeGreaterThanOrEqual(toolMetrics.viewportLeft - 1);
    expect(toolMetrics.frameRight).toBeLessThanOrEqual(toolMetrics.viewportRight + 1);

    await page.locator(".tool-card[data-state='expanded']").getByRole("button", { name: "Collapse" }).click();
    await expect(page.locator(".tool-card[data-state='expanded']")).toHaveCount(0);
  });

  test("uses full mobile width and removes redundant chat shell borders", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockAppApi(page);
    await page.goto("/");

    const assistantColumn = page.locator(".message-column-assistant").first();
    await expect(assistantColumn).toBeVisible();

    const mobileMetrics = await page.evaluate(() => {
      const surface = document.querySelector(".message-column-assistant");
      const viewport = document.querySelector(".thread-viewport");
      const chatCard = document.querySelector(".chat-card");
      const chatHeader = document.querySelector(".chat-header");
      const composer = document.querySelector(".composer-root");

      if (!surface || !viewport || !chatCard || !chatHeader || !composer) {
        throw new Error("Expected mobile chat elements to be present");
      }

      const surfaceRect = surface.getBoundingClientRect();
      const viewportRect = viewport.getBoundingClientRect();
      return {
        surfaceWidth: surfaceRect.width,
        viewportWidth: viewportRect.width,
        chatBorderLeft: getComputedStyle(chatCard).borderLeftWidth,
        chatBorderRight: getComputedStyle(chatCard).borderRightWidth,
        headerBorderBottom: getComputedStyle(chatHeader).borderBottomWidth,
        composerBorderTop: getComputedStyle(composer).borderTopWidth,
      };
    });

    expect(mobileMetrics.surfaceWidth).toBeGreaterThan(mobileMetrics.viewportWidth - 40);
    expect(mobileMetrics.chatBorderLeft).toBe("0px");
    expect(mobileMetrics.chatBorderRight).toBe("0px");
    expect(mobileMetrics.headerBorderBottom).toBe("0px");
    expect(mobileMetrics.composerBorderTop).toBe("0px");
  });

  for (const [label, device] of Object.entries({
    "Pixel 7": devices["Pixel 7"],
    "iPhone 11": devices["iPhone 11"],
  })) {
    test(`does not horizontally overflow on ${label}`, async ({ browser }) => {
      const context = await browser.newContext({ ...device });
      const page = await context.newPage();
      await mockAppApi(page);
      await page.goto("/");
      await expect(page.locator(".message-column-assistant").first()).toBeVisible();

      const overflowMetrics = await page.evaluate(() => {
        const html = document.documentElement;
        const body = document.body;
        const candidates = Array.from(
          document.querySelectorAll(
            ".thread-viewport, .message-row, .message-column, .message-bubble, .message-markdown, .tool-card, pre, img"
          )
        );
        const worstRight = candidates.reduce((max, element) => {
          const rect = element.getBoundingClientRect();
          return Math.max(max, rect.right);
        }, 0);
        return {
          viewportWidth: window.innerWidth,
          docClientWidth: html.clientWidth,
          docScrollWidth: html.scrollWidth,
          bodyScrollWidth: body.scrollWidth,
          worstRight,
        };
      });

      expect(overflowMetrics.docScrollWidth).toBeLessThanOrEqual(overflowMetrics.docClientWidth + 1);
      expect(overflowMetrics.bodyScrollWidth).toBeLessThanOrEqual(overflowMetrics.viewportWidth + 1);
      expect(overflowMetrics.worstRight).toBeLessThanOrEqual(overflowMetrics.viewportWidth + 1);

      await context.close();
    });
  }
});
