import http from "node:http";

const host = "127.0.0.1";
const port = 8019;
const session = {
  session_id: "stream-session-e2e",
  title: "Streamed test session",
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  preview: "Streaming test preview",
};

const readJsonBody = async (req) => {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  return JSON.parse(Buffer.concat(chunks).toString("utf-8"));
};

const writeJson = (res, statusCode, payload) => {
  res.writeHead(statusCode, {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Cache-Control": "no-store",
  });
  res.end(JSON.stringify(payload));
};

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url || "/", `http://${host}:${port}`);

  if (req.method === "OPTIONS") {
    res.writeHead(204, {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
      "Access-Control-Allow-Headers": "content-type",
    });
    res.end();
    return;
  }

  if (req.method === "GET" && url.pathname === "/api/config") {
    writeJson(res, 200, {
      model: "gpt-4o-mini",
      max_tool_calls_per_turn: 4,
      sandbox: {
        mode: "local",
        api_url: "",
        template_name: "python-runtime-template",
        namespace: "alt-default",
        server_port: 8888,
        max_output_chars: 6000,
        local_timeout_seconds: 20,
      },
    });
    return;
  }

  if (req.method === "POST" && url.pathname === "/api/config") {
    const body = await readJsonBody(req);
    writeJson(res, 200, {
      model: body.model || "gpt-4o-mini",
      max_tool_calls_per_turn: Number(body.max_tool_calls_per_turn || 4),
      sandbox: {
        mode: body.sandbox_mode || "local",
        api_url: body.sandbox_api_url || "",
        template_name: body.sandbox_template_name || "python-runtime-template",
        namespace: body.sandbox_namespace || "alt-default",
        server_port: Number(body.sandbox_server_port || 8888),
        max_output_chars: Number(body.sandbox_max_output_chars || 6000),
        local_timeout_seconds: Number(body.sandbox_local_timeout_seconds || 20),
      },
    });
    return;
  }

  if (req.method === "GET" && url.pathname === "/api/sessions") {
    writeJson(res, 200, { sessions: [session] });
    return;
  }

  if (req.method === "POST" && url.pathname === "/api/sessions") {
    writeJson(res, 200, { ...session, messages: [] });
    return;
  }

  if (req.method === "GET" && url.pathname === `/api/sessions/${session.session_id}`) {
    writeJson(res, 200, { ...session, messages: [] });
    return;
  }

  if (req.method === "POST" && url.pathname === `/api/sessions/${session.session_id}/share`) {
    writeJson(res, 200, {
      session_id: session.session_id,
      share_id: "share-stream",
      share_path: "/public/share-stream",
    });
    return;
  }

  if (req.method === "GET" && url.pathname === "/api/public/share-stream") {
    writeJson(res, 200, {
      ...session,
      messages: [
        {
          id: "a-share",
          role: "assistant",
          status: { type: "complete" },
          metadata: {},
          content: [{ type: "text", text: "Shared thread example" }],
        },
      ],
    });
    return;
  }

  if (req.method === "POST" && url.pathname === "/api/assistant") {
    const body = await readJsonBody(req);
    const userParts = body?.commands?.[0]?.message?.parts || [];
    const userText =
      userParts
        .filter((part) => part.type === "text")
        .map((part) => part.text)
        .join("\n") || "hello";
    const hasImage = userParts.some((part) => part.type === "image");
    const userContent = userParts.map((part) =>
      part.type === "image"
        ? { type: "image", image: part.image }
        : { type: "text", text: part.text || "" }
    );

    res.writeHead(200, {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "no-store",
      Connection: "keep-alive",
      "Access-Control-Allow-Origin": "*",
    });

    res.write(
      `aui-state:${JSON.stringify([
        { type: "set", path: ["session_id"], value: "stream-session-e2e" },
        {
          type: "set",
          path: ["messages"],
          value: [
            {
              id: "u1",
              role: "user",
              content: userContent,
            },
          ],
        },
      ])}\n`
    );

    if (String(userText).toLowerCase().includes("sinusoid")) {
      res.write(
        `aui-state:${JSON.stringify([
          {
            type: "set",
            path: ["messages"],
            value: [
              {
                id: "u1",
                role: "user",
                content: [{ type: "text", text: userText }],
              },
              {
                id: "a1",
                role: "assistant",
                status: { type: "complete" },
                content: [
                  { type: "reasoning", text: "Planning sinusoid plot generation..." },
                  {
                    type: "text",
                    text: "I installed the required plotting library and generated the sinusoid plot.",
                  },
                  {
                    type: "tool-call",
                    toolCallId: "tool-sinusoid",
                    toolName: "sandbox_exec_python",
                    argsText:
                      '{"code":"import numpy as np\\nimport matplotlib.pyplot as plt\\nx=np.linspace(0,6.28,200)\\ny=np.sin(x)\\nplt.plot(x,y)\\nplt.savefig(\"sinusoid.png\")\\nexpose_asset(\"sinusoid.png\")"}',
                    result: {
                      ok: true,
                      stdout: "created sinusoid.png",
                      stderr: "",
                      assets: [
                        {
                          asset_id: "asset-sinusoid",
                          filename: "sinusoid.png",
                          mime_type: "image/png",
                          view_url:
                            "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5x8t8AAAAASUVORK5CYII=",
                          download_url:
                            "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5x8t8AAAAASUVORK5CYII=",
                        },
                      ],
                    },
                  },
                  {
                    type: "image",
                    image:
                      "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5x8t8AAAAASUVORK5CYII=",
                  },
                ],
              },
            ],
          },
        ])}\n`
      );
      res.end();
      return;
    }
    res.write(`g:${JSON.stringify(`Planning response for: ${userText}`)}\n`);

    setTimeout(() => {
      res.write(`g:${JSON.stringify("Using tools...")}\n`);
      res.write(`0:${JSON.stringify(hasImage ? "Image received. " : "This is a streamed ")}\n`);
    }, 120);

    setTimeout(() => {
      res.write(`0:${JSON.stringify("assistant response.")}\n`);
      res.end();
    }, 260);
    return;
  }

  if (req.method === "POST" && url.pathname.startsWith("/api/sessions/")) {
    writeJson(res, 200, { reset: true });
    return;
  }

  writeJson(res, 404, { error: "not-found", path: url.pathname });
});

server.listen(port, host, () => {
  process.stdout.write(`mock-backend listening on http://${host}:${port}\n`);
});

const shutdown = () => {
  server.close(() => process.exit(0));
};

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
