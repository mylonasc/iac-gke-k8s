import React, { useCallback, useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import {
  AssistantRuntimeProvider,
  AttachmentPrimitive,
  AuiIf,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAssistantState,
  useMessagePartImage,
  useMessagePartText,
  useAssistantTransportRuntime,
} from "@assistant-ui/react";
import "katex/dist/katex.min.css";
import "./App.css";

const getAppBasePath = () => {
  const path = window.location.pathname;
  const strippedPublic = path.replace(/\/public\/[^/]+\/?$/, "");
  const normalized = strippedPublic.replace(/\/$/, "");
  return normalized || "";
};

const DEFAULT_API_BASE = `${getAppBasePath()}/api`;
const gfmPlugin = typeof remarkGfm === "function" ? remarkGfm : remarkGfm?.default;
const mathPlugin = typeof remarkMath === "function" ? remarkMath : remarkMath?.default;
const katexPlugin = typeof rehypeKatex === "function" ? rehypeKatex : rehypeKatex?.default;
const APP_BASE_PATH = getAppBasePath();
const THEME_STORAGE_KEY = "sandboxed-react-agent-theme";
const AUTH_TOKEN_STORAGE_KEY =
  import.meta.env.VITE_AUTH_TOKEN_STORAGE_KEY || "sandboxed-react-agent-auth-token";
const SANDBOX_TEMPLATES = [
  {
    value: "python-runtime-template-small",
    label: "Small Sandbox",
    description: "Low-footprint runtime for better pod packing and lower startup contention.",
  },
  {
    value: "python-runtime-template",
    label: "Balanced Sandbox",
    description: "Default runtime for standard tasks.",
  },
  {
    value: "python-runtime-template-large",
    label: "Large Sandbox",
    description: "Higher CPU and memory request for heavier tasks.",
  },
  {
    value: "python-runtime-template-pydata",
    label: "PyData Sandbox",
    description: "Extended runtime with numpy/scipy/pandas/polars/matplotlib/yfinance.",
  },
];

const resolveAppUrl = (url) => {
  if (typeof url !== "string" || !url) return url;
  if (url.startsWith("http://") || url.startsWith("https://") || url.startsWith("data:")) {
    return url;
  }
  if (url.startsWith("/api/")) {
    return APP_BASE_PATH ? `${APP_BASE_PATH}${url}` : url;
  }
  return url;
};

const getMediaQueryMatches = (query, fallback = false) => {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return fallback;
  }
  return window.matchMedia(query).matches;
};

const getAuthToken = () => {
  if (typeof window === "undefined") return "";
  const staticToken = import.meta.env.VITE_AUTH_TOKEN || "";
  if (staticToken) return staticToken;
  if (typeof window.__AUTH_TOKEN__ === "string" && window.__AUTH_TOKEN__.trim()) {
    return window.__AUTH_TOKEN__.trim();
  }
  const localToken = window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) || "";
  if (localToken.trim()) return localToken.trim();
  const sessionToken = window.sessionStorage.getItem(AUTH_TOKEN_STORAGE_KEY) || "";
  return sessionToken.trim();
};

const withAuthHeaders = (headersInit) => {
  const headers = new Headers(headersInit || {});
  const token = getAuthToken();
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return headers;
};

const apiFetch = (input, init = {}) => {
  return fetch(input, {
    ...init,
    credentials: init.credentials || "include",
    headers: withAuthHeaders(init.headers),
  });
};

const fileToDataUrl = (file) =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = (error) => reject(error);
    reader.readAsDataURL(file);
  });

const imageAttachmentAdapter = {
  accept: "image/*",
  async add({ file }) {
    return {
      id: `${file.name}-${Date.now()}`,
      type: "image",
      name: file.name,
      contentType: file.type,
      file,
      status: { type: "requires-action", reason: "composer-send" },
    };
  },
  async send(attachment) {
    return {
      ...attachment,
      status: { type: "complete" },
      content: [
        {
          type: "image",
          image: await fileToDataUrl(attachment.file),
        },
      ],
    };
  },
  async remove() {},
};

const normalizeMessage = (message, index) => {
  if (!message || typeof message !== "object") return null;
  const role = message.role === "assistant" ? "assistant" : "user";
  const content = Array.isArray(message.content)
    ? message.content
    : Array.isArray(message.parts)
      ? message.parts
      : [];
  return {
    id: message.id || `${role}-${index}`,
    role,
    content,
    status: message.status,
    metadata: message.metadata || {},
  };
};

const converter = (state, connectionMetadata) => {
  const serverMessages = Array.isArray(state?.messages)
    ? state.messages.map((message, index) => normalizeMessage(message, index)).filter(Boolean)
    : [];

  const pendingHumanMessages = connectionMetadata.pendingCommands
    .filter((cmd) => cmd.type === "add-message")
    .map((cmd) => {
      const parts = (cmd.message.parts || []).flatMap((part) => {
        if (part.type === "text") return [{ type: "text", text: part.text || "" }];
        if (part.type === "image") return [{ type: "image", image: part.image || "" }];
        return [];
      });
      const text = parts
        .filter((part) => part.type === "text")
        .map((part) => part.text || "")
        .join("\n")
        .trim();
      return {
        id: cmd.message.id || `pending-${text}`,
        role: "user",
        content: parts,
        metadata: {},
      };
    });

  const serverIds = new Set(serverMessages.map((m) => m.id));
  const optimistic = pendingHumanMessages.filter((m) => !serverIds.has(m.id));

  return {
    messages: [...optimistic, ...serverMessages],
    isRunning: connectionMetadata.isSending,
  };
};

function MarkdownPart({ text, isRunning }) {
  const [expanded, setExpanded] = useState(false);
  const value = `${text || ""}${isRunning ? "\n\n●" : ""}`;
  const lineCount = useMemo(() => (value.match(/\n/g)?.length || 0) + 1, [value]);
  const isLong = lineCount > 10;
  const remarkPlugins = [gfmPlugin, mathPlugin].filter(Boolean);
  const rehypePlugins = [katexPlugin].filter(Boolean);
  const markdownComponents = useMemo(
    () => ({
      code({ inline, className, children, ...props }) {
        if (inline) {
          return (
            <code className={className} {...props}>
              {children}
            </code>
          );
        }
        const content = String(children || "").replace(/\n$/, "");
        return (
          <pre className="markdown-code-block">
            <code className={className || "language-text"} {...props}>
              {content}
            </code>
          </pre>
        );
      },
    }),
    []
  );
  const markdownNode = (
    <ReactMarkdown
      remarkPlugins={remarkPlugins}
      rehypePlugins={rehypePlugins}
      components={markdownComponents}
    >
      {value}
    </ReactMarkdown>
  );

  if (!isLong) {
    return <div className="message-text">{markdownNode}</div>;
  }

  return (
    <div className="message-text">
      <div className={`message-fade-block ${expanded ? "expanded" : "collapsed"}`}>
        {markdownNode}
      </div>
      <button type="button" className="btn tiny inline" onClick={() => setExpanded((prev) => !prev)}>
        {expanded ? "Show less" : "Show more"}
      </button>
    </div>
  );
}

function MarkdownTextPart() {
  const part = useMessagePartText();
  return <MarkdownPart text={part.text} isRunning={part.status?.type === "running"} />;
}

function ImagePart() {
  const part = useMessagePartImage();
  return (
    <div className="message-image-wrap">
      <img src={resolveAppUrl(part.image)} alt="Uploaded" className="message-image" />
    </div>
  );
}

function ToolCallPart(props) {
  const argsText = props.argsText || JSON.stringify(props.args || {}, null, 2);
  const resultText =
    props.result === undefined ? "(pending)" : JSON.stringify(props.result, null, 2);
  const parsedArgs = useMemo(() => {
    if (props.args && typeof props.args === "object") return props.args;
    try {
      return JSON.parse(argsText || "{}");
    } catch {
      return {};
    }
  }, [argsText, props.args]);
  const commandText =
    typeof parsedArgs?.command === "string"
      ? parsedArgs.command
      : typeof parsedArgs?.code === "string"
        ? parsedArgs.code
        : "";
  const commandLabel = typeof parsedArgs?.command === "string" ? "Command" : "Code";
  const commandLanguage = typeof parsedArgs?.command === "string" ? "bash" : "python";

  const stdout = typeof props.result?.stdout === "string" ? props.result.stdout : "";
  const stderr = typeof props.result?.stderr === "string" ? props.result.stderr : "";
  const toolError = typeof props.result?.error === "string" ? props.result.error : "";
  const exitCode = props.result?.exit_code;
  const assets = Array.isArray(props.result?.assets) ? props.result.assets : [];
  const hasHtmlWidget = assets.some((asset) => String(asset?.mime_type || "").startsWith("text/html"));
  const displayToolName = hasHtmlWidget
    ? "UI Widget"
    : props.toolName === "sandbox_exec_python"
      ? "Python"
      : props.toolName === "sandbox_exec_shell"
        ? "Shell"
        : props.toolName;
  const [maximizedWidget, setMaximizedWidget] = useState(null);
  const claimName = props.result?.claim_name || "";
  const leaseId = props.result?.lease_id || "";

  useEffect(() => {
    if (!maximizedWidget || typeof window === "undefined" || typeof document === "undefined") {
      return undefined;
    }
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        setMaximizedWidget(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [maximizedWidget]);

  return (
    <details className="tool-call" open={false}>
      <summary>
        <code>{displayToolName}</code>
      </summary>
      <div className="tool-context">
        {props.result === undefined ? (
          <span className="badge running">Waiting for sandbox claim/runtime...</span>
        ) : claimName ? (
          <span className="badge completed">Claim ready: {claimName}</span>
        ) : leaseId ? (
          <span className="badge completed">Lease: {leaseId}</span>
        ) : (
          <span className="badge">No claim metadata</span>
        )}
      </div>
      <div className="tool-block">
        <strong>{commandText ? commandLabel : "Arguments"}</strong>
        {commandText ? (
          <pre className="tool-code-block">
            <code className={`language-${commandLanguage}`}>{commandText}</code>
          </pre>
        ) : (
          <pre className="tool-code-block">
            <code className="language-json">{argsText}</code>
          </pre>
        )}
      </div>
      {stdout ? (
        <div className="tool-block">
          <strong>Stdout</strong>
          <pre className="tool-output-block">
            <code className="language-text">{stdout}</code>
          </pre>
        </div>
      ) : null}
      {stderr ? (
        <div className="tool-block">
          <strong>Stderr</strong>
          <pre className="tool-output-block error">
            <code className="language-text">{stderr}</code>
          </pre>
        </div>
      ) : null}
      {toolError ? (
        <div className="tool-block">
          <strong>Error</strong>
          <pre className="tool-output-block error">
            <code className="language-text">{toolError}</code>
          </pre>
        </div>
      ) : null}
      {props.result !== undefined && exitCode !== undefined && exitCode !== null ? (
        <div className="tool-block">
          <strong>Exit code</strong>
          <code>{String(exitCode)}</code>
        </div>
      ) : null}
      {!stdout && !stderr && !toolError ? (
        <div className="tool-block">
          <strong>Result</strong>
          <pre className="tool-code-block">
            <code className="language-json">{resultText}</code>
          </pre>
        </div>
      ) : null}
      {assets.length > 0 ? (
        <div className="tool-block">
          <strong>Assets</strong>
          <ul className="asset-list">
            {assets.map((asset) => (
              <li key={asset.asset_id || asset.view_url}>
                {String(asset.mime_type || "").startsWith("image/") ? (
                  <img
                    src={resolveAppUrl(asset.view_url)}
                    alt={asset.filename || "Generated asset"}
                    className="tool-asset-image"
                  />
                ) : null}
                {String(asset.mime_type || "").startsWith("text/html") ? (
                  <div className="tool-widget-wrap">
                    <div className="tool-widget-label">Interactive widget preview</div>
                    <iframe
                      src={resolveAppUrl(asset.view_url)}
                      title={asset.filename || "Generated widget"}
                      className="tool-widget-frame"
                      loading="lazy"
                      sandbox="allow-scripts allow-downloads"
                      referrerPolicy="no-referrer"
                    />
                    <div className="tool-widget-actions">
                      <button
                        type="button"
                        className="btn tiny"
                        onClick={() => setMaximizedWidget(asset)}
                      >
                        Expand
                      </button>
                      <a
                        href={resolveAppUrl(asset.view_url)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Open
                      </a>
                    </div>
                  </div>
                ) : null}
                <a
                  href={resolveAppUrl(asset.download_url || asset.view_url)}
                  target="_blank"
                  rel="noreferrer"
                >
                  {asset.filename || "download"}
                </a>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {maximizedWidget ? (
        <div
          className="widget-modal-backdrop"
          onClick={() => setMaximizedWidget(null)}
          role="presentation"
        >
          <div className="widget-modal" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="widget-modal-header">
              <strong>{maximizedWidget.filename || "UI Widget"}</strong>
              <div className="widget-modal-actions">
                <a
                  href={resolveAppUrl(maximizedWidget.view_url)}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open
                </a>
                <a
                  href={resolveAppUrl(maximizedWidget.download_url || maximizedWidget.view_url)}
                  target="_blank"
                  rel="noreferrer"
                >
                  Download
                </a>
                <button type="button" className="btn tiny" onClick={() => setMaximizedWidget(null)}>
                  Close
                </button>
              </div>
            </div>
            <iframe
              src={resolveAppUrl(maximizedWidget.view_url)}
              title={maximizedWidget.filename || "Maximized widget"}
              className="tool-widget-frame tool-widget-frame-maximized"
              loading="lazy"
              sandbox="allow-scripts allow-downloads"
              referrerPolicy="no-referrer"
            />
          </div>
        </div>
      ) : null}
    </details>
  );
}

function ComposerAttachmentItem() {
  return (
    <AttachmentPrimitive.Root className="attachment-pill">
      <AttachmentPrimitive.Name className="attachment-name" />
      <AttachmentPrimitive.Remove className="attachment-remove">x</AttachmentPrimitive.Remove>
    </AttachmentPrimitive.Root>
  );
}

function TransportProvider({ children, apiBase, session }) {
  const transportHeaders = useMemo(
    () => Object.fromEntries(withAuthHeaders().entries()),
    []
  );
  const runtime = useAssistantTransportRuntime({
    api: `${apiBase}/assistant`,
    headers: transportHeaders,
    initialState: {
      session_id: session?.session_id || null,
      messages: Array.isArray(session?.messages) ? session.messages : [],
      tool_updates: [],
    },
    converter,
    adapters: {
      attachments: imageAttachmentAdapter,
    },
  });

  return <AssistantRuntimeProvider runtime={runtime}>{children}</AssistantRuntimeProvider>;
}

function UserMessage() {
  return (
    <MessagePrimitive.Root className="message user">
      <div className="bubble">
        <div className="message-label">User</div>
        <MessagePrimitive.Parts components={{ Text: MarkdownTextPart, Image: ImagePart }} />
      </div>
    </MessagePrimitive.Root>
  );
}

function AssistantMessage() {
  return (
    <MessagePrimitive.Root className="message assistant">
      <div className="bubble">
        <div className="message-label">Assistant</div>
        <MessagePrimitive.Parts
          components={{
            Text: MarkdownTextPart,
            Image: ImagePart,
            Reasoning: () => null,
            tools: {
              Fallback: (part) => <ToolCallPart {...part} />,
            },
          }}
        />
      </div>
    </MessagePrimitive.Root>
  );
}

function ThreadMarkdownShareButton({ apiBase, sessionId }) {
  const [copied, setCopied] = useState(false);

  const handleShareMarkdown = useCallback(async () => {
    if (!sessionId) return;
    const shareResponse = await apiFetch(`${apiBase}/sessions/${sessionId}/share`, {
      method: "POST",
    });
    if (!shareResponse.ok) return;
    const shareData = await shareResponse.json();
    const markdownUrl = `${window.location.origin}${getAppBasePath()}/api/public/${shareData.share_id}/markdown`;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(markdownUrl);
      }
    } catch {
      // Ignore clipboard failures in restricted browser contexts.
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }, [apiBase, sessionId]);

  return (
    <button type="button" className="btn" onClick={handleShareMarkdown}>
      {copied ? "Copied Markdown URL" : "Share as Markdown"}
    </button>
  );
}

function ThinkingSidebar() {
  const isRunning = useAssistantState((s) => s.thread.isRunning);
  const messages = useAssistantState((s) => s.thread.messages);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (isRunning) {
      setOpen(true);
    } else {
      setOpen(false);
    }
  }, [isRunning]);

  const entries = (messages || [])
    .filter((message) => message.role === "assistant")
    .flatMap((message) =>
      (message.content || [])
        .filter((part) => part.type === "reasoning" && typeof part.text === "string")
        .map((part, index) => ({
          id: `${message.id || "msg"}-${index}`,
          text: part.text,
        }))
    )
    .filter((entry) => entry.text.trim().length > 0);

  return (
    <aside className={`thinking-sidebar ${open ? "open" : "closed"}`}>
      <button type="button" className="thinking-toggle" onClick={() => setOpen((prev) => !prev)}>
        Thinking {entries.length > 0 ? `(${entries.length})` : ""}
      </button>
      {open ? (
        <div className="thinking-panel">
          {entries.length === 0 ? (
            <p className="thinking-empty">No thinking steps yet.</p>
          ) : (
            entries.map((entry) => (
              <details key={entry.id} className="reasoning" open={false}>
                <summary>Reasoning step</summary>
                <MarkdownPart text={entry.text} isRunning={false} />
              </details>
            ))
          )}
        </div>
      ) : null}
    </aside>
  );
}

function Composer({ readOnly }) {
  if (readOnly) {
    return <div className="composer-readonly">Read-only shared thread</div>;
  }

  return (
    <ComposerPrimitive.Root className="composer">
      <div className="composer-attachments">
        <ComposerPrimitive.Attachments
          components={{
            Attachment: ComposerAttachmentItem,
            Image: ComposerAttachmentItem,
          }}
        />
      </div>
      <ComposerPrimitive.Input
        className="composer-input"
        placeholder="Ask the agent to run Python/shell in sandbox, debug code, etc."
        rows={3}
      />
      <div className="composer-actions">
        <ComposerPrimitive.AddAttachment className="btn" title="Add image">
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" className="icon-svg">
            <path d="M5 4a3 3 0 0 0-3 3v10a3 3 0 0 0 3 3h14a3 3 0 0 0 3-3V7a3 3 0 0 0-3-3H5Zm0 2h14a1 1 0 0 1 1 1v7.4l-3.3-3.3a1 1 0 0 0-1.4 0L10 16.4l-2.3-2.3a1 1 0 0 0-1.4 0L4 16.4V7a1 1 0 0 1 1-1Zm15 11v.4a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-.4l3-3 2.3 2.3a1 1 0 0 0 1.4 0l5.3-5.3L20 17Zm-11.5-8a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3Z" fill="currentColor"/>
          </svg>
          <span className="sr-only">image upload</span>
        </ComposerPrimitive.AddAttachment>
        <AuiIf condition={(s) => !s.thread.isRunning}>
          <ComposerPrimitive.Send className="btn primary">Send</ComposerPrimitive.Send>
        </AuiIf>
        <AuiIf condition={(s) => s.thread.isRunning}>
          <ComposerPrimitive.Cancel className="btn danger">Stop</ComposerPrimitive.Cancel>
        </AuiIf>
      </div>
    </ComposerPrimitive.Root>
  );
}

function ChatArea({ session, onResetSession, readOnly, apiBase }) {
  const sandbox = session?.sandbox || {};
  const activeClaim = sandbox.has_active_claim ? sandbox.claim_name : null;
  const leaseStatus = sandbox?.status || null;
  const waitingSince = sandbox?.created_at ? Date.parse(sandbox.created_at) : Number.NaN;
  const waitingSeconds = Number.isFinite(waitingSince)
    ? Math.max(0, Math.floor((Date.now() - waitingSince) / 1000))
    : null;

  let claimBadgeClass = "";
  let claimBadgeText = "Claim: none";
  if (leaseStatus === "pending") {
    claimBadgeClass = "running";
    claimBadgeText =
      waitingSeconds !== null
        ? `Claim: acquiring (${waitingSeconds}s)`
        : "Claim: acquiring";
  } else if (leaseStatus === "ready" && activeClaim) {
    claimBadgeClass = "completed";
    claimBadgeText = `Claim ready: ${activeClaim}`;
  } else if (leaseStatus === "ready") {
    claimBadgeClass = "running";
    claimBadgeText = "Claim: binding runtime";
  } else if (leaseStatus) {
    claimBadgeClass = "error";
    claimBadgeText = `Claim status: ${leaseStatus}`;
  }

  return (
    <section className="panel chat-panel">
      <div className="chat-header">
        <h2>{readOnly ? "Shared Thread" : "Assistant UI Chat"}</h2>
        <div className="chat-meta">
          <span>
            Session: <code>{session?.session_id || "new"}</code>
          </span>
          {!readOnly ? (
            <>
              <ThreadMarkdownShareButton apiBase={apiBase} sessionId={session?.session_id} />
              <button
                type="button"
                className="btn"
                onClick={() => onResetSession(session?.session_id)}
                disabled={!session?.session_id}
              >
                Reset Session
              </button>
            </>
          ) : null}
          {!readOnly ? (
            <span className={`badge ${claimBadgeClass}`.trim()}>
              {claimBadgeText}
            </span>
          ) : null}
        </div>
      </div>

      <ThreadPrimitive.Root className="thread-root">
        <ThreadPrimitive.Viewport className="thread-viewport">
          <AuiIf condition={(s) => s.thread.isEmpty}>
            <div className="empty">Start by sending a message.</div>
          </AuiIf>
          <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage }} />
          <ThreadPrimitive.ScrollToBottom className="btn scroll-btn">Jump to latest</ThreadPrimitive.ScrollToBottom>
        </ThreadPrimitive.Viewport>
        <Composer readOnly={readOnly} />
      </ThreadPrimitive.Root>
    </section>
  );
}

function SandboxTemplatePicker({ value, onChange, disabled }) {
  return (
    <div className="sandbox-template-picker" role="radiogroup" aria-label="Sandbox template">
      <span className="sandbox-template-title">Runtime</span>
      <div className="sandbox-template-options">
        {SANDBOX_TEMPLATES.map((template) => (
          <label key={template.value} className={`sandbox-template-option ${value === template.value ? "selected" : ""}`}>
            <input
              type="radio"
              name="sandbox-template"
              value={template.value}
              checked={value === template.value}
              onChange={() => onChange(template.value)}
              disabled={disabled}
            />
            <span className="option-text">
              <strong>{template.label}</strong>
              <small>{template.description}</small>
            </span>
          </label>
        ))}
      </div>
    </div>
  );
}

function Sidebar({ sessions, activeSessionId, onSelect, onNew, onShare, shareInFlight, isSharedView }) {
  return (
    <aside className="panel sidebar">
      <div className="sidebar-header">
        <h2>Threads</h2>
        {!isSharedView ? (
          <button type="button" className="btn primary" onClick={onNew}>
            New
          </button>
        ) : null}
      </div>
      <ul className="session-list">
        {sessions.map((session) => (
          <li key={session.session_id} className="session-row">
            <button
              type="button"
              onClick={() => onSelect(session.session_id)}
              className={`session-item ${session.session_id === activeSessionId ? "active" : ""}`}
            >
              <span className="title">{session.title || "New chat"}</span>
              <span className="preview">{session.preview || "No messages yet"}</span>
            </button>
            {!isSharedView ? (
              <button
                type="button"
                className="share-icon"
                aria-label="Share thread"
                onClick={(event) => {
                  event.stopPropagation();
                  onShare(session.session_id);
                }}
                disabled={shareInFlight}
                title="Share thread"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" className="share-svg">
                  <path d="M10.6 13.4a1 1 0 0 1 0-1.4l3-3a3 3 0 1 1 4.2 4.2l-2.2 2.2a3 3 0 0 1-4.2 0 .999.999 0 1 1 1.4-1.4 1 1 0 0 0 1.4 0l2.2-2.2a1 1 0 1 0-1.4-1.4l-3 3a1 1 0 0 1-1.4 0Z" fill="currentColor"/>
                  <path d="M13.4 10.6a1 1 0 0 1 0 1.4l-3 3a3 3 0 1 1-4.2-4.2l2.2-2.2a3 3 0 0 1 4.2 0 .999.999 0 1 1-1.4 1.4 1 1 0 0 0-1.4 0l-2.2 2.2a1 1 0 0 0 1.4 1.4l3-3a1 1 0 0 1 1.4 0Z" fill="currentColor"/>
                </svg>
              </button>
            ) : null}
          </li>
        ))}
      </ul>
    </aside>
  );
}

function SettingsForm({ apiBase, config, setConfig, configLoading, configSaving, configError, configMessage, onReload, onSave }) {
  return (
    <section className="panel settings-panel">
      <h2>Backend Configuration</h2>
      <p>
        API base: <code>{apiBase}</code>
      </p>
      <form onSubmit={onSave} className="settings-grid">
        <label>
          Model
          <input type="text" value={config.model} onChange={(event) => setConfig((prev) => ({ ...prev, model: event.target.value }))} disabled={configLoading || configSaving} />
        </label>
        <label>
          Max tool calls per turn
          <input type="number" min={1} max={20} value={config.max_tool_calls_per_turn} onChange={(event) => setConfig((prev) => ({ ...prev, max_tool_calls_per_turn: event.target.value }))} disabled={configLoading || configSaving} />
        </label>
        <label>
          Sandbox mode
          <select value={config.sandbox_mode} onChange={(event) => setConfig((prev) => ({ ...prev, sandbox_mode: event.target.value }))} disabled={configLoading || configSaving}>
            <option value="local">local</option>
            <option value="cluster">cluster</option>
          </select>
        </label>
        <label>
          Sandbox API URL
          <input type="text" value={config.sandbox_api_url} onChange={(event) => setConfig((prev) => ({ ...prev, sandbox_api_url: event.target.value }))} disabled={configLoading || configSaving} />
        </label>
        <label>
          Sandbox template name
          <input
            type="text"
            list="sandbox-template-options"
            value={config.sandbox_template_name}
            onChange={(event) => setConfig((prev) => ({ ...prev, sandbox_template_name: event.target.value }))}
            disabled={configLoading || configSaving}
          />
          <datalist id="sandbox-template-options">
            <option value="python-runtime-template" />
            <option value="python-runtime-template-small" />
            <option value="python-runtime-template-large" />
            <option value="python-runtime-template-pydata" />
          </datalist>
        </label>
        <label>
          Sandbox namespace
          <input type="text" value={config.sandbox_namespace} onChange={(event) => setConfig((prev) => ({ ...prev, sandbox_namespace: event.target.value }))} disabled={configLoading || configSaving} />
        </label>
        <label>
          Sandbox server port
          <input type="number" min={1} max={65535} value={config.sandbox_server_port} onChange={(event) => setConfig((prev) => ({ ...prev, sandbox_server_port: event.target.value }))} disabled={configLoading || configSaving} />
        </label>
        <label>
          Max output chars
          <input type="number" min={100} max={100000} value={config.sandbox_max_output_chars} onChange={(event) => setConfig((prev) => ({ ...prev, sandbox_max_output_chars: event.target.value }))} disabled={configLoading || configSaving} />
        </label>
        <label>
          Local timeout seconds
          <input type="number" min={1} max={600} value={config.sandbox_local_timeout_seconds} onChange={(event) => setConfig((prev) => ({ ...prev, sandbox_local_timeout_seconds: event.target.value }))} disabled={configLoading || configSaving} />
        </label>
        <div className="settings-actions">
          <button type="button" className="btn" onClick={onReload} disabled={configLoading || configSaving}>{configLoading ? "Loading..." : "Reload Config"}</button>
          <button type="submit" className="btn primary" disabled={configLoading || configSaving}>{configSaving ? "Saving..." : "Save Config"}</button>
        </div>
        {configError ? <p className="error-text">{configError}</p> : null}
        {configMessage ? <p className="success-text">{configMessage}</p> : null}
      </form>
    </section>
  );
}

function App() {
  const [tab, setTab] = useState("chat");
  const [runtimeKey, setRuntimeKey] = useState(0);
  const [sessions, setSessions] = useState([]);
  const [activeSession, setActiveSession] = useState(null);
  const [shareInFlight, setShareInFlight] = useState(false);
  const [isSharedView, setIsSharedView] = useState(false);
  const [configLoading, setConfigLoading] = useState(false);
  const [configSaving, setConfigSaving] = useState(false);
  const [templateSaving, setTemplateSaving] = useState(false);
  const [configError, setConfigError] = useState("");
  const [configMessage, setConfigMessage] = useState("");
  const [config, setConfig] = useState({
    model: "gpt-4o-mini",
    max_tool_calls_per_turn: 4,
    sandbox_mode: "local",
    sandbox_api_url: "",
    sandbox_template_name: "python-runtime-template-small",
    sandbox_namespace: "alt-default",
    sandbox_server_port: 8888,
    sandbox_max_output_chars: 6000,
    sandbox_local_timeout_seconds: 20,
  });
  const [theme, setTheme] = useState(() => {
    if (typeof window === "undefined") return "light";
    const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (storedTheme === "light" || storedTheme === "dark") return storedTheme;
    return getMediaQueryMatches("(prefers-color-scheme: dark)") ? "dark" : "light";
  });
  const [isMobile, setIsMobile] = useState(() =>
    getMediaQueryMatches("(max-width: 760px)")
  );
  const [showMobileThreads, setShowMobileThreads] = useState(false);
  const [showMobileRuntime, setShowMobileRuntime] = useState(false);
  const [userId, setUserId] = useState("");
  const [userTier, setUserTier] = useState("default");

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return undefined;
    }
    const media = window.matchMedia("(max-width: 760px)");
    const onChange = (event) => setIsMobile(event.matches);
    setIsMobile(media.matches);
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", onChange);
      return () => media.removeEventListener("change", onChange);
    }
    media.addListener(onChange);
    return () => media.removeListener(onChange);
  }, []);

  useEffect(() => {
    if (typeof document === "undefined") return;
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.style.colorScheme = theme;
    if (typeof window !== "undefined") {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    }
  }, [theme]);

  useEffect(() => {
    if (!isMobile) {
      setShowMobileThreads(false);
      setShowMobileRuntime(false);
    }
  }, [isMobile]);

  const apiBase = useMemo(() => {
    const configured = import.meta.env.VITE_API_BASE;
    return configured && configured.length > 0 ? configured : DEFAULT_API_BASE;
  }, []);

  const loadSession = useCallback(
    async (sessionId) => {
      const response = await apiFetch(`${apiBase}/sessions/${sessionId}`);
      if (!response.ok) throw new Error(`Failed to load session ${sessionId}`);
      const data = await response.json();
      setActiveSession(data);
      setRuntimeKey((prev) => prev + 1);
    },
    [apiBase]
  );

  const loadSessions = useCallback(async () => {
    const response = await apiFetch(`${apiBase}/sessions`);
    if (!response.ok) throw new Error("Failed to list sessions");
    const data = await response.json();
    const items = Array.isArray(data.sessions) ? data.sessions : [];
    setSessions(items);
    return items;
  }, [apiBase]);

  const loadUserIdentity = useCallback(async () => {
    try {
      const response = await apiFetch(`${apiBase}/me`);
      if (!response.ok) throw new Error("Failed to load user identity");
      const data = await response.json();
      setUserId(typeof data?.user_id === "string" ? data.user_id : "");
      setUserTier(typeof data?.tier === "string" && data.tier ? data.tier : "default");
    } catch {
      setUserId("");
      setUserTier("default");
    }
  }, [apiBase]);

  const createSession = useCallback(async () => {
    const response = await apiFetch(`${apiBase}/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (!response.ok) throw new Error("Failed to create session");
    const data = await response.json();
    await loadSessions();
    await loadSession(data.session_id);
  }, [apiBase, loadSession, loadSessions]);

  useEffect(() => {
    const sharedMatch = window.location.pathname.match(/\/public\/([^/]+)\/?$/);
    const shared = sharedMatch?.[1];
    if (!shared) {
      setIsSharedView(false);
      loadSessions()
        .then((items) => {
          if (items.length > 0) {
            loadSession(items[0].session_id).catch(() => undefined);
          } else {
            createSession().catch(() => undefined);
          }
        })
        .catch(() => undefined);
      return;
    }

    setIsSharedView(true);
    apiFetch(`${apiBase}/public/${shared}`)
      .then((r) => r.json())
      .then((data) => {
        setActiveSession(data);
        setSessions([
          {
            session_id: data.session_id,
            title: data.title,
            preview: "Shared session",
          },
        ]);
        setRuntimeKey((prev) => prev + 1);
      })
      .catch(() => undefined);
  }, [apiBase, createSession, loadSession, loadSessions]);

  useEffect(() => {
    if (isSharedView || tab !== "chat") return undefined;
    const timer = window.setInterval(() => {
      loadSessions().catch(() => undefined);
    }, 4000);
    return () => window.clearInterval(timer);
  }, [isSharedView, loadSessions, tab]);

  useEffect(() => {
    if (isSharedView || tab !== "chat" || !activeSession?.session_id) return undefined;
    const sessionId = activeSession.session_id;
    const timer = window.setInterval(() => {
      apiFetch(`${apiBase}/sessions/${sessionId}/sandbox`)
        .then((response) => (response.ok ? response.json() : null))
        .then((data) => {
          if (!data?.sandbox) return;
          setActiveSession((prev) => {
            if (!prev || prev.session_id !== sessionId) return prev;
            return { ...prev, sandbox: data.sandbox };
          });
        })
        .catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [activeSession?.session_id, apiBase, isSharedView, tab]);

  async function handleShare(sessionId) {
    setShareInFlight(true);
    try {
      const response = await apiFetch(`${apiBase}/sessions/${sessionId}/share`, { method: "POST" });
      if (!response.ok) throw new Error("Failed to share session");
      const data = await response.json();
      const url = `${window.location.origin}${getAppBasePath()}${data.share_path}`;
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(url);
      }
      setConfigMessage(`Share URL copied: ${url}`);
      await loadSessions();
    } catch (error) {
      setConfigError(String(error));
    } finally {
      setShareInFlight(false);
    }
  }

  async function handleResetSession(sessionId) {
    if (!sessionId) return;
    await apiFetch(`${apiBase}/sessions/${sessionId}/reset`, { method: "POST" });
    const updated = await loadSessions();
    if (updated.length > 0) {
      await loadSession(updated[0].session_id);
    } else {
      await createSession();
    }
  }

  async function loadConfig() {
    setConfigLoading(true);
    setConfigError("");
    setConfigMessage("");
    try {
      const response = await apiFetch(`${apiBase}/config`);
      if (!response.ok) throw new Error(`Failed to load config: ${response.status}`);
      const data = await response.json();
      setConfig({
        model: data.model || "gpt-4o-mini",
        max_tool_calls_per_turn: Number(data.max_tool_calls_per_turn ?? 4),
        sandbox_mode: data?.sandbox?.mode || "local",
        sandbox_api_url: data?.sandbox?.api_url || "",
        sandbox_template_name: data?.sandbox?.template_name || "python-runtime-template-small",
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

  useEffect(() => {
    if (isSharedView) {
      setUserId("");
      setUserTier("default");
      return;
    }
    loadUserIdentity();
  }, [isSharedView, loadUserIdentity]);

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
      const response = await apiFetch(`${apiBase}/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || "Failed to save config");
      setConfigMessage("Configuration saved.");
      setConfig((prev) => ({ ...prev, model: data.model }));
    } catch (error) {
      setConfigError(String(error));
    } finally {
      setConfigSaving(false);
    }
  }

  async function handleTemplateQuickSelect(templateName) {
    if (!templateName || templateName === config.sandbox_template_name) return;
    const previousTemplate = config.sandbox_template_name;
    const nextConfig = { ...config, sandbox_template_name: templateName };
    setConfig((prev) => ({ ...prev, sandbox_template_name: templateName }));
    setTemplateSaving(true);
    setConfigError("");
    setConfigMessage("");
    try {
      const payload = {
        model: nextConfig.model,
        max_tool_calls_per_turn: Number(nextConfig.max_tool_calls_per_turn),
        sandbox_mode: nextConfig.sandbox_mode,
        sandbox_api_url: nextConfig.sandbox_api_url,
        sandbox_template_name: nextConfig.sandbox_template_name,
        sandbox_namespace: nextConfig.sandbox_namespace,
        sandbox_server_port: Number(nextConfig.sandbox_server_port),
        sandbox_max_output_chars: Number(nextConfig.sandbox_max_output_chars),
        sandbox_local_timeout_seconds: Number(nextConfig.sandbox_local_timeout_seconds),
      };
      const response = await apiFetch(`${apiBase}/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || "Failed to update sandbox template");
      setConfigMessage(`Runtime switched to ${templateName}.`);
    } catch (error) {
      setConfig((prev) => ({ ...prev, sandbox_template_name: previousTemplate }));
      setConfigError(String(error));
    } finally {
      setTemplateSaving(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <h1>Sandboxed React Agent</h1>
        <div className="topbar-actions">
          {!isSharedView ? (
            <span className="user-identity" title={userId || "User ID unavailable"}>
              User ID: <code>{userId || "-"}</code>
              <span className="badge">Tier: {userTier}</span>
            </span>
          ) : null}
          <nav className="tabs">
            <button type="button" onClick={() => setTab("chat")} className={`tab ${tab === "chat" ? "active" : ""}`}>Chat</button>
            <button type="button" onClick={() => setTab("settings")} className={`tab ${tab === "settings" ? "active" : ""}`}>Settings</button>
          </nav>
          <button
            type="button"
            className="btn theme-toggle"
            onClick={() => setTheme((prev) => (prev === "dark" ? "light" : "dark"))}
          >
            {theme === "dark" ? "Light mode" : "Dark mode"}
          </button>
        </div>
      </header>

      {tab === "chat" ? (
        <div>
          {isMobile ? (
            <div className="mobile-controls">
              <button
                type="button"
                className={`btn ${showMobileThreads ? "primary" : ""}`.trim()}
                onClick={() => setShowMobileThreads((prev) => !prev)}
              >
                {showMobileThreads ? "Hide Threads" : "Threads"}
              </button>
              {!isSharedView ? (
                <button
                  type="button"
                  className={`btn ${showMobileRuntime ? "primary" : ""}`.trim()}
                  onClick={() => setShowMobileRuntime((prev) => !prev)}
                >
                  {showMobileRuntime ? "Hide Runtime" : "Runtime"}
                </button>
              ) : null}
            </div>
          ) : null}
          <div className="workspace">
            {!isMobile ? (
              <Sidebar
                sessions={sessions}
                activeSessionId={activeSession?.session_id}
                onSelect={(sessionId) => loadSession(sessionId).catch(() => undefined)}
                onNew={() => createSession().catch(() => undefined)}
                onShare={handleShare}
                shareInFlight={shareInFlight}
                isSharedView={isSharedView}
              />
            ) : null}
            {isMobile && showMobileThreads ? (
              <div className="mobile-sheet">
                <Sidebar
                  sessions={sessions}
                  activeSessionId={activeSession?.session_id}
                  onSelect={(sessionId) => {
                    loadSession(sessionId).catch(() => undefined);
                    setShowMobileThreads(false);
                  }}
                  onNew={() => {
                    createSession().catch(() => undefined);
                    setShowMobileThreads(false);
                  }}
                  onShare={handleShare}
                  shareInFlight={shareInFlight}
                  isSharedView={isSharedView}
                />
              </div>
            ) : null}
          <TransportProvider key={runtimeKey} apiBase={apiBase} session={activeSession}>
            <div className="chat-with-thinking">
              <div>
                {!isSharedView && (!isMobile || showMobileRuntime) ? (
                  <SandboxTemplatePicker
                    value={config.sandbox_template_name}
                    onChange={handleTemplateQuickSelect}
                    disabled={configLoading || configSaving || templateSaving}
                  />
                ) : null}
                <ChatArea
                  session={activeSession}
                  onResetSession={handleResetSession}
                  readOnly={isSharedView}
                  apiBase={apiBase}
                />
                {!isSharedView && (configError || configMessage) ? (
                  <p className={configError ? "quick-config-feedback error-text" : "quick-config-feedback success-text"}>
                    {configError || configMessage}
                  </p>
                ) : null}
              </div>
              <ThinkingSidebar />
            </div>
          </TransportProvider>
          </div>
        </div>
      ) : (
        <SettingsForm
          apiBase={apiBase}
          config={config}
          setConfig={setConfig}
          configLoading={configLoading}
          configSaving={configSaving}
          configError={configError}
          configMessage={configMessage}
          onReload={loadConfig}
          onSave={handleSaveConfig}
        />
      )}
    </main>
  );
}

export default App;
