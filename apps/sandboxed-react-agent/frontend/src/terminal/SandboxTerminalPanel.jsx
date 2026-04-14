import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "../api/client";

function toWebSocketUrl(path) {
  if (!path) return "";
  if (path.startsWith("ws://") || path.startsWith("wss://")) return path;
  if (path.startsWith("http://")) return `ws://${path.slice("http://".length)}`;
  if (path.startsWith("https://")) return `wss://${path.slice("https://".length)}`;
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  if (path.startsWith("/")) return `${protocol}://${window.location.host}${path}`;
  return `${protocol}://${window.location.host}/${path}`;
}

async function readApiPayload(response) {
  const contentType = String(response?.headers?.get?.("content-type") || "").toLowerCase();
  const asJson = contentType.includes("application/json") || contentType.includes("+json");

  const tryReadJson = async () => {
    if (typeof response?.json !== "function") return null;
    try {
      return await response.json();
    } catch {
      return null;
    }
  };

  if (asJson) {
    return (await tryReadJson()) || {};
  }

  const fallbackJson = await tryReadJson();
  if (fallbackJson && typeof fallbackJson === "object") {
    return fallbackJson;
  }

  const rawText =
    typeof response?.text === "function"
      ? await response.text().catch(() => "")
      : "";
  return {
    detail: rawText || undefined,
    raw_text: rawText,
  };
}

export function SandboxTerminalPanel({
  title,
  openPath,
  terminalFactory = null,
}) {
  const wsRef = useRef(null);
  const closePathRef = useRef("");
  const terminalIdRef = useRef("");
  const termRef = useRef(null);
  const fitAddonRef = useRef(null);
  const terminalHostRef = useRef(null);
  const resizeObserverRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const reconnectAttemptsRef = useRef(0);
  const manualCloseRef = useRef(false);
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");
  const [reconnectHint, setReconnectHint] = useState("");

  const terminalThemeForMode = useCallback((mode) => {
    if (mode === "dark") {
      return {
        background: "#0b1420",
        foreground: "#d8e6ff",
        cursor: "#79a6ff",
      };
    }
    return {
      background: "#f6f8fc",
      foreground: "#0f1728",
      cursor: "#1f4f93",
    };
  }, []);

  const writeTerm = useCallback((text) => {
    if (!termRef.current) return;
    termRef.current.write(String(text || ""));
  }, []);

  const writeTermLine = useCallback((text) => {
    if (!termRef.current) return;
    termRef.current.writeln(String(text || ""));
  }, []);

  const sendResize = useCallback(() => {
    const ws = wsRef.current;
    const term = termRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN || !term) return;
    ws.send(
      JSON.stringify({
        type: "resize",
        cols: term.cols,
        rows: term.rows,
      })
    );
  }, []);

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const copySelection = useCallback(async () => {
    try {
      const term = termRef.current;
      if (!term || !term.hasSelection?.()) return false;
      const selectedText = String(term.getSelection?.() || "");
      if (!selectedText) return false;
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(selectedText);
        term.clearSelection?.();
        writeTermLine("[copied selection]");
        return true;
      }
      return false;
    } catch {
      writeTermLine("[copy] clipboard write blocked");
      return false;
    }
  }, [writeTermLine]);

  const pasteFromClipboard = useCallback(async () => {
    try {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        writeTermLine("[paste] terminal is not connected");
        return false;
      }
      if (!navigator.clipboard?.readText) {
        writeTermLine("[paste] clipboard API unavailable");
        return false;
      }
      const text = await navigator.clipboard.readText();
      if (!text) return false;
      ws.send(
        JSON.stringify({
          type: "stdin",
          data: text,
        })
      );
      return true;
    } catch {
      writeTermLine("[paste] clipboard read blocked");
      return false;
    }
  }, [writeTermLine]);

  useEffect(() => {
    let disposed = false;
    let cleanup = () => {};

    const init = async () => {
      try {
        let TerminalCtor;
        let FitAddonCtor;

        if (terminalFactory && terminalFactory.Terminal && terminalFactory.FitAddon) {
          TerminalCtor = terminalFactory.Terminal;
          FitAddonCtor = terminalFactory.FitAddon;
        } else {
          const xterm = await import("xterm");
          const xtermFit = await import("@xterm/addon-fit");
          TerminalCtor = xterm.Terminal;
          FitAddonCtor = xtermFit.FitAddon;
        }

        if (disposed) return;

        const rootTheme =
          document.documentElement.getAttribute("data-theme") === "dark"
            ? "dark"
            : "light";

        const term = new TerminalCtor({
          convertEol: true,
          cursorBlink: true,
          fontFamily: "var(--font-mono)",
          fontSize: 13,
          lineHeight: 1.35,
          theme: terminalThemeForMode(rootTheme),
        });
        const fitAddon = new FitAddonCtor();
        term.loadAddon(fitAddon);
        termRef.current = term;
        fitAddonRef.current = fitAddon;

        if (terminalHostRef.current) {
          term.open(terminalHostRef.current);
          fitAddon.fit();
        }

        const disposable = term.onData((chunk) => {
          const ws = wsRef.current;
          if (!ws || ws.readyState !== WebSocket.OPEN) return;
          ws.send(
            JSON.stringify({
              type: "stdin",
              data: chunk,
            })
          );
        });

        const keyDisposable = term.onKey(({ domEvent }) => {
          const key = String(domEvent?.key || "").toLowerCase();
          const isMac = /mac|iphone|ipad|ipod/i.test(navigator.platform || "");
          const modifierPressed = isMac ? domEvent.metaKey : domEvent.ctrlKey;
          if (modifierPressed && !domEvent.altKey && key === "c") {
            if (term.hasSelection?.()) {
              domEvent.preventDefault();
              void copySelection();
            }
            return;
          }
          if (modifierPressed && !domEvent.altKey && key === "v") {
            domEvent.preventDefault();
            void pasteFromClipboard();
          }
        });

        const applyTerminalTheme = () => {
          const mode =
            document.documentElement.getAttribute("data-theme") === "dark"
              ? "dark"
              : "light";
          const nextTheme = terminalThemeForMode(mode);
          if (typeof term.setOption === "function") {
            term.setOption("theme", nextTheme);
            return;
          }
          if (term.options && typeof term.options === "object") {
            term.options.theme = nextTheme;
          }
        };
        applyTerminalTheme();

        const rootObserver = new MutationObserver(() => {
          applyTerminalTheme();
        });
        rootObserver.observe(document.documentElement, {
          attributes: true,
          attributeFilter: ["data-theme"],
        });

        const onWindowResize = () => {
          fitAddon.fit();
          sendResize();
        };
        window.addEventListener("resize", onWindowResize);

        if (typeof ResizeObserver !== "undefined" && terminalHostRef.current) {
          resizeObserverRef.current = new ResizeObserver(() => {
            fitAddon.fit();
            sendResize();
          });
          resizeObserverRef.current.observe(terminalHostRef.current);
        }

        writeTermLine("Sandbox terminal ready. Click Open to connect.");

        cleanup = () => {
          disposable.dispose();
          keyDisposable.dispose();
          rootObserver.disconnect();
          if (resizeObserverRef.current) {
            resizeObserverRef.current.disconnect();
            resizeObserverRef.current = null;
          }
          window.removeEventListener("resize", onWindowResize);
          if (wsRef.current) {
            manualCloseRef.current = true;
            wsRef.current.close();
            wsRef.current = null;
          }
          term.dispose();
          termRef.current = null;
          fitAddonRef.current = null;
        };
      } catch (err) {
        setError(`Failed to initialize terminal UI: ${String(err)}`);
      }
    };

    init();

    return () => {
      disposed = true;
      clearReconnectTimer();
      cleanup();
    };
  }, [
    clearReconnectTimer,
    copySelection,
    pasteFromClipboard,
    sendResize,
    terminalFactory,
    terminalThemeForMode,
    writeTermLine,
  ]);

  const statusLabel = useMemo(() => {
    if (status === "opening") return "Opening terminal...";
    if (status === "connected") return "Connected";
    if (status === "closed") return "Closed";
    if (status === "error") return "Error";
    return "Idle";
  }, [status]);

  const connect = useCallback(async ({ isReconnect = false } = {}) => {
    if (!openPath) return;
    clearReconnectTimer();
    if (!isReconnect) {
      reconnectAttemptsRef.current = 0;
      setReconnectHint("");
    }
    manualCloseRef.current = false;
    setError("");
    setStatus("opening");
    try {
      const response = await apiFetch(openPath, {
        method: "POST",
      });
      const payload = await readApiPayload(response);
      if (!response.ok) {
        throw new Error(
          payload?.detail ||
            payload?.message ||
            payload?.error ||
            `Failed to open terminal (HTTP ${response.status || "error"})`
        );
      }

      closePathRef.current = String(payload?.close_path || "");
      terminalIdRef.current = String(payload?.terminal_id || "");
      const wsUrl = toWebSocketUrl(String(payload?.websocket_path || ""));
      if (!wsUrl) throw new Error("Missing websocket path");

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setStatus("connected");
        reconnectAttemptsRef.current = 0;
        setReconnectHint("");
        writeTermLine("[connected]");
        fitAddonRef.current?.fit();
        sendResize();
        termRef.current?.focus();
      };
      ws.onclose = () => {
        wsRef.current = null;
        setStatus("closed");
        writeTermLine("[closed]");
        if (!manualCloseRef.current) {
          const nextAttempt = reconnectAttemptsRef.current + 1;
          if (nextAttempt > 5) {
            setReconnectHint("Auto-reconnect stopped after 5 attempts.");
            return;
          }
          reconnectAttemptsRef.current = nextAttempt;
          const delayMs = Math.min(8000, 500 * 2 ** (nextAttempt - 1));
          setReconnectHint(
            `Connection lost. Reconnecting in ${Math.ceil(delayMs / 1000)}s (attempt ${nextAttempt}/5)...`
          );
          reconnectTimerRef.current = window.setTimeout(() => {
            reconnectTimerRef.current = null;
            void connect({ isReconnect: true });
          }, delayMs);
        }
      };
      ws.onerror = () => {
        setStatus("error");
        writeTermLine("[error] websocket connection error");
      };
      ws.onmessage = (event) => {
        let parsed;
        try {
          parsed = JSON.parse(String(event.data || "{}"));
        } catch {
          writeTerm(String(event.data || ""));
          return;
        }
        const type = String(parsed?.type || "");
        if (type === "stdout" || type === "stderr") {
          const data = String(parsed?.data || "");
          if (type === "stderr") {
            writeTerm(`\x1b[31m${data}\x1b[0m`);
          } else {
            writeTerm(data);
          }
          return;
        }
        if (type === "status") {
          writeTermLine(`[status] ${parsed?.status || "unknown"}`);
        }
      };
    } catch (err) {
      setStatus("error");
      setError(String(err));
      writeTermLine(`[error] ${String(err)}`);
      if (!manualCloseRef.current) {
        const nextAttempt = reconnectAttemptsRef.current + 1;
        if (nextAttempt <= 5) {
          reconnectAttemptsRef.current = nextAttempt;
          const delayMs = Math.min(8000, 500 * 2 ** (nextAttempt - 1));
          setReconnectHint(
            `Connect failed. Retrying in ${Math.ceil(delayMs / 1000)}s (attempt ${nextAttempt}/5)...`
          );
          reconnectTimerRef.current = window.setTimeout(() => {
            reconnectTimerRef.current = null;
            void connect({ isReconnect: true });
          }, delayMs);
        }
      }
    }
  }, [clearReconnectTimer, openPath, sendResize, writeTermLine]);

  const disconnect = useCallback(async () => {
    manualCloseRef.current = true;
    clearReconnectTimer();
    reconnectAttemptsRef.current = 0;
    setReconnectHint("");
    const ws = wsRef.current;
    if (ws) {
      ws.close();
      wsRef.current = null;
    }
    const closePath = closePathRef.current;
    if (closePath) {
      await apiFetch(closePath, { method: "DELETE" }).catch(() => undefined);
    }
    closePathRef.current = "";
    terminalIdRef.current = "";
    setStatus("closed");
  }, [clearReconnectTimer]);

  const reconnect = useCallback(async () => {
    await disconnect();
    await connect({ isReconnect: true });
  }, [connect, disconnect]);

  return (
    <section className="terminal-shell">
      <header className="terminal-shell-header">
        <h3>{title || "Sandbox Terminal"}</h3>
        <span className="pill">{statusLabel}</span>
      </header>
      {terminalIdRef.current ? <p className="terminal-meta">Terminal: {terminalIdRef.current}</p> : null}
      {reconnectHint ? <p className="terminal-meta">{reconnectHint}</p> : null}
      {error ? <p className="feedback feedback-error">{error}</p> : null}
      <div className="terminal-actions">
        <button type="button" className="btn btn-subtle" onClick={connect} disabled={status === "opening" || status === "connected"}>
          Open
        </button>
        <button type="button" className="btn btn-subtle" onClick={reconnect} disabled={status === "opening"}>
          Reconnect
        </button>
        <button type="button" className="btn btn-subtle" onClick={disconnect} disabled={status !== "connected" && status !== "opening"}>
          Close
        </button>
      </div>
      <div className="terminal-output" ref={terminalHostRef} data-testid="terminal-output" />
    </section>
  );
}
