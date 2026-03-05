import React, { useEffect, useMemo, useState } from "react";

const DEFAULT_API_BASE = `${window.location.pathname.replace(/\/$/, "")}/api`;

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [configLoading, setConfigLoading] = useState(false);
  const [configSaving, setConfigSaving] = useState(false);
  const [configError, setConfigError] = useState("");
  const [configMessage, setConfigMessage] = useState("");
  const [sessionId, setSessionId] = useState(() => localStorage.getItem("sandboxed-agent-session") || "");
  const [config, setConfig] = useState({
    model: "gpt-4o-mini",
    max_tool_calls_per_turn: 4,
    sandbox_mode: "local",
    sandbox_api_url: "",
    sandbox_template_name: "python-runtime-template",
    sandbox_namespace: "alt-default",
    sandbox_server_port: 8888,
    sandbox_max_output_chars: 6000,
    sandbox_local_timeout_seconds: 20,
  });

  const apiBase = useMemo(() => {
    const configured = import.meta.env.VITE_API_BASE;
    return configured && configured.length > 0 ? configured : DEFAULT_API_BASE;
  }, []);

  async function loadConfig() {
    setConfigLoading(true);
    setConfigError("");
    setConfigMessage("");
    try {
      const response = await fetch(`${apiBase}/config`);
      if (!response.ok) {
        throw new Error(`Failed to load config: ${response.status}`);
      }
      const data = await response.json();
      setConfig({
        model: data.model || "gpt-4o-mini",
        max_tool_calls_per_turn: Number(data.max_tool_calls_per_turn ?? 4),
        sandbox_mode: data?.sandbox?.mode || "local",
        sandbox_api_url: data?.sandbox?.api_url || "",
        sandbox_template_name: data?.sandbox?.template_name || "python-runtime-template",
        sandbox_namespace: data?.sandbox?.namespace || "alt-default",
        sandbox_server_port: Number(data?.sandbox?.server_port ?? 8888),
        sandbox_max_output_chars: Number(data?.sandbox?.max_output_chars ?? 6000),
        sandbox_local_timeout_seconds: Number(data?.sandbox?.local_timeout_seconds ?? 20),
      });
    } catch (error) {
      setConfigError(String(error));
    } finally {
      setConfigLoading(false);
    }
  }

  useEffect(() => {
    loadConfig();
  }, [apiBase]);

  async function handleSaveConfig(event) {
    event.preventDefault();
    setConfigSaving(true);
    setConfigError("");
    setConfigMessage("");

    try {
      const payload = {
        model: config.model,
        max_tool_calls_per_turn: Number(config.max_tool_calls_per_turn),
        sandbox_mode: config.sandbox_mode,
        sandbox_api_url: config.sandbox_api_url,
        sandbox_template_name: config.sandbox_template_name,
        sandbox_namespace: config.sandbox_namespace,
        sandbox_server_port: Number(config.sandbox_server_port),
        sandbox_max_output_chars: Number(config.sandbox_max_output_chars),
        sandbox_local_timeout_seconds: Number(config.sandbox_local_timeout_seconds),
      };

      const response = await fetch(`${apiBase}/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();

      if (!response.ok) {
        const detail = data?.detail || `Failed to save config: ${response.status}`;
        throw new Error(detail);
      }

      setConfigMessage("Configuration saved.");
      setConfig({
        model: data.model || payload.model,
        max_tool_calls_per_turn: Number(data.max_tool_calls_per_turn ?? payload.max_tool_calls_per_turn),
        sandbox_mode: data?.sandbox?.mode || payload.sandbox_mode,
        sandbox_api_url: data?.sandbox?.api_url || payload.sandbox_api_url,
        sandbox_template_name: data?.sandbox?.template_name || payload.sandbox_template_name,
        sandbox_namespace: data?.sandbox?.namespace || payload.sandbox_namespace,
        sandbox_server_port: Number(data?.sandbox?.server_port ?? payload.sandbox_server_port),
        sandbox_max_output_chars: Number(data?.sandbox?.max_output_chars ?? payload.sandbox_max_output_chars),
        sandbox_local_timeout_seconds: Number(data?.sandbox?.local_timeout_seconds ?? payload.sandbox_local_timeout_seconds),
      });
    } catch (error) {
      setConfigError(String(error));
    } finally {
      setConfigSaving(false);
    }
  }

  async function handleSend(event) {
    event.preventDefault();
    if (!input.trim() || loading) {
      return;
    }

    const userMessage = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMessage }]);
    setLoading(true);

    try {
      const response = await fetch(`${apiBase}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMessage, session_id: sessionId || null }),
      });
      const data = await response.json();

      if (data.session_id && data.session_id !== sessionId) {
        setSessionId(data.session_id);
        localStorage.setItem("sandboxed-agent-session", data.session_id);
      }

      const toolMeta = Array.isArray(data.tool_calls) && data.tool_calls.length > 0
        ? `\n\n[tools used: ${data.tool_calls.map((t) => t.tool).join(", ")}]`
        : "";

      const assistantMessage = data.reply || data.error || "No response from agent.";
      setMessages((prev) => [...prev, { role: "assistant", content: `${assistantMessage}${toolMeta}` }]);
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Request failed: ${String(error)}` },
      ]);
    } finally {
      setLoading(false);
    }
  }

  async function handleResetSession() {
    if (!sessionId) {
      return;
    }
    await fetch(`${apiBase}/sessions/${sessionId}/reset`, { method: "POST" });
    localStorage.removeItem("sandboxed-agent-session");
    setSessionId("");
    setMessages([]);
  }

  return (
    <main style={{ maxWidth: 920, margin: "0 auto", padding: "2rem", fontFamily: "sans-serif" }}>
      <h1>Sandboxed React Agent</h1>
      <p>API base: <code>{apiBase}</code></p>
      <p>Session: <code>{sessionId || "new"}</code></p>

      <section style={{ border: "1px solid #ddd", borderRadius: 8, padding: "1rem", marginBottom: "1rem" }}>
        <h2 style={{ marginTop: 0 }}>Backend Configuration</h2>
        <form onSubmit={handleSaveConfig} style={{ display: "grid", gap: "0.6rem" }}>
          <label>
            Model
            <input
              type="text"
              value={config.model}
              onChange={(event) => setConfig((prev) => ({ ...prev, model: event.target.value }))}
              disabled={configLoading || configSaving}
            />
          </label>
          <label>
            Max tool calls per turn
            <input
              type="number"
              min={1}
              max={20}
              value={config.max_tool_calls_per_turn}
              onChange={(event) => setConfig((prev) => ({ ...prev, max_tool_calls_per_turn: event.target.value }))}
              disabled={configLoading || configSaving}
            />
          </label>
          <label>
            Sandbox mode
            <select
              value={config.sandbox_mode}
              onChange={(event) => setConfig((prev) => ({ ...prev, sandbox_mode: event.target.value }))}
              disabled={configLoading || configSaving}
            >
              <option value="local">local</option>
              <option value="cluster">cluster</option>
            </select>
          </label>
          <label>
            Sandbox API URL
            <input
              type="text"
              value={config.sandbox_api_url}
              onChange={(event) => setConfig((prev) => ({ ...prev, sandbox_api_url: event.target.value }))}
              disabled={configLoading || configSaving}
            />
          </label>
          <label>
            Sandbox template name
            <input
              type="text"
              value={config.sandbox_template_name}
              onChange={(event) => setConfig((prev) => ({ ...prev, sandbox_template_name: event.target.value }))}
              disabled={configLoading || configSaving}
            />
          </label>
          <label>
            Sandbox namespace
            <input
              type="text"
              value={config.sandbox_namespace}
              onChange={(event) => setConfig((prev) => ({ ...prev, sandbox_namespace: event.target.value }))}
              disabled={configLoading || configSaving}
            />
          </label>
          <label>
            Sandbox server port
            <input
              type="number"
              min={1}
              max={65535}
              value={config.sandbox_server_port}
              onChange={(event) => setConfig((prev) => ({ ...prev, sandbox_server_port: event.target.value }))}
              disabled={configLoading || configSaving}
            />
          </label>
          <label>
            Max output chars
            <input
              type="number"
              min={100}
              max={100000}
              value={config.sandbox_max_output_chars}
              onChange={(event) => setConfig((prev) => ({ ...prev, sandbox_max_output_chars: event.target.value }))}
              disabled={configLoading || configSaving}
            />
          </label>
          <label>
            Local timeout seconds
            <input
              type="number"
              min={1}
              max={600}
              value={config.sandbox_local_timeout_seconds}
              onChange={(event) => setConfig((prev) => ({ ...prev, sandbox_local_timeout_seconds: event.target.value }))}
              disabled={configLoading || configSaving}
            />
          </label>

          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button type="button" onClick={loadConfig} disabled={configLoading || configSaving}>
              {configLoading ? "Loading..." : "Reload Config"}
            </button>
            <button type="submit" disabled={configLoading || configSaving}>
              {configSaving ? "Saving..." : "Save Config"}
            </button>
          </div>

          {configError ? <p style={{ color: "#b00020", margin: 0 }}>{configError}</p> : null}
          {configMessage ? <p style={{ color: "#1b5e20", margin: 0 }}>{configMessage}</p> : null}
        </form>
      </section>

      <section style={{ border: "1px solid #ddd", borderRadius: 8, padding: "1rem", minHeight: 320 }}>
        {messages.length === 0 ? <p>No messages yet.</p> : null}
        {messages.map((message, idx) => (
          <div key={idx} style={{ marginBottom: "1rem" }}>
            <strong>{message.role === "user" ? "You" : "Agent"}:</strong>
            <pre style={{ whiteSpace: "pre-wrap", margin: "0.35rem 0 0 0" }}>{message.content}</pre>
          </div>
        ))}
      </section>

      <form onSubmit={handleSend} style={{ marginTop: "1rem", display: "grid", gap: "0.5rem" }}>
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          rows={5}
          placeholder="Ask the agent to run Python/shell in sandbox, debug code, etc."
          disabled={loading}
        />
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button type="submit" disabled={loading}>{loading ? "Running..." : "Send"}</button>
          <button type="button" onClick={handleResetSession} disabled={!sessionId || loading}>Reset Session</button>
        </div>
      </form>
    </main>
  );
}

export default App;
