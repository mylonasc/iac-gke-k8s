import React from "react";
import { Share2 } from "lucide-react";

export function ThreadsSidebar({
  sessions,
  activeSessionId,
  isSharedView,
  onSelect,
  onCreate,
  onShare,
  shareInFlight,
}) {
  return (
    <aside className="panel threads-panel">
      {!isSharedView ? (
        <div className="sidebar-actions">
          <button type="button" className="btn btn-primary new-chat-btn" onClick={onCreate}>
            + New Chat
          </button>
        </div>
      ) : null}

      <div className="panel-header">
        <h3>History</h3>
      </div>
      <ul className="threads-list">
        {sessions.map((session) => (
          <li key={session.session_id} className="thread-item-row">
            <button
              type="button"
              className={`thread-item ${session.session_id === activeSessionId ? "is-active" : ""}`}
              onClick={() => onSelect(session.session_id)}
            >
              <span className="thread-title">{session.title || "New chat"}</span>
              <span className="thread-preview">{session.preview || "No messages yet"}</span>
            </button>
            {!isSharedView ? (
              <button
                type="button"
                className="btn btn-icon icon-only"
                title="Share thread"
                aria-label="Share thread"
                onClick={() => onShare(session.session_id)}
                disabled={shareInFlight}
              >
                <Share2 className="icon-svg" aria-hidden="true" strokeWidth={2} />
              </button>
            ) : null}
          </li>
        ))}
      </ul>
    </aside>
  );
}
