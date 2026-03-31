import React from "react";
import { AttachmentPrimitive, AuiIf, ComposerPrimitive } from "@assistant-ui/react";

function ImageIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" className="icon-svg">
      <path
        d="M5 4a3 3 0 0 0-3 3v10a3 3 0 0 0 3 3h14a3 3 0 0 0 3-3V7a3 3 0 0 0-3-3H5Zm0 2h14a1 1 0 0 1 1 1v7.4l-3.3-3.3a1 1 0 0 0-1.4 0L10 16.4l-2.3-2.3a1 1 0 0 0-1.4 0L4 16.4V7a1 1 0 0 1 1-1Zm15 11v.4a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-.4l3-3 2.3 2.3a1 1 0 0 0 1.4 0l5.3-5.3L20 17Zm-11.5-8a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3Z"
        fill="currentColor"
      />
    </svg>
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

export function Composer({ readOnly }) {
  if (readOnly) {
    return <div className="composer-readonly">Read-only shared thread</div>;
  }

  return (
    <ComposerPrimitive.Root className="composer-root">
      <ComposerPrimitive.Attachments
        className="composer-attachments"
        components={{
          Attachment: ComposerAttachmentItem,
          Image: ComposerAttachmentItem,
        }}
      />
      <ComposerPrimitive.Input
        className="composer-input"
        placeholder="Ask the sandboxed agent to debug, run Python/shell, or build something..."
        rows={3}
      />
      <div className="composer-actions">
        <ComposerPrimitive.AddAttachment className="btn btn-subtle icon-only" title="Upload image" aria-label="Upload image">
          <ImageIcon />
        </ComposerPrimitive.AddAttachment>
        <AuiIf condition={(s) => !s.thread.isRunning}>
          <ComposerPrimitive.Send className="btn btn-primary">Send</ComposerPrimitive.Send>
        </AuiIf>
        <AuiIf condition={(s) => s.thread.isRunning}>
          <ComposerPrimitive.Cancel className="btn btn-danger">Stop</ComposerPrimitive.Cancel>
        </AuiIf>
      </div>
    </ComposerPrimitive.Root>
  );
}
