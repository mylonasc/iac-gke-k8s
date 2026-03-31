import React, { useMemo, useState } from "react";
import { useAssistantState } from "@assistant-ui/react";

function ReasoningMarkdown({ text }) {
  return <div className="thinking-text">{text}</div>;
}

export function ThinkingSidebar() {
  const messages = useAssistantState((state) => state.thread.messages);
  const [open, setOpen] = useState(false);

  const entries = useMemo(
    () =>
      (messages || [])
        .filter((message) => message.role === "assistant")
        .flatMap((message) =>
          (message.content || [])
            .filter((part) => part.type === "reasoning" && typeof part.text === "string")
            .map((part, index) => ({
              id: `${message.id || "msg"}-${index}`,
              text: part.text,
            }))
        )
        .filter((entry) => entry.text.trim().length > 0),
    [messages]
  );

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
              <details key={entry.id} className="reasoning-card" open={false}>
                <summary>Reasoning step</summary>
                <ReasoningMarkdown text={entry.text} />
              </details>
            ))
          )}
        </div>
      ) : null}
    </aside>
  );
}
