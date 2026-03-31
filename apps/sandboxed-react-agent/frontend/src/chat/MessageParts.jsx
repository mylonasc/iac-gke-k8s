import React, { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { MessagePrimitive, useMessagePartImage, useMessagePartText } from "@assistant-ui/react";
import { resolveAppUrl } from "../api/client";

const gfmPlugin = typeof remarkGfm === "function" ? remarkGfm : remarkGfm?.default;
const mathPlugin = typeof remarkMath === "function" ? remarkMath : remarkMath?.default;
const katexPlugin = typeof rehypeKatex === "function" ? rehypeKatex : rehypeKatex?.default;

function MarkdownPart({ text, isRunning }) {
  const [expanded, setExpanded] = useState(false);
  const value = `${text || ""}${isRunning ? "\n\n●" : ""}`;
  const lineCount = useMemo(() => (value.match(/\n/g)?.length || 0) + 1, [value]);
  const isLong = lineCount > 10;
  const remarkPlugins = [gfmPlugin, mathPlugin].filter(Boolean);
  const rehypePlugins = [katexPlugin].filter(Boolean);

  const markdownNode = (
    <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins}>
      {value}
    </ReactMarkdown>
  );

  if (!isLong) {
    return <div className="message-markdown">{markdownNode}</div>;
  }

  return (
    <div className="message-markdown">
      <div className={`message-fade-block ${expanded ? "expanded" : "collapsed"}`}>{markdownNode}</div>
      <button type="button" className="btn btn-subtle tiny" onClick={() => setExpanded((prev) => !prev)}>
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
    <details className="tool-card" open={false}>
      <summary>
        <code>{displayToolName || "Tool call"}</code>
      </summary>
      <div className="tool-context">
        {props.result === undefined ? (
          <span className="pill pill-running">Waiting for sandbox claim/runtime...</span>
        ) : claimName ? (
          <span className="pill pill-success">Claim ready: {claimName}</span>
        ) : leaseId ? (
          <span className="pill pill-success">Lease: {leaseId}</span>
        ) : (
          <span className="pill">No claim metadata</span>
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
                      <button type="button" className="btn btn-subtle tiny" onClick={() => setMaximizedWidget(asset)}>
                        Expand
                      </button>
                      <a href={resolveAppUrl(asset.view_url)} target="_blank" rel="noreferrer">
                        Open
                      </a>
                    </div>
                  </div>
                ) : null}
                <a href={resolveAppUrl(asset.download_url || asset.view_url)} target="_blank" rel="noreferrer">
                  {asset.filename || "download"}
                </a>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {maximizedWidget ? (
        <div className="widget-modal-backdrop" onClick={() => setMaximizedWidget(null)} role="presentation">
          <div className="widget-modal" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="widget-modal-header">
              <strong>{maximizedWidget.filename || "UI Widget"}</strong>
              <div className="widget-modal-actions">
                <a href={resolveAppUrl(maximizedWidget.view_url)} target="_blank" rel="noreferrer">
                  Open
                </a>
                <a
                  href={resolveAppUrl(maximizedWidget.download_url || maximizedWidget.view_url)}
                  target="_blank"
                  rel="noreferrer"
                >
                  Download
                </a>
                <button type="button" className="btn btn-subtle tiny" onClick={() => setMaximizedWidget(null)}>
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

export function UserMessage() {
  return (
    <MessagePrimitive.Root className="message-row user">
      <div className="message-bubble message-bubble-user">
        <div className="message-label">User</div>
        <MessagePrimitive.Parts components={{ Text: MarkdownTextPart, Image: ImagePart }} />
      </div>
    </MessagePrimitive.Root>
  );
}

export function AssistantMessage() {
  const messageComponents = useMemo(
    () => ({
      Text: MarkdownTextPart,
      Image: ImagePart,
      Reasoning: () => null,
      tools: {
        Fallback: (part) => <ToolCallPart {...part} />,
      },
    }),
    []
  );

  return (
    <MessagePrimitive.Root className="message-row assistant">
      <div className="message-bubble message-bubble-assistant">
        <div className="message-label">Assistant</div>
        <MessagePrimitive.Parts components={messageComponents} />
      </div>
    </MessagePrimitive.Root>
  );
}
