import React, { useEffect, useMemo, useState } from "react";
import { AuiIf, ThreadPrimitive } from "@assistant-ui/react";
import { Share2, Trash2 } from "lucide-react";
import { apiFetch, getAppBasePath } from "../api/client";
import { AssistantMessage, UserMessage } from "./MessageParts";
import { Composer } from "./Composer";
import { SandboxLiveStatus } from "./SandboxLiveStatus";
import { ThinkingSidebar } from "./ThinkingSidebar";
import { SandboxTerminalPanel } from "../terminal/SandboxTerminalPanel";

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
  canOpenTerminal = true,
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
  const [showSandboxControls, setShowSandboxControls] = useState(false);
  const [showTerminal, setShowTerminal] = useState(false);
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
  }, [session?.session_id]);

  useEffect(() => {
    if (sandboxStatusError) {
      setShowSandboxControls(true);
    }
  }, [sandboxStatusError]);

  useEffect(() => {
    if (!showSandboxControls) return undefined;
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        setShowSandboxControls(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [showSandboxControls]);

  useEffect(() => {
    const onOpenTerminal = (event) => {
      if (!canOpenTerminal) return;
      const detail = event?.detail || {};
      const targetSessionId = typeof detail.sessionId === "string" ? detail.sessionId : "";
      if (!session?.session_id || (targetSessionId && targetSessionId !== session.session_id)) {
        return;
      }
      setShowTerminal(true);
    };
    window.addEventListener("sra-open-session-terminal", onOpenTerminal);
    return () => window.removeEventListener("sra-open-session-terminal", onOpenTerminal);
  }, [canOpenTerminal, session?.session_id]);

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
  const runtimeResolution = sessionStatus?.runtime_resolution || null;
  const activeRuntime = sessionStatus?.active_runtime || null;
  const availableSandboxes = sessionStatus?.available_sandboxes || {};
  const availableProfiles =
    Array.isArray(availableSandboxes.profiles) && availableSandboxes.profiles.length > 0
      ? availableSandboxes.profiles
      : ["persistent_workspace", "transient"];
  const availableExecutionModels =
    Array.isArray(availableSandboxes.execution_models) &&
    availableSandboxes.execution_models.length > 0
      ? availableSandboxes.execution_models
      : ["session", "ephemeral"];
  const availableTemplateNames = useMemo(() => {
    const names = new Set();
    const templates = Array.isArray(availableSandboxes.templates)
      ? availableSandboxes.templates
      : [];
    templates.forEach((entry) => {
      if (!entry || typeof entry.name !== "string") return;
      const name = entry.name.trim();
      if (name) names.add(name);
    });
    [
      session?.sandbox_policy?.template_name,
      sessionStatus?.effective?.runtime?.template_name,
      config?.sandbox_template_name,
    ].forEach((value) => {
      if (typeof value !== "string") return;
      const name = value.trim();
      if (name) names.add(name);
    });
    return Array.from(names).sort();
  }, [
    availableSandboxes.templates,
    config?.sandbox_template_name,
    session?.sandbox_policy?.template_name,
    sessionStatus?.effective?.runtime?.template_name,
  ]);
  const persistentBaseTemplates = useMemo(() => {
    const values = Array.isArray(availableSandboxes?.persistent_workspace?.base_templates)
      ? availableSandboxes.persistent_workspace.base_templates
      : [];
    const unique = new Set();
    values.forEach((entry) => {
      if (typeof entry !== "string") return;
      const value = entry.trim();
      if (!value) return;
      unique.add(value);
    });
    return Array.from(unique);
  }, [availableSandboxes?.persistent_workspace?.base_templates]);
  const persistentPrimaryBaseTemplate =
    typeof availableSandboxes?.persistent_workspace?.primary_base_template === "string"
      ? availableSandboxes.persistent_workspace.primary_base_template.trim()
      : "";
  const persistentTemplateHint =
    persistentBaseTemplates.length > 0
      ? persistentBaseTemplates.join(", ")
      : "not reported by backend";
  const workspace = sessionStatus?.workspace_status?.workspace || null;
  const provisioningPending = sessionStatus?.workspace_status?.provisioning_pending;
  const currentSandboxProfile =
    activeRuntime?.profile ||
    sessionStatus?.effective?.runtime?.profile ||
    config?.sandbox_profile ||
    "persistent_workspace";
  const currentSandboxTemplate =
    activeRuntime?.template_name ||
    sessionStatus?.effective?.runtime?.template_name ||
    config?.sandbox_template_name ||
    "python-runtime-template-small";
  const currentExecutionModel =
    activeRuntime?.execution_model ||
    sessionStatus?.effective?.lifecycle?.execution_model ||
    "session";
  const fallbackActive = Boolean(
    activeRuntime?.fallback_active || runtimeResolution?.fallback_active
  );
  const fallbackNotice =
    typeof runtimeResolution?.notice === "string" && runtimeResolution.notice
      ? runtimeResolution.notice
      : "Persistent sandbox is unavailable; transient fallback is active.";

  const applySessionPolicy = async () => {
    if (!session?.session_id || !onUpdateSessionSandboxPolicy) return;
    const patch = {
      profile: sessionProfile || null,
      template_name: sessionTemplate || null,
      execution_model: sessionExecutionModel || null,
    };
    await onUpdateSessionSandboxPolicy(session.session_id, patch);
  };

  const sandboxControlsPanel = (
    <div className="sandbox-controls-panel">
      <div className="sandbox-status-row">
        <span className="pill">Workspace: {workspace?.status || "none"}</span>
        <span className="pill">Pending: {provisioningPending ? "yes" : "no"}</span>
        <span className="pill">
          Effective profile: {sessionStatus?.effective?.runtime?.profile || config?.sandbox_profile}
        </span>
        <span className={`pill ${fallbackActive ? "pill-warning" : "pill-success"}`}>
          Active profile: {currentSandboxProfile}
        </span>
        <span className="pill">
          Effective template: {sessionStatus?.effective?.runtime?.template_name || config?.sandbox_template_name}
        </span>
        <span className="pill">Active template: {currentSandboxTemplate}</span>
        <span className="pill">Execution: {currentExecutionModel}</span>
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
        {canOpenTerminal ? (
          <button
            type="button"
            className="btn btn-subtle tiny"
            disabled={!session?.session_id}
            onClick={() => setShowTerminal(true)}
          >
            Open terminal
          </button>
        ) : null}
      </div>
      <div className="sandbox-policy-row">
        <p className="sandbox-policy-hint">
          <strong>Persistent base templates:</strong> {persistentTemplateHint}
          {persistentPrimaryBaseTemplate ? ` (primary: ${persistentPrimaryBaseTemplate})` : ""}
        </p>
        <label>
          Session profile
          <select value={sessionProfile} onChange={(event) => setSessionProfile(event.target.value)}>
            <option value="">(inherit)</option>
            {availableProfiles.map((profile) => (
              <option key={profile} value={profile}>
                {profile}
              </option>
            ))}
          </select>
        </label>
        <label>
          Session template
          <select value={sessionTemplate} onChange={(event) => setSessionTemplate(event.target.value)}>
            <option value="">(inherit)</option>
            {availableTemplateNames.map((templateName) => (
              <option key={templateName} value={templateName}>
                {templateName}
              </option>
            ))}
          </select>
        </label>
        <label>
          Session execution model
          <select
            value={sessionExecutionModel}
            onChange={(event) => setSessionExecutionModel(event.target.value)}
          >
            <option value="">(inherit)</option>
            {availableExecutionModels.map((executionModel) => (
              <option key={executionModel} value={executionModel}>
                {executionModel}
              </option>
            ))}
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
  );

  return (
    <section className="chat-card">
      <header className={`chat-header ${isMobile ? "chat-header-mobile" : ""}`}>
        <div className="chat-header-main">
          <div>
            {!isMobile ? <h2>{title}</h2> : null}
            {!isMobile ? <p className="chat-subtitle">Session: {session?.session_id || "new"}</p> : null}
            {!readOnly && !isMobile ? (
              <div className="chat-meta-row">
                <span className="pill">Model: {config?.model || "gpt-4o-mini"}</span>
                <span className="pill">
                  Default profile: {config?.sandbox_profile || "persistent_workspace"}
                </span>
                <span className="pill">Default template: {config?.sandbox_template_name || "default"}</span>
                <span className={`pill ${fallbackActive ? "pill-warning" : "pill-success"}`}>
                  Sandbox now: {currentSandboxProfile}
                </span>
                <span className="pill">Template now: {currentSandboxTemplate}</span>
                <span className="pill">Execution: {currentExecutionModel}</span>
              </div>
            ) : null}
          </div>
          <div className="chat-header-actions">
            {!readOnly ? <ClaimBadge session={session} /> : null}
            {!readOnly ? (
              <button
                type="button"
                className="btn btn-subtle"
                onClick={() => setShowSandboxControls(true)}
              >
                Advanced sandbox controls
              </button>
            ) : null}
            {!readOnly && canOpenTerminal ? (
              <button
                type="button"
                className="btn btn-subtle"
                disabled={!session?.session_id}
                onClick={() => setShowTerminal(true)}
              >
                Terminal
              </button>
            ) : null}
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
        </div>
        {!readOnly && fallbackActive ? (
          <div className="sandbox-fallback-banner" role="status" aria-live="polite">
            <strong>Persistent fallback active.</strong> {fallbackNotice}
          </div>
        ) : null}
        {!readOnly ? (
          <div className="sandbox-active-row">
            <span className={`pill ${fallbackActive ? "pill-warning" : "pill-success"}`}>
              Current profile: {currentSandboxProfile}
            </span>
            <span className="pill">Current template: {currentSandboxTemplate}</span>
            <span className="pill">Execution: {currentExecutionModel}</span>
          </div>
        ) : null}
        <SandboxLiveStatus readOnly={readOnly} />
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
      {!readOnly && showSandboxControls ? (
        <div
          className="sandbox-tools-backdrop"
          role="presentation"
          onClick={() => setShowSandboxControls(false)}
        >
          <section
            className="sandbox-tools-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Advanced sandbox controls"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="sandbox-tools-header">
              <h3>Advanced sandbox controls</h3>
              <button
                type="button"
                className="btn btn-subtle tiny"
                onClick={() => setShowSandboxControls(false)}
              >
                Close
              </button>
            </div>
            <div className="sandbox-tools-body">{sandboxControlsPanel}</div>
          </section>
        </div>
      ) : null}
      {!readOnly && canOpenTerminal && showTerminal ? (
        <div
          className="sandbox-tools-backdrop"
          role="presentation"
          onClick={() => setShowTerminal(false)}
        >
          <section
            className="sandbox-tools-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Sandbox terminal"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="sandbox-tools-header">
              <h3>Sandbox terminal</h3>
              <button
                type="button"
                className="btn btn-subtle tiny"
                onClick={() => setShowTerminal(false)}
              >
                Close
              </button>
            </div>
            <div className="sandbox-tools-body">
              <SandboxTerminalPanel
                title="Interactive shell"
                openPath={
                  session?.session_id
                    ? `/api/sessions/${session.session_id}/sandbox/terminal/open`
                    : ""
                }
              />
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}
