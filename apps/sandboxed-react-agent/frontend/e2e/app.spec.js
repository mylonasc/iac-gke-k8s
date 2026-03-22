import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  let currentMessages = [];
  const session = {
    session_id: "session-e2e",
    title: "Fix stream bug",
    created_at: "2026-03-09T00:00:00Z",
    updated_at: "2026-03-09T00:00:00Z",
    preview: "Why is streaming not working?",
  };

  await page.route("**/api/config", async (route) => {
    const method = route.request().method();
    if (method === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          model: "gpt-4o-mini",
          max_tool_calls_per_turn: 4,
          sandbox: {
            mode: "local",
            api_url: "",
            template_name: "python-runtime-template-small",
            namespace: "alt-default",
            server_port: 8888,
            max_output_chars: 6000,
            local_timeout_seconds: 20,
          },
        }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        model: "gpt-4.1-mini",
        max_tool_calls_per_turn: 5,
        sandbox: {
          mode: "local",
          api_url: "",
          template_name: "python-runtime-template-small",
          namespace: "alt-default",
          server_port: 8888,
          max_output_chars: 6000,
          local_timeout_seconds: 20,
        },
      }),
    });
  });

  await page.route("**/api/sessions", async (route) => {
    const method = route.request().method();
    if (method === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ sessions: [session] }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...session, messages: [] }),
    });
  });

  await page.route("**/api/sessions/session-e2e", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...session, messages: currentMessages }),
    });
  });

  await page.route("**/api/assets/asset-sinusoid", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "image/png",
      body: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5x8t8AAAAASUVORK5CYII=",
        "base64"
      ),
    });
  });

  await page.route("**/api/assets/asset-sinusoid/download", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "image/png",
      body: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5x8t8AAAAASUVORK5CYII=",
        "base64"
      ),
    });
  });

  await page.route("**/api/sessions/session-e2e/share", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        session_id: "session-e2e",
        share_id: "share-e2e",
        share_path: "/public/share-e2e",
      }),
    });
  });

  await page.route("**/api/public/share-e2e", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...session,
        messages: [
          {
            id: "shared-a",
            role: "assistant",
            status: { type: "complete" },
            content: [{ type: "text", text: "Shared thread content" }],
            metadata: {},
          },
        ],
      }),
    });
  });

  await page.route("**/api/public/share-e2e/markdown", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/markdown; charset=utf-8",
      body: "# Shared thread markdown\n\n## Assistant\n\nShared thread content\n",
    });
  });

  await page.route("**/api/assistant", async (route) => {
    const body = route.request().postDataJSON();
    const rawBody = JSON.stringify(body || {}).toLowerCase();
    const promptText = (body?.commands?.[0]?.message?.parts || [])
      .filter((part) => part.type === "text")
      .map((part) => part.text || "")
      .join("\n")
      .toLowerCase();
    const hasImage = Boolean(
      body?.commands?.[0]?.message?.parts?.some((part) => part.type === "image")
    );
    const isSinusoidPrompt =
      promptText.includes("sinusoid") || rawBody.includes("sinusoid");
    const userParts = hasImage
      ? [
          {
            type: "image",
            image:
              "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5x8t8AAAAASUVORK5CYII=",
          },
        ]
      : [{ type: "text", text: "hello from playwright" }];
    const assistantText = hasImage
      ? "Image received."
      : isSinusoidPrompt
        ? "I installed the required plotting library and generated the sinusoid plot."
        : "Hello from e2e stream.";
    const assistantParts = [
      { type: "reasoning", text: "Planning response..." },
      { type: "text", text: assistantText },
    ];
    if (isSinusoidPrompt) {
      assistantParts.push({
        type: "tool-call",
        toolCallId: "tool-sinusoid",
        toolName: "sandbox_exec_python",
        argsText:
          '{"code":"import numpy as np\nimport matplotlib.pyplot as plt\nx=np.linspace(0,6.28,200)\ny=np.sin(x)\nplt.plot(x,y)\nplt.savefig(\"sinusoid.png\")\nexpose_asset(\"sinusoid.png\")"}',
        result: {
          ok: true,
          stdout: "created sinusoid.png",
          stderr: "",
          assets: [
            {
              asset_id: "asset-sinusoid",
              filename: "sinusoid.png",
              mime_type: "image/png",
              view_url: "/api/assets/asset-sinusoid",
              download_url: "/api/assets/asset-sinusoid/download",
            },
          ],
        },
      });
      assistantParts.push({
        type: "image",
        image: "/api/assets/asset-sinusoid",
      });
    }

    currentMessages = [
      {
        id: "u1",
        role: "user",
        content: userParts,
      },
      {
        id: "a1",
        role: "assistant",
        status: { type: "complete" },
        content: assistantParts,
      },
    ];

    await route.fulfill({
      status: 200,
      contentType: "text/plain; charset=utf-8",
      body: [
        'aui-state:[{"type":"set","path":["session_id"],"value":"session-e2e"}]',
        `aui-state:${JSON.stringify([
          {
            type: "set",
            path: ["messages"],
            value: [
              ...currentMessages,
            ],
          },
        ])}`,
      ].join("\n"),
    });
  });

  await page.route("**/api/sessions/**/reset", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ reset: true }),
    });
  });
});

test("renders tabs and saves settings", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Sandboxed React Agent" })).toBeVisible();
  await page.getByRole("button", { name: "Settings" }).click();

  await expect(page.getByRole("heading", { name: "Backend Configuration" })).toBeVisible();
  const modelInput = page.getByRole("textbox", { name: "Model" });
  await modelInput.fill("gpt-4.1-mini");
  await page.getByRole("button", { name: "Save Config" }).click();

  await expect(page.getByText("Configuration saved.")).toBeVisible();
});

test("renders chat workspace and streaming/progress affordances", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Threads" })).toBeVisible();
  await expect(page.getByText("Fix stream bug")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Assistant UI Chat" })).toBeVisible();
  await expect(
    page.getByPlaceholder("Ask the agent to run Python/shell in sandbox, debug code, etc.")
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Send" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Share thread" })).toBeVisible();
});

test("shares thread and opens public URL", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Share thread" }).first().click();

  const publicResponse = page.waitForResponse("**/api/public/share-e2e");
  await page.goto("/public/share-e2e");
  await publicResponse;
  await expect(page.getByRole("heading", { name: "Shared Thread" })).toBeVisible();
  await expect(page.getByText("Shared thread content")).toBeVisible();
  await expect(page.getByText("Read-only shared thread")).toBeVisible();
});

test("copies share-as-markdown URL", async ({ page }) => {
  await page.goto("/");
  const shareResponse = page.waitForResponse("**/api/sessions/session-e2e/share");
  await page.getByRole("button", { name: "Share as Markdown" }).click();
  await shareResponse;
  await expect(page.getByRole("button", { name: "Copied Markdown URL" })).toBeVisible();
});

test("persists generated image across reload", async ({ page }) => {
  const persistedMessages = [
    {
      id: "u1",
      role: "user",
      content: [{ type: "text", text: "Create a sinusoid plot and expose it." }],
    },
    {
      id: "a1",
      role: "assistant",
      status: { type: "complete" },
      content: [
        {
          type: "text",
          text: "I installed the required plotting library and generated the sinusoid plot.",
        },
        { type: "image", image: "/api/assets/asset-sinusoid" },
      ],
    },
  ];

  await page.route("**/api/sessions/session-e2e", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        session_id: "session-e2e",
        title: "Fix stream bug",
        created_at: "2026-03-09T00:00:00Z",
        updated_at: "2026-03-09T00:00:00Z",
        messages: persistedMessages,
      }),
    });
  });

  await page.goto("/");
  await expect(
    page.getByText("I installed the required plotting library and generated the sinusoid plot.")
  ).toBeVisible();
  await expect(page.getByAltText("Uploaded")).toBeVisible();

  await page.reload();
  await expect(
    page.getByText("I installed the required plotting library and generated the sinusoid plot.")
  ).toBeVisible();
  await expect(page.getByAltText("Uploaded")).toBeVisible();
});
