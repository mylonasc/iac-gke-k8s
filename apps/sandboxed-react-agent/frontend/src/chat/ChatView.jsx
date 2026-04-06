import React, { useMemo, useState } from "react";
import { AuiIf, ThreadPrimitive } from "@assistant-ui/react";
import { Share2, Trash2 } from "lucide-react";
import { apiFetch, getAppBasePath } from "../api/client";
import { AssistantMessage, UserMessage } from "./MessageParts";
import { Composer } from "./Composer";
import { ThinkingSidebar } from "./ThinkingSidebar";

function ClaimBadge({ session }) {
  const sandbox = session?.sandbox || {};
  const activeClaim = sandbox.has_active_claim ? sandbox.claim_name : null;
  const leaseStatus = sandbox?.status || null;
  let text = "Claim: none";
  let className = "pill";

  if (leaseStatus === "pending") {
    text = "Claim: acquiring";
    className = "pill pill-running";
  } else if (leaseStatus === "ready" && activeClaim) {
    text = `Claim ready: ${activeClaim}`;
    className = "pill pill-success";
  } else if (leaseStatus) {
    text = `Claim status: ${leaseStatus}`;
    className = "pill pill-warning";
  }

  return <span className={className}>{text}</span>;
}

export function ChatView({
  apiBase,
  session,
  config,
  onResetSession,
  readOnly,
  configError,
  configMessage,
  onShare,
  isMobile,
}) {
  const title = readOnly ? "Shared Thread" : session?.title || "New Chat";
  const [copiedMarkdown, setCopiedMarkdown] = useState(false);
  const [showThinking, setShowThinking] = useState(false);

  const threadComponents = useMemo(
    () => ({ UserMessage, AssistantMessage }),
    []
  );

  const shareMarkdown = async () => {
    if (!session?.session_id) return;
    const response = await apiFetch(`${apiBase}/sessions/${session.session_id}/share`, {
      method: "POST",
    });
    if (!response.ok) return;
    const data = await response.json();
    const markdownUrl = `${window.location.origin}${getAppBasePath()}/api/public/${data.share_id}/markdown`;
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(markdownUrl);
    }
    setCopiedMarkdown(true);
    window.setTimeout(() => setCopiedMarkdown(false), 1500);
  };

  return (
    <section className="chat-card">
      <header className={`chat-header ${isMobile ? "chat-header-mobile" : ""}`}>
        <div>
          {!isMobile ? <h2>{title}</h2> : null}
          {!isMobile ? <p className="chat-subtitle">Session: {session?.session_id || "new"}</p> : null}
          {!readOnly && !isMobile ? (
            <div className="chat-meta-row">
              <span className="pill">Model: {config?.model || "gpt-4o-mini"}</span>
              <span className="pill">Runtime: {config?.sandbox_template_name || "default"}</span>
            </div>
          ) : null}
        </div>
        <div className="chat-header-actions">
          {!readOnly ? <ClaimBadge session={session} /> : null}
          {!readOnly ? (
            <button
              type="button"
              className="btn btn-subtle"
              onClick={() => setShowThinking((prev) => !prev)}
            >
              {showThinking ? "Hide thinking" : "Show thinking"}
            </button>
          ) : null}
          {!readOnly && !isMobile ? (
            <button
              type="button"
              className="btn btn-subtle icon-only"
              onClick={shareMarkdown}
              title="Share as markdown"
              aria-label="Share as markdown"
            >
              <Share2 className="icon-svg" aria-hidden="true" strokeWidth={2} />
            </button>
          ) : null}
          {!readOnly && !isMobile && onShare ? (
            <button
              type="button"
              className="btn btn-subtle icon-only"
              onClick={() => onShare(session?.session_id)}
              title="Share"
              aria-label="Share"
            >
              <Share2 className="icon-svg" aria-hidden="true" strokeWidth={2} />
            </button>
          ) : null}
          {!readOnly && copiedMarkdown ? <span className="pill pill-success">Copied markdown URL</span> : null}
          {!readOnly ? (
            <button
              type="button"
              className="btn btn-subtle icon-only"
              onClick={() => onResetSession(session?.session_id)}
              disabled={!session?.session_id}
              title="Delete thread"
              aria-label="Delete thread"
            >
              <Trash2 className="icon-svg" aria-hidden="true" strokeWidth={2} />
            </button>
          ) : null}
        </div>
      </header>

      <ThreadPrimitive.Root className="thread-root">
        <div className={`thread-layout ${showThinking ? "has-thinking" : ""}`}>
          <ThreadPrimitive.Viewport className="thread-viewport">
            <AuiIf condition={(s) => s.thread.isEmpty}>
              <div className="empty-state">Start by sending a message.</div>
            </AuiIf>
            <ThreadPrimitive.Messages components={threadComponents} />
            <ThreadPrimitive.ScrollToBottom className="btn btn-subtle jump-button">
              Jump to latest
            </ThreadPrimitive.ScrollToBottom>
          </ThreadPrimitive.Viewport>
          {!readOnly && showThinking ? <ThinkingSidebar /> : null}
        </div>
        {!readOnly && (configError || configMessage) ? (
          <div className={configError ? "quick-config-feedback feedback-error" : "quick-config-feedback feedback-success"}>
            {configError || configMessage}
          </div>
        ) : null}
        <Composer readOnly={readOnly} />
      </ThreadPrimitive.Root>
    </section>
  );
}
