import React, { useState } from "react";
import { Menu, Share2 } from "lucide-react";
import { ChatView } from "./chat/ChatView";
import { TransportProvider } from "./chat/TransportProvider";
import { useAppState } from "./hooks/useAppState";
import { useMediaQuery } from "./hooks/useMediaQuery";
import { MobileDrawer } from "./layout/MobileDrawer";
import { ThreadsSidebar } from "./layout/ThreadsSidebar";
import { RuntimePicker } from "./runtime/RuntimePicker";
import { SettingsPanel } from "./settings/SettingsPanel";

function IdentityBadge({ userId, userTier }) {
  if (!userId) return null;
  return (
    <div className="identity-badge" title={userId}>
      <span className="identity-label">User</span>
      <code>{userId}</code>
      <span className="pill">Tier: {userTier}</span>
    </div>
  );
}

function HeaderActions({ isMobile, onOpenThreads, onOpenRuntime, onOpenSettings }) {
  if (!isMobile) return null;
  return (
    <div className="mobile-actions">
      <button type="button" className="btn btn-subtle" onClick={onOpenThreads}>
        Threads
      </button>
      <button type="button" className="btn btn-subtle" onClick={onOpenRuntime}>
        Runtime
      </button>
      <button type="button" className="btn btn-subtle" onClick={onOpenSettings}>
        Settings
      </button>
    </div>
  );
}

function MobileTopBar({ title, canShare, onShare, theme, onToggleTheme, onOpenMenu }) {
  return (
    <div className="mobile-topbar">
      <button type="button" className="btn btn-subtle icon-only" onClick={onOpenMenu} aria-label="Open menu">
        <Menu className="icon-svg" aria-hidden="true" strokeWidth={2} />
      </button>
      <div className="mobile-topbar-title" title={title}>
        {title}
      </div>
      <div className="mobile-topbar-actions">
        {canShare ? (
          <button type="button" className="btn btn-subtle icon-only" onClick={onShare} aria-label="Share thread">
            <Share2 className="icon-svg" aria-hidden="true" strokeWidth={2} />
          </button>
        ) : null}
        <button type="button" className="btn btn-subtle" onClick={onToggleTheme}>
          {theme === "dark" ? "Light" : "Dark"}
        </button>
      </div>
    </div>
  );
}

export default function App() {
  const isMobile = useMediaQuery("(max-width: 980px)");
  const [threadsDrawerOpen, setThreadsDrawerOpen] = useState(false);
  const [runtimeDrawerOpen, setRuntimeDrawerOpen] = useState(false);
  const [settingsDrawerOpen, setSettingsDrawerOpen] = useState(false);
  const [menuDrawerOpen, setMenuDrawerOpen] = useState(false);
  const [threadsDocked, setThreadsDocked] = useState(true);
  const [runtimeDocked, setRuntimeDocked] = useState(true);

  const {
    apiBase,
    activeSession,
    config,
    configError,
    configLoading,
    configMessage,
    configSaving,
    adminOpsData,
    adminOpsError,
    adminOpsLoading,
    sandboxStatusLoading,
    sandboxStatusError,
    createSession,
    handleResetSession,
    handleSaveConfig,
    handleShare,
    handleTemplateQuickSelect,
    isSharedView,
    loadConfig,
    loadAdminOps,
    loadSessionSandboxStatus,
    loadSession,
    runSessionSandboxAction,
    runtimeKey,
    sessions,
    setConfig,
    setTab,
    setTheme,
    updateSessionSandboxPolicy,
    shareInFlight,
    tab,
    templateSaving,
    theme,
    userId,
    userTier,
  } = useAppState();

  const runtimeQuickSwitchDisabled =
    configLoading ||
    configSaving ||
    templateSaving ||
    config.sandbox_profile !== "transient";
  const runtimeQuickSwitchReason =
    config.sandbox_profile !== "transient"
      ? "Quick template switching is available only in transient sandbox profile."
      : "";

  return (
    <main className="app-v2">
      {isMobile ? (
        <MobileTopBar
          title={activeSession?.title || "New chat"}
          canShare={!isSharedView && !!activeSession?.session_id}
          onShare={() => handleShare(activeSession?.session_id)}
          theme={theme}
          onToggleTheme={() => setTheme((prev) => (prev === "dark" ? "light" : "dark"))}
          onOpenMenu={() => setMenuDrawerOpen(true)}
        />
      ) : (
        <header className="app-topbar">
          <div>
            <h1>Sandboxed React Agent</h1>
            <p className="tagline">Gemini/ChatGPT-style shell for sandboxed workflows</p>
          </div>
          <div className="topbar-right">
            {!isSharedView ? <IdentityBadge userId={userId} userTier={userTier} /> : null}
            <div className="tab-row">
              <button
                type="button"
                className={`btn ${tab === "chat" ? "btn-primary" : "btn-subtle"}`}
                onClick={() => setTab("chat")}
              >
                Chat
              </button>
              <button
                type="button"
                className={`btn ${tab === "settings" ? "btn-primary" : "btn-subtle"}`}
                onClick={() => setTab("settings")}
              >
                Settings
              </button>
              <button
                type="button"
                className="btn btn-subtle"
                onClick={() => setTheme((prev) => (prev === "dark" ? "light" : "dark"))}
              >
                {theme === "dark" ? "Light" : "Dark"}
              </button>
            </div>
          </div>
        </header>
      )}

      <div
        className={`app-grid ${!isMobile && !threadsDocked ? "threads-collapsed" : ""} ${
          !isMobile && !runtimeDocked ? "runtime-collapsed" : ""
        }`}
      >
        {!isMobile ? (
          <div className="left-pane-slot">
            {threadsDocked ? (
              <ThreadsSidebar
                sessions={sessions}
                activeSessionId={activeSession?.session_id}
                isSharedView={isSharedView}
                onSelect={(sessionId) => loadSession(sessionId).catch(() => undefined)}
                onCreate={() => createSession().catch(() => undefined)}
                onShare={handleShare}
                shareInFlight={shareInFlight}
              />
            ) : null}
          </div>
        ) : null}

        {!isMobile ? (
          <div className="left-divider-slot">
            <button
              type="button"
              className="pane-divider"
              title={threadsDocked ? "Tuck threads" : "Untuck threads"}
              aria-label={threadsDocked ? "Tuck threads" : "Untuck threads"}
              onClick={() => setThreadsDocked((prev) => !prev)}
            >
              {threadsDocked ? "<" : ">"}
            </button>
          </div>
        ) : null}

        <section className="main-column center-pane-slot">
          {tab === "chat" ? (
            <TransportProvider key={runtimeKey} apiBase={apiBase} session={activeSession}>
              <ChatView
                apiBase={apiBase}
                session={activeSession}
                config={config}
                onResetSession={handleResetSession}
                onRefreshSandboxStatus={loadSessionSandboxStatus}
                onUpdateSessionSandboxPolicy={updateSessionSandboxPolicy}
                onRunSessionSandboxAction={runSessionSandboxAction}
                sandboxStatusLoading={sandboxStatusLoading}
                sandboxStatusError={sandboxStatusError}
                readOnly={isSharedView}
                configError={configError}
                configMessage={configMessage}
                onShare={handleShare}
                isMobile={isMobile}
              />
            </TransportProvider>
          ) : (
            <SettingsPanel
              apiBase={apiBase}
              config={config}
              setConfig={setConfig}
              configLoading={configLoading}
              configSaving={configSaving}
              configError={configError}
              configMessage={configMessage}
              adminOpsData={adminOpsData}
              adminOpsError={adminOpsError}
              adminOpsLoading={adminOpsLoading}
              onReload={loadConfig}
              onLoadAdminOps={loadAdminOps}
              onSave={handleSaveConfig}
            />
          )}
        </section>

        {!isMobile && !isSharedView ? (
          <div className="right-divider-slot">
            <button
              type="button"
              className="pane-divider"
              title={runtimeDocked ? "Tuck runtime" : "Untuck runtime"}
              aria-label={runtimeDocked ? "Tuck runtime" : "Untuck runtime"}
              onClick={() => setRuntimeDocked((prev) => !prev)}
            >
              {runtimeDocked ? ">" : "<"}
            </button>
          </div>
        ) : null}

        {!isMobile && !isSharedView ? (
          <div className="right-pane-slot">
            {runtimeDocked ? (
              <RuntimePicker
                value={config.sandbox_template_name}
                onChange={handleTemplateQuickSelect}
                disabled={runtimeQuickSwitchDisabled}
                disabledReason={runtimeQuickSwitchReason}
              />
            ) : null}
          </div>
        ) : null}
      </div>

      <MobileDrawer open={threadsDrawerOpen} title="Threads" onClose={() => setThreadsDrawerOpen(false)}>
        <ThreadsSidebar
          sessions={sessions}
          activeSessionId={activeSession?.session_id}
          isSharedView={isSharedView}
          onSelect={(sessionId) => {
            loadSession(sessionId).catch(() => undefined);
            setThreadsDrawerOpen(false);
          }}
          onCreate={() => {
            createSession().catch(() => undefined);
            setThreadsDrawerOpen(false);
          }}
          onShare={handleShare}
          shareInFlight={shareInFlight}
        />
      </MobileDrawer>

      {!isSharedView ? (
        <MobileDrawer open={runtimeDrawerOpen} title="Runtime" onClose={() => setRuntimeDrawerOpen(false)}>
          <RuntimePicker
            value={config.sandbox_template_name}
            onChange={(template) => {
              handleTemplateQuickSelect(template);
              setRuntimeDrawerOpen(false);
            }}
            disabled={runtimeQuickSwitchDisabled}
            disabledReason={runtimeQuickSwitchReason}
          />
        </MobileDrawer>
      ) : null}

      <MobileDrawer open={settingsDrawerOpen} title="Settings" onClose={() => setSettingsDrawerOpen(false)}>
        <SettingsPanel
          apiBase={apiBase}
          config={config}
          setConfig={setConfig}
          configLoading={configLoading}
          configSaving={configSaving}
          configError={configError}
          configMessage={configMessage}
          adminOpsData={adminOpsData}
          adminOpsError={adminOpsError}
          adminOpsLoading={adminOpsLoading}
          onReload={loadConfig}
          onLoadAdminOps={loadAdminOps}
          onSave={async (event) => {
            await handleSaveConfig(event);
            setSettingsDrawerOpen(false);
          }}
        />
      </MobileDrawer>

      <MobileDrawer open={menuDrawerOpen} title="Sandboxed React Agent" onClose={() => setMenuDrawerOpen(false)}>
        <div className="mobile-menu-content">
          {!isSharedView ? <IdentityBadge userId={userId} userTier={userTier} /> : null}
          <div className="mobile-menu-group">
            <button
              type="button"
              className={`btn ${tab === "chat" ? "btn-primary" : "btn-subtle"}`}
              onClick={() => {
                setTab("chat");
                setMenuDrawerOpen(false);
              }}
            >
              Chat
            </button>
          </div>
          <div className="mobile-actions">
            <button
              type="button"
              className="btn btn-subtle"
              onClick={() => {
                setMenuDrawerOpen(false);
                setThreadsDrawerOpen(true);
              }}
            >
              Threads
            </button>
            <button
              type="button"
              className="btn btn-subtle"
              onClick={() => {
                setMenuDrawerOpen(false);
                setRuntimeDrawerOpen(true);
              }}
            >
              Runtime
            </button>
            <button
              type="button"
              className="btn btn-subtle"
              onClick={() => {
                setMenuDrawerOpen(false);
                setSettingsDrawerOpen(true);
              }}
            >
              Settings
            </button>
          </div>
        </div>
      </MobileDrawer>
    </main>
  );
}
