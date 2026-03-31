import React, { useMemo } from "react";
import {
  AssistantRuntimeProvider,
  useAssistantTransportRuntime,
} from "@assistant-ui/react";
import { authHeadersObject } from "../api/client";

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
      return {
        id: cmd.message.id || `pending-${Date.now()}`,
        role: "user",
        content: parts,
        metadata: {},
      };
    });

  const serverIds = new Set(serverMessages.map((message) => message.id));
  const optimistic = pendingHumanMessages.filter((message) => !serverIds.has(message.id));

  return {
    messages: [...optimistic, ...serverMessages],
    isRunning: connectionMetadata.isSending,
  };
};

export function TransportProvider({ children, apiBase, session }) {
  const transportHeaders = useMemo(() => authHeadersObject(), []);
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
