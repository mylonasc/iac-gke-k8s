import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ChatView } from "./ChatView";

vi.mock("@assistant-ui/react", () => {
  const passthrough = ({ children, ...props }) => <div {...props}>{children}</div>;
  return {
    AuiIf: ({ condition, children }) => {
      const state = { thread: { isRunning: false, isEmpty: false } };
      return condition(state) ? <>{children}</> : null;
    },
    useAssistantTransportState: (selector) =>
      (typeof selector === "function" ? selector({}) : {}),
    useAssistantState: (selector) =>
      (typeof selector === "function"
        ? selector({ thread: { state: {} } })
        : { thread: { state: {} } }),
    ThreadPrimitive: {
      Root: passthrough,
      Viewport: passthrough,
      Messages: () => <div data-testid="thread-messages" />,
      ScrollToBottom: ({ children, ...props }) => <button {...props}>{children}</button>,
    },
  };
});

vi.mock("./MessageParts", () => ({
  UserMessage: () => <div>User message</div>,
  AssistantMessage: () => <div>Assistant message</div>,
}));

vi.mock("./Composer", () => ({
  Composer: () => <div>Composer</div>,
}));

vi.mock("./ThinkingSidebar", () => ({
  ThinkingSidebar: () => <aside>Thinking Sidebar</aside>,
}));

vi.mock("../terminal/SandboxTerminalPanel", () => ({
  SandboxTerminalPanel: () => <div>Terminal Panel</div>,
}));

const baseSession = {
  session_id: "session-1",
  title: "Test thread",
  sandbox: { status: "ready", has_active_claim: true, claim_name: "claim-1" },
  sandbox_policy: {},
  sandbox_status: {
    sandbox_policy: {},
    workspace_status: {
      provisioning_pending: false,
      workspace: { status: "ready" },
    },
    effective: {
      runtime: {
        profile: "transient",
        template_name: "python-runtime-template-small",
      },
    },
    available_sandboxes: {
      profiles: ["persistent_workspace", "transient"],
      execution_models: ["session", "ephemeral"],
      persistent_workspace: {
        base_templates: [
          "python-runtime-template-small",
          "python-runtime-template",
          "python-runtime-template-large",
        ],
        primary_base_template: "python-runtime-template-small",
      },
      templates: [
        { name: "python-runtime-template-small" },
        { name: "python-runtime-template-large" },
        { name: "template-one" },
        { name: "template-two" },
      ],
    },
  },
};

const baseConfig = {
  model: "gpt-4o-mini",
  sandbox_profile: "persistent_workspace",
  sandbox_template_name: "python-runtime-template-small",
};

function renderView(overrides = {}) {
  const props = {
    apiBase: "/api",
    session: baseSession,
    config: baseConfig,
    onResetSession: vi.fn(),
    onRefreshSandboxStatus: vi.fn(),
    onUpdateSessionSandboxPolicy: vi.fn(),
    onRunSessionSandboxAction: vi.fn(),
    sandboxStatusLoading: false,
    sandboxStatusError: "",
    readOnly: false,
    configError: "",
    configMessage: "",
    onShare: vi.fn(),
    isMobile: false,
    ...overrides,
  };
  return { ...render(<ChatView {...props} />), props };
}

describe("ChatView sandbox controls", () => {
  it("renders workspace and effective runtime status", async () => {
    const user = userEvent.setup();
    renderView();

    await user.click(screen.getByRole("button", { name: "Advanced sandbox controls" }));

    expect(
      screen.getByRole("dialog", { name: "Advanced sandbox controls" })
    ).toBeInTheDocument();

    expect(screen.getByText("Workspace: ready")).toBeInTheDocument();
    expect(screen.getByText("Pending: no")).toBeInTheDocument();
    expect(screen.getByText("Effective profile: transient")).toBeInTheDocument();
    expect(screen.getByText("Effective template: python-runtime-template-small")).toBeInTheDocument();
    expect(screen.getByText(/Persistent base templates:/)).toBeInTheDocument();
  });

  it("invokes refresh and action callbacks", async () => {
    const user = userEvent.setup();
    const onRefreshSandboxStatus = vi.fn();
    const onRunSessionSandboxAction = vi.fn();

    renderView({ onRefreshSandboxStatus, onRunSessionSandboxAction });

    await user.click(screen.getByRole("button", { name: "Advanced sandbox controls" }));
    await user.click(screen.getByRole("button", { name: "Refresh status" }));
    await user.click(screen.getByRole("button", { name: "Release lease" }));
    await user.click(screen.getByRole("button", { name: "Reconcile workspace" }));

    expect(onRefreshSandboxStatus).toHaveBeenCalledWith("session-1");
    expect(onRunSessionSandboxAction).toHaveBeenNthCalledWith(1, "session-1", "release_lease", {
      wait: false,
    });
    expect(onRunSessionSandboxAction).toHaveBeenNthCalledWith(
      2,
      "session-1",
      "reconcile_workspace",
      { wait: false }
    );
  });

  it("opens terminal modal from controls", async () => {
    const user = userEvent.setup();
    renderView();

    await user.click(screen.getByRole("button", { name: "Terminal" }));

    expect(screen.getByRole("dialog", { name: "Sandbox terminal" })).toBeInTheDocument();
    expect(screen.getByText("Terminal Panel")).toBeInTheDocument();
  });

  it("sends nulls when policy fields are cleared", async () => {
    const user = userEvent.setup();
    const onUpdateSessionSandboxPolicy = vi.fn();
    const session = {
      ...baseSession,
      sandbox_policy: {
        profile: "transient",
        template_name: "python-runtime-template-small",
        execution_model: "ephemeral",
      },
    };

    renderView({ session, onUpdateSessionSandboxPolicy });

    await user.click(screen.getByRole("button", { name: "Advanced sandbox controls" }));
    await user.selectOptions(screen.getByLabelText("Session profile"), "");
    await user.selectOptions(screen.getByLabelText("Session template"), "");
    await user.selectOptions(screen.getByLabelText("Session execution model"), "");
    await user.click(screen.getByRole("button", { name: "Apply session policy" }));

    expect(onUpdateSessionSandboxPolicy).toHaveBeenCalledWith("session-1", {
      profile: null,
      template_name: null,
      execution_model: null,
    });
  });

  it("resets policy inputs when session changes", async () => {
    const user = userEvent.setup();
    const firstSession = {
      ...baseSession,
      session_id: "session-1",
      sandbox_policy: { profile: "transient", template_name: "template-one", execution_model: "session" },
    };
    const secondSession = {
      ...baseSession,
      session_id: "session-2",
      sandbox_policy: {
        profile: "persistent_workspace",
        template_name: "template-two",
        execution_model: "ephemeral",
      },
    };

    const { rerender } = renderView({ session: firstSession });

    await user.click(screen.getByRole("button", { name: "Advanced sandbox controls" }));
    await user.selectOptions(screen.getByLabelText("Session template"), "python-runtime-template-small");
    expect(screen.getByLabelText("Session template")).toHaveValue("python-runtime-template-small");

    rerender(
      <ChatView
        apiBase="/api"
        session={secondSession}
        config={baseConfig}
        onResetSession={vi.fn()}
        onRefreshSandboxStatus={vi.fn()}
        onUpdateSessionSandboxPolicy={vi.fn()}
        onRunSessionSandboxAction={vi.fn()}
        sandboxStatusLoading={false}
        sandboxStatusError=""
        readOnly={false}
        configError=""
        configMessage=""
        onShare={vi.fn()}
        isMobile={false}
      />
    );

    await waitFor(() => {
      expect(screen.getByLabelText("Session profile")).toHaveValue("persistent_workspace");
      expect(screen.getByLabelText("Session template")).toHaveValue("template-two");
      expect(screen.getByLabelText("Session execution model")).toHaveValue("ephemeral");
    });
  });
});
