import React, { useEffect } from "react";

export function MobileDrawer({ open, title, onClose, children }) {
  useEffect(() => {
    if (!open || typeof document === "undefined") return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className="drawer-backdrop" role="presentation" onClick={onClose}>
      <section className="drawer-sheet" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <header className="drawer-header">
          <h3>{title}</h3>
          <button type="button" className="btn btn-subtle" onClick={onClose}>
            Close
          </button>
        </header>
        <div className="drawer-content">{children}</div>
      </section>
    </div>
  );
}
