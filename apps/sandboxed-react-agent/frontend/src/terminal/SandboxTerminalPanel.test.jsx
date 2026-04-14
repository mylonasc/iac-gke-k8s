import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";


class MockTerminal {
  static instances = [];

  constructor() {
    this.cols = 80;
    this.rows = 24;
    this.output = "";
    this.selection = "";
    this.options = {};
    this._onData = null;
    MockTerminal.instances.push(this);
  }

  loadAddon(addon) {
    this.addon = addon;
  }

  open() {}

  onData(handler) {
    this._onData = handler;
    return { dispose: () => {} };
  }

  onKey(handler) {
    this._onKey = handler;
    return { dispose: () => {} };
  }

  setOption(name, value) {
    this.options[name] = value;
  }

  hasSelection() {
    return Boolean(this.selection);
  }

  getSelection() {
    return this.selection;
  }

  clearSelection() {
    this.selection = "";
  }

  write(value) {
    this.output += String(value || "");
  }

  writeln(value) {
    this.output += `${String(value || "")}\n`;
  }

  focus() {}

  dispose() {}
}


class MockFitAddon {
  fit() {}
}

import { SandboxTerminalPanel } from "./SandboxTerminalPanel";


class MockWebSocket {
  static instances = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  constructor(url) {
    this.url = url;
    this.readyState = MockWebSocket.CONNECTING;
    this.sent = [];
    this.onopen = null;
    this.onclose = null;
    this.onerror = null;
    this.onmessage = null;
    MockWebSocket.instances.push(this);
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


describe("SandboxTerminalPanel", () => {
  afterEach(() => {
    MockWebSocket.instances = [];
    MockTerminal.instances = [];
    document.documentElement.setAttribute("data-theme", "light");
    vi.unstubAllGlobals();
  });

  it("opens terminal, receives output, and sends stdin", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input, init) => {
      const url = String(input);
      if (url === "/api/dev/sessions/s-1/terminal/open") {
        return {
          ok: true,
          json: async () => ({
            terminal_id: "term-1",
            websocket_path: "/api/dev/sessions/s-1/terminal/term-1/ws?token=tok-1",
            close_path: "/api/dev/sessions/s-1/terminal/term-1",
          }),
        };
      }
      if (url === "/api/dev/sessions/s-1/terminal/term-1") {
        expect(init?.method).toBe("DELETE");
        return { ok: true, json: async () => ({ closed: true }) };
      }
      return { ok: false, json: async () => ({ detail: "bad" }) };
    });

    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", MockWebSocket);

    render(
      <SandboxTerminalPanel
        title="Dev shell"
        openPath="/api/dev/sessions/s-1/terminal/open"
        terminalFactory={{ Terminal: MockTerminal, FitAddon: MockFitAddon }}
      />
    );

    await user.click(screen.getByRole("button", { name: "Open" }));

    expect(MockWebSocket.instances).toHaveLength(1);
    const ws = MockWebSocket.instances[0];
    expect(ws.url).toContain("/api/dev/sessions/s-1/terminal/term-1/ws?token=tok-1");
    const term = MockTerminal.instances[0];

    act(() => {
      ws.readyState = MockWebSocket.OPEN;
      ws.onopen?.();
      ws.onmessage?.({
        data: JSON.stringify({ type: "stdout", data: "hello from sandbox\n" }),
      });
    });

    await waitFor(() => {
      expect(term.output).toContain("hello from sandbox");
    });

    act(() => {
      term._onData?.("ls\n");
    });

    expect(ws.sent).toContain(JSON.stringify({ type: "stdin", data: "ls\n" }));

    await user.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/dev/sessions/s-1/terminal/term-1",
        expect.objectContaining({ method: "DELETE" })
      );
    });
  });

  it("reconnect button closes then opens a fresh terminal", async () => {
    const user = userEvent.setup();
    let openCount = 0;
    const fetchMock = vi.fn(async (input, init) => {
      const url = String(input);
      if (url === "/api/dev/sessions/s-1/terminal/open") {
        openCount += 1;
        return {
          ok: true,
          json: async () => ({
            terminal_id: `term-${openCount}`,
            websocket_path: `/api/dev/sessions/s-1/terminal/term-${openCount}/ws?token=tok-${openCount}`,
            close_path: `/api/dev/sessions/s-1/terminal/term-${openCount}`,
          }),
        };
      }
      if (url.startsWith("/api/dev/sessions/s-1/terminal/term-")) {
        expect(init?.method).toBe("DELETE");
        return { ok: true, json: async () => ({ closed: true }) };
      }
      return { ok: false, json: async () => ({ detail: "bad" }) };
    });

    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", MockWebSocket);

    render(
      <SandboxTerminalPanel
        title="Dev shell"
        openPath="/api/dev/sessions/s-1/terminal/open"
        terminalFactory={{ Terminal: MockTerminal, FitAddon: MockFitAddon }}
      />
    );

    await user.click(screen.getByRole("button", { name: "Open" }));
    expect(MockWebSocket.instances).toHaveLength(1);

    const firstWs = MockWebSocket.instances[0];
    act(() => {
      firstWs.readyState = MockWebSocket.OPEN;
      firstWs.onopen?.();
    });

    await user.click(screen.getByRole("button", { name: "Reconnect" }));

    await waitFor(() => {
      expect(MockWebSocket.instances).toHaveLength(2);
    });
    expect(MockWebSocket.instances[1].url).toContain("term-2/ws?token=tok-2");
  });

  it("handles ctrl/cmd copy and paste keyboard shortcuts", async () => {
    const user = userEvent.setup();
    const writeTextMock = vi.fn(async () => undefined);
    const readTextMock = vi.fn(async () => "ls\n");
    Object.defineProperty(window.navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: writeTextMock,
        readText: readTextMock,
      },
    });
    Object.defineProperty(window.navigator, "platform", {
      configurable: true,
      value: "Linux",
    });

    const fetchMock = vi.fn(async (input) => {
      const url = String(input);
      if (url === "/api/dev/sessions/s-1/terminal/open") {
        return {
          ok: true,
          json: async () => ({
            terminal_id: "term-1",
            websocket_path: "/api/dev/sessions/s-1/terminal/term-1/ws?token=tok-1",
            close_path: "/api/dev/sessions/s-1/terminal/term-1",
          }),
        };
      }
      return { ok: true, json: async () => ({ closed: true }) };
    });

    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", MockWebSocket);

    render(
      <SandboxTerminalPanel
        title="Dev shell"
        openPath="/api/dev/sessions/s-1/terminal/open"
        terminalFactory={{ Terminal: MockTerminal, FitAddon: MockFitAddon }}
      />
    );

    await user.click(screen.getByRole("button", { name: "Open" }));

    const ws = MockWebSocket.instances[0];
    const term = MockTerminal.instances[0];
    act(() => {
      ws.readyState = MockWebSocket.OPEN;
      ws.onopen?.();
    });

    const copyPreventDefault = vi.fn();
    term.selection = "pwd";
    act(() => {
      term._onKey?.({
        domEvent: {
          key: "c",
          ctrlKey: true,
          metaKey: false,
          altKey: false,
          preventDefault: copyPreventDefault,
        },
      });
    });

    await waitFor(() => {
      expect(writeTextMock).toHaveBeenCalledWith("pwd");
    });
    expect(copyPreventDefault).toHaveBeenCalled();

    const pastePreventDefault = vi.fn();
    act(() => {
      term._onKey?.({
        domEvent: {
          key: "v",
          ctrlKey: true,
          metaKey: false,
          altKey: false,
          preventDefault: pastePreventDefault,
        },
      });
    });

    await waitFor(() => {
      expect(readTextMock).toHaveBeenCalled();
    });
    expect(pastePreventDefault).toHaveBeenCalled();
    expect(ws.sent).toContain(JSON.stringify({ type: "stdin", data: "ls\n" }));
  });

  it("updates terminal theme when app theme changes", async () => {
    document.documentElement.setAttribute("data-theme", "light");

    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({}) })));
    vi.stubGlobal("WebSocket", MockWebSocket);

    render(
      <SandboxTerminalPanel
        title="Dev shell"
        openPath="/api/dev/sessions/s-1/terminal/open"
        terminalFactory={{ Terminal: MockTerminal, FitAddon: MockFitAddon }}
      />
    );

    const term = MockTerminal.instances[0];
    expect(term.options.theme).toMatchObject({
      background: "#f6f8fc",
      foreground: "#0f1728",
      cursor: "#1f4f93",
    });

    act(() => {
      document.documentElement.setAttribute("data-theme", "dark");
    });

    await waitFor(() => {
      expect(term.options.theme).toMatchObject({
        background: "#0b1420",
        foreground: "#d8e6ff",
        cursor: "#79a6ff",
      });
    });
  });

  it("shows plain-text backend errors without JSON parse failure", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input) => {
      const url = String(input);
      if (url === "/api/dev/sessions/s-1/terminal/open") {
        return {
          ok: false,
          status: 500,
          headers: new Headers({ "content-type": "text/plain" }),
          text: async () => "Internal Server Error",
        };
      }
      return { ok: true, headers: new Headers({ "content-type": "application/json" }), json: async () => ({}) };
    });

    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", MockWebSocket);

    render(
      <SandboxTerminalPanel
        title="Dev shell"
        openPath="/api/dev/sessions/s-1/terminal/open"
        terminalFactory={{ Terminal: MockTerminal, FitAddon: MockFitAddon }}
      />
    );

    await user.click(screen.getByRole("button", { name: "Open" }));

    await waitFor(() => {
      expect(screen.getByText(/Internal Server Error/)).toBeTruthy();
    });
  });
});
