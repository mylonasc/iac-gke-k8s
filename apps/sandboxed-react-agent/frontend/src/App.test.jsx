import React from "react";
import { render, screen } from "@testing-library/react";
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
    },
    AttachmentPrimitive: {
      Root: passthrough,
      Name: () => <span>attachment</span>,
      Remove: ({ children, ...props }) => <button {...props}>{children}</button>,
    },
    MessagePrimitive: {
      Root: passthrough,
      Parts: () => <div>message-part</div>,
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
              id: "a-1",
              role: "assistant",
              content: [{ type: "reasoning", text: "Planning response..." }],
            },
          ],
        },
      }),
    useAssistantTransportState: (selector) =>
      (typeof selector === "function" ? selector({}) : {}),
  };
});

describe("App v2", () => {
  beforeEach(() => {
    const mockSession = {
      session_id: "session-1",
      title: "Test chat",
      preview: "Hello",
      messages: [],
    };

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input, init) => {
        const url = String(input);
        if (url.endsWith("/api/sessions") && (!init || init.method === undefined)) {
          return { ok: true, json: async () => ({ sessions: [mockSession] }) };
        }
        if (url.endsWith("/api/sessions/session-1")) {
          return { ok: true, json: async () => mockSession };
        }
        if (url.endsWith("/api/config") && (!init || init.method === undefined)) {
          return {
            ok: true,
            json: async () => ({
              model: "gpt-4o-mini",
              max_tool_calls_per_turn: 4,
              sandbox: { template_name: "python-runtime-template-small" },
            }),
          };
        }
        if (url.endsWith("/api/me")) {
          return { ok: true, json: async () => ({ user_id: "tester-1", tier: "default" }) };
        }
        return { ok: true, json: async () => ({}) };
      })
    );
  });

  it("renders redesigned shell", async () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "Sandboxed React Agent" })).toBeInTheDocument();
    expect(await screen.findByText("History")).toBeInTheDocument();
    expect(screen.getByText("How can I help you today?")).toBeInTheDocument();
  });
});
