import React, { useEffect, useMemo, useState } from "react";
import { AuiIf, ThreadPrimitive } from "@assistant-ui/react";
import { Share2, Trash2 } from "lucide-react";
import { apiFetch, getAppBasePath } from "../api/client";
import { AssistantMessage, UserMessage } from "./MessageParts";
import { Composer } from "./Composer";
import { SandboxLiveStatus } from "./SandboxLiveStatus";
import { ThinkingSidebar } from "./ThinkingSidebar";
import { SandboxTerminalPanel } from "../terminal/SandboxTerminalPanel";
import { SandboxManagementWidget } from "../runtime/SandboxManagementWidget";

function LandingView({ readOnly }) {
  return (
    <div className="landing-view">
      <div className="landing-content">
        <div className="landing-header">
          <h1>How can I help you today?</h1>
          <p className="landing-subtitle">
            Sandboxed LLM Agent ready to execute Python, Shell, and more.
          </p>
        </div>
        
        <div className="landing-composer-wrap">
          <Composer readOnly={readOnly} />
        </div>

        <div className="landing-suggestions">
          <div className="suggestion-card">
            <strong>Analyze Data</strong>
            <p>Run Python to process large datasets and generate charts.</p>
          </div>
          <div className="suggestion-card">
            <strong>Debug System</strong>
            <p>Use Shell tools to inspect logs or troubleshoot infrastructure.</p>
          </div>
          <div className="suggestion-card">
            <strong>Automate Tasks</strong>
            <p>Write scripts to handle repetitive file or API operations.</p>
          </div>
        </div>
      </div>
    </div>
  );
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
  const [showTerminal, setShowTerminal] = useState(false);

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
  
  const applySessionPolicy = async (sessionId, patch) => {
    if (!sessionId || !onUpdateSessionSandboxPolicy) return;
    await onUpdateSessionSandboxPolicy(sessionId, patch);
  };

  return (
    <section className="chat-card">
      <header className={`chat-header ${isMobile ? "chat-header-mobile" : ""}`}>
        <div className="chat-header-main">
          <div>
            {!isMobile ? <h2>{title}</h2> : null}
            {!isMobile ? <p className="chat-subtitle">Session: {session?.session_id || "new"}</p> : null}
          </div>
          <div className="chat-header-actions">
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

        {!readOnly ? (
          <SandboxManagementWidget
            session={session}
            config={config}
            onRefreshStatus={onRefreshSandboxStatus}
            onUpdatePolicy={applySessionPolicy}
            onRunAction={onRunSessionSandboxAction}
            onOpenTerminal={() => setShowTerminal(true)}
            loading={sandboxStatusLoading}
            error={sandboxStatusError}
            canOpenTerminal={canOpenTerminal}
            isMobile={isMobile}
          />
        ) : null}

        <SandboxLiveStatus readOnly={readOnly} />
      </header>

      <ThreadPrimitive.Root className="thread-root">
        <AuiIf condition={(s) => s.thread.isEmpty}>
          <LandingView readOnly={readOnly} />
        </AuiIf>
        
        <AuiIf condition={(s) => !s.thread.isEmpty}>
          <div className={`thread-layout ${showThinking ? "has-thinking" : ""}`}>
            <ThreadPrimitive.Viewport className="thread-viewport">
              <div className="chat-centering-container">
                <ThreadPrimitive.Messages components={threadComponents} />
              </div>
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
        </AuiIf>
      </ThreadPrimitive.Root>
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
                    ? `${apiBase}/sessions/${session.session_id}/sandbox/terminal/open`
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
