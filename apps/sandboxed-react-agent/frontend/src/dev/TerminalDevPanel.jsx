import React from "react";
import { DEFAULT_API_BASE } from "../api/client";
import { SandboxTerminalPanel } from "../terminal/SandboxTerminalPanel";

export function TerminalDevPanel({ sessionId }) {
  if (!sessionId) {
    return (
      <section className="terminal-dev-empty">
        <h2>Terminal Dev Panel</h2>
        <p>Create or select a session first, then reopen this panel.</p>
      </section>
    );
  }

  return (
    <section className="terminal-dev-panel">
      <h2>Terminal Dev Panel</h2>
      <p className="terminal-meta">Session: {sessionId}</p>
      <SandboxTerminalPanel
        title="Dev terminal"
        openPath={`${DEFAULT_API_BASE}/dev/sessions/${sessionId}/terminal/open`}
      />
    </section>
  );
}
