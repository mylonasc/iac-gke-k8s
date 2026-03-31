import React from "react";

function ShareIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" className="icon-svg">
      <path
        d="M10.6 13.4a1 1 0 0 1 0-1.4l3-3a3 3 0 1 1 4.2 4.2l-2.2 2.2a3 3 0 0 1-4.2 0 .999.999 0 1 1 1.4-1.4 1 1 0 0 0 1.4 0l2.2-2.2a1 1 0 1 0-1.4-1.4l-3 3a1 1 0 0 1-1.4 0Z"
        fill="currentColor"
      />
      <path
        d="M13.4 10.6a1 1 0 0 1 0 1.4l-3 3a3 3 0 1 1-4.2-4.2l2.2-2.2a3 3 0 0 1 4.2 0 .999.999 0 1 1-1.4 1.4 1 1 0 0 0-1.4 0l-2.2 2.2a1 1 0 0 0 1.4 1.4l3-3a1 1 0 0 1 1.4 0Z"
        fill="currentColor"
      />
    </svg>
  );
}

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
      <div className="panel-header">
        <h3>Threads</h3>
        {!isSharedView ? (
          <button type="button" className="btn btn-primary" onClick={onCreate}>
            New
          </button>
        ) : null}
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
                <ShareIcon />
              </button>
            ) : null}
          </li>
        ))}
      </ul>
    </aside>
  );
}
