import React, { useMemo, useState } from "react";
import { Menu, Share2 } from "lucide-react";
import { ChatView } from "./chat/ChatView";
import { TransportProvider } from "./chat/TransportProvider";
import { useAppState } from "./hooks/useAppState";
import { useMediaQuery } from "./hooks/useMediaQuery";
import { MobileDrawer } from "./layout/MobileDrawer";
import { ThreadsSidebar } from "./layout/ThreadsSidebar";
import { SettingsPanel } from "./settings/SettingsPanel";
import { TerminalDevPanel } from "./dev/TerminalDevPanel";

function IdentityBadge({ userId, userEmail, userDisplayName, userTier }) {
  if (!userId && !userEmail && !userDisplayName) return null;
  const label = userDisplayName || userEmail || userId;
  return (
    <div className="identity-badge" title={userId || userEmail}>
      <span className="identity-label">User</span>
      <code>{label}</code>
      <span className="pill">Tier: {userTier}</span>
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
  const [settingsDrawerOpen, setSettingsDrawerOpen] = useState(false);
  const [menuDrawerOpen, setMenuDrawerOpen] = useState(false);
  const [threadsDocked, setThreadsDocked] = useState(true);

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
    theme,
    userId,
    userEmail,
    userDisplayName,
    userTier,
    userCapabilities,
  } = useAppState();

  const capabilitySet = useMemo(
    () => new Set(Array.isArray(userCapabilities) ? userCapabilities : []),
    [userCapabilities]
  );
  const canOpenTerminal = capabilitySet.has("terminal.open");
  const canViewAdminOps = capabilitySet.has("admin.ops.read");

  const showTerminalDevPanel = useMemo(() => {
    if (typeof window === "undefined") return false;
    const params = new URLSearchParams(window.location.search);
    return params.get("dev_panel") === "terminal";
  }, []);

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
            {!isSharedView ? <IdentityBadge userId={userId} userEmail={userEmail} userDisplayName={userDisplayName} userTier={userTier} /> : null}
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
        className={`app-grid ${!isMobile && !threadsDocked ? "threads-collapsed" : ""}`}
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
          {showTerminalDevPanel ? (
            <TerminalDevPanel sessionId={activeSession?.session_id} />
          ) : tab === "chat" ? (
            <TransportProvider key={runtimeKey} apiBase={apiBase} session={activeSession}>
              <ChatView
                apiBase={apiBase}
                session={activeSession}
                config={config}
                canOpenTerminal={canOpenTerminal}
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
              canViewAdminOps={canViewAdminOps}
              authzConsoleUrl="/sandboxed-react-agent-authz/"
              adminOpsData={adminOpsData}
              adminOpsError={adminOpsError}
              adminOpsLoading={adminOpsLoading}
              onReload={loadConfig}
              onLoadAdminOps={loadAdminOps}
              onSave={handleSaveConfig}
            />
          )}
        </section>

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

      <MobileDrawer open={settingsDrawerOpen} title="Settings" onClose={() => setSettingsDrawerOpen(false)}>
        <SettingsPanel
          apiBase={apiBase}
          config={config}
          setConfig={setConfig}
          configLoading={configLoading}
          configSaving={configSaving}
          configError={configError}
          configMessage={configMessage}
          canViewAdminOps={canViewAdminOps}
          authzConsoleUrl="/sandboxed-react-agent-authz/"
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
          {!isSharedView ? <IdentityBadge userId={userId} userEmail={userEmail} userDisplayName={userDisplayName} userTier={userTier} /> : null}
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
