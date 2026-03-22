import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

vi.mock("@assistant-ui/react", () => {
  const passthrough = ({ children, ...props }) => <div {...props}>{children}</div>;
  return {
    AssistantRuntimeProvider: passthrough,
    ThreadPrimitive: {
      Root: passthrough,
      Viewport: passthrough,
      Messages: ({ components }) => (
        <div>
          <components.UserMessage />
          <components.AssistantMessage />
        </div>
      ),
      ScrollToBottom: ({ children, ...props }) => <button {...props}>{children}</button>,
    },
    ComposerPrimitive: {
      Root: passthrough,
      Input: (props) => <textarea {...props} />,
      Send: ({ children, ...props }) => <button {...props}>{children}</button>,
      Cancel: ({ children, ...props }) => <button {...props}>{children}</button>,
      AddAttachment: ({ children, ...props }) => <button {...props}>{children}</button>,
      Attachments: passthrough,
      AttachmentByIndex: passthrough,
    },
    AttachmentPrimitive: {
      Root: passthrough,
      Name: () => <span>mock-attachment</span>,
      Remove: ({ children, ...props }) => <button {...props}>{children}</button>,
    },
    MessagePrimitive: {
      Root: passthrough,
      Parts: () => <div>mock-message-part</div>,
      Unstable_PartsGrouped: () => <div>mock-message-part</div>,
    },
    AuiIf: ({ condition, children }) => {
      const state = { thread: { isRunning: false, isEmpty: true } };
      return condition(state) ? <>{children}</> : null;
    },
    useAssistantTransportRuntime: () => ({ runtime: true }),
    useMessagePartText: () => ({ text: "mock", status: { type: "complete" } }),
    useMessagePartImage: () => ({ image: "data:image/png;base64,mock" }),
    useAssistantState: (selector) =>
      selector({
        thread: {
          isRunning: false,
          isEmpty: true,
          messages: [
            {
              role: "assistant",
              content: [{ type: "reasoning", text: "Planning response..." }],
            },
          ],
        },
      }),
  };
});

describe("App UI", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    const mockSession = {
      session_id: "session-1",
      title: "Debug python error",
      created_at: "2026-03-09T00:00:00Z",
      updated_at: "2026-03-09T00:00:00Z",
      preview: "How do I fix this traceback?",
      messages: [],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input, init) => {
        const url = String(input);
        if (url.endsWith("/api/sessions") && (!init || init.method === undefined)) {
          return { ok: true, json: async () => ({ sessions: [mockSession] }) };
        }

        if (url.endsWith("/api/sessions") && init?.method === "POST") {
          return { ok: true, json: async () => mockSession };
        }

        if (url.endsWith("/api/sessions/session-1") && (!init || init.method === undefined)) {
          return {
            ok: true,
            json: async () => ({
              ...mockSession,
              messages: [
                {
                  id: "m1",
                  role: "user",
                  content: [{ type: "text", text: "How do I fix this traceback?" }],
                  metadata: {},
                },
              ],
            }),
          };
        }

        if (url.endsWith("/api/config") && (!init || init.method === undefined)) {
          return {
            ok: true,
            json: async () => ({
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
          };
        }

        if (url.endsWith("/api/config") && init?.method === "POST") {
          return {
            ok: true,
            json: async () => ({
              model: "gpt-4.1-mini",
              max_tool_calls_per_turn: 6,
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
          };
        }

        return { ok: true, json: async () => ({}) };
      })
    );
    window.localStorage.clear();
  });

  it("renders chat tab by default and can switch to settings", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(screen.getByRole("heading", { name: "Sandboxed React Agent" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Threads" })).toBeInTheDocument();
    expect(screen.getByText("Start by sending a message.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Settings" }));

    expect(screen.getByRole("heading", { name: "Backend Configuration" })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByDisplayValue("gpt-4o-mini")).toBeInTheDocument();
    });
  });

  it("saves configuration from settings tab", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Settings" }));
    const modelInput = await screen.findByDisplayValue("gpt-4o-mini");
    await user.clear(modelInput);
    await user.type(modelInput, "gpt-4.1-mini");

    const maxCallsInput = screen.getByLabelText("Max tool calls per turn");
    await user.clear(maxCallsInput);
    await user.type(maxCallsInput, "6");

    await user.click(screen.getByRole("button", { name: "Save Config" }));

    await waitFor(() => {
      expect(screen.getByText("Configuration saved.")).toBeInTheDocument();
    });
  });
});
