import React, { useMemo } from "react";
import { useAssistantState } from "@assistant-ui/react";

function formatToken(value) {
  return String(value || "")
    .split(/[_\-.]+/)
    .filter(Boolean)
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}

function payloadSummary(payload) {
  if (!payload || typeof payload !== "object") return "";
  const parts = [];
  if (typeof payload.notice === "string" && payload.notice.trim()) {
    parts.push(payload.notice.trim());
  }
  if (typeof payload.claim_name === "string" && payload.claim_name.trim()) {
    parts.push(`claim ${payload.claim_name.trim()}`);
  }
  if (typeof payload.lease_id === "string" && payload.lease_id.trim()) {
    parts.push(`lease ${payload.lease_id.trim()}`);
  }
  if (typeof payload.error === "string" && payload.error.trim()) {
    parts.push(payload.error.trim());
  }
  return parts.join(" - ");
}

export function SandboxLiveStatus({ readOnly = false }) {
  const rawThreadState = useAssistantState((state) => state?.thread?.state);
  const threadState =
    rawThreadState && typeof rawThreadState === "object" ? rawThreadState : null;
  const live =
    threadState?.sandbox_live && typeof threadState.sandbox_live === "object"
      ? threadState.sandbox_live
      : null;
  const updates = Array.isArray(threadState?.sandbox_updates)
    ? threadState.sandbox_updates
    : [];

  const recent = useMemo(() => updates.slice(-5).reverse(), [updates]);

  if (readOnly || (!live && recent.length === 0)) return null;

  return (
    <div className="sandbox-live-panel" role="status" aria-live="polite">
      <div className="sandbox-live-header">
        <span className="pill">Sandbox stream</span>
        {live ? (
          <>
            <span className="pill">{formatToken(live.stage) || "Unknown stage"}</span>
            <span className="pill">{formatToken(live.status) || "Info"}</span>
            <span className="pill">{formatToken(live.code) || "Updated"}</span>
          </>
        ) : null}
      </div>
      {recent.length > 0 ? (
        <ul className="sandbox-live-list">
          {recent.map((entry) => {
            const summary = payloadSummary(entry?.payload);
            const line = `${formatToken(entry?.stage) || "Sandbox"}: ${formatToken(entry?.code) || "Updated"}`;
            return (
              <li key={entry?.id || `${entry?.timestamp || "t"}-${entry?.code || "u"}`}>
                <span className="sandbox-live-item-meta">{line}</span>
                {summary ? <span>{summary}</span> : null}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="sandbox-live-empty">Waiting for sandbox activity...</p>
      )}
    </div>
  );
}
