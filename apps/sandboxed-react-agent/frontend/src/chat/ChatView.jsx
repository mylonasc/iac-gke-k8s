import React, { useEffect, useMemo, useState } from "react";
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
  onRefreshSandboxStatus,
  onUpdateSessionSandboxPolicy,
  onRunSessionSandboxAction,
  sandboxStatusLoading,
  sandboxStatusError,
  readOnly,
  configError,
  configMessage,
  onShare,
  isMobile,
}) {
  const title = readOnly ? "Shared Thread" : session?.title || "New Chat";
  const [copiedMarkdown, setCopiedMarkdown] = useState(false);
  const [showThinking, setShowThinking] = useState(false);
  const [sessionProfile, setSessionProfile] = useState(
    session?.sandbox_policy?.profile || ""
  );
  const [sessionTemplate, setSessionTemplate] = useState(
    session?.sandbox_policy?.template_name || ""
  );
  const [sessionExecutionModel, setSessionExecutionModel] = useState(
    session?.sandbox_policy?.execution_model || ""
  );

  useEffect(() => {
    setSessionProfile(session?.sandbox_policy?.profile || "");
    setSessionTemplate(session?.sandbox_policy?.template_name || "");
    setSessionExecutionModel(session?.sandbox_policy?.execution_model || "");
  }, [session?.sandbox_policy, session?.session_id]);

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

  const sessionStatus = session?.sandbox_status || null;
  const workspace = sessionStatus?.workspace_status?.workspace || null;
  const provisioningPending = sessionStatus?.workspace_status?.provisioning_pending;

  const applySessionPolicy = async () => {
    if (!session?.session_id || !onUpdateSessionSandboxPolicy) return;
    const patch = {
      profile: sessionProfile || null,
      template_name: sessionTemplate || null,
      execution_model: sessionExecutionModel || null,
    };
    await onUpdateSessionSandboxPolicy(session.session_id, patch);
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
              <span className="pill">
                Profile: {config?.sandbox_profile || "persistent_workspace"}
              </span>
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

      {!readOnly ? (
        <div className="sandbox-status-strip">
          <div className="sandbox-status-row">
            <span className="pill">Workspace: {workspace?.status || "none"}</span>
            <span className="pill">
              Pending: {provisioningPending ? "yes" : "no"}
            </span>
            <span className="pill">
              Effective profile: {sessionStatus?.effective?.runtime?.profile || config?.sandbox_profile}
            </span>
            <span className="pill">
              Effective template: {sessionStatus?.effective?.runtime?.template_name || config?.sandbox_template_name}
            </span>
            <button
              type="button"
              className="btn btn-subtle tiny"
              disabled={!session?.session_id || sandboxStatusLoading}
              onClick={() => onRefreshSandboxStatus?.(session.session_id)}
            >
              {sandboxStatusLoading ? "Refreshing..." : "Refresh status"}
            </button>
            <button
              type="button"
              className="btn btn-subtle tiny"
              disabled={!session?.session_id || sandboxStatusLoading}
              onClick={() =>
                onRunSessionSandboxAction?.(session.session_id, "release_lease", {
                  wait: false,
                })
              }
            >
              Release lease
            </button>
            <button
              type="button"
              className="btn btn-subtle tiny"
              disabled={!session?.session_id || sandboxStatusLoading}
              onClick={() =>
                onRunSessionSandboxAction?.(session.session_id, "reconcile_workspace", {
                  wait: false,
                })
              }
            >
              Reconcile workspace
            </button>
          </div>
          <div className="sandbox-policy-row">
            <label>
              Session profile
              <select value={sessionProfile} onChange={(event) => setSessionProfile(event.target.value)}>
                <option value="">(inherit)</option>
                <option value="persistent_workspace">persistent_workspace</option>
                <option value="transient">transient</option>
              </select>
            </label>
            <label>
              Session template
              <input
                type="text"
                value={sessionTemplate}
                onChange={(event) => setSessionTemplate(event.target.value)}
                placeholder="(inherit)"
              />
            </label>
            <label>
              Session execution model
              <select
                value={sessionExecutionModel}
                onChange={(event) => setSessionExecutionModel(event.target.value)}
              >
                <option value="">(inherit)</option>
                <option value="session">session</option>
                <option value="ephemeral">ephemeral</option>
              </select>
            </label>
            <button
              type="button"
              className="btn btn-primary tiny"
              disabled={!session?.session_id || sandboxStatusLoading}
              onClick={applySessionPolicy}
            >
              Apply session policy
            </button>
          </div>
          {sandboxStatusError ? <p className="feedback feedback-error">{sandboxStatusError}</p> : null}
        </div>
      ) : null}

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
