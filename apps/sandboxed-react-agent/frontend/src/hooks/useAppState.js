import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch, DEFAULT_API_BASE, getAppBasePath } from "../api/client";

const THEME_STORAGE_KEY = "sandboxed-react-agent-theme-v2";

const defaultConfig = {
  model: "gpt-4o-mini",
  max_tool_calls_per_turn: 4,
  sandbox_mode: "cluster",
  sandbox_profile: "persistent_workspace",
  sandbox_api_url: "",
  sandbox_template_name: "python-runtime-template-small",
  sandbox_namespace: "alt-default",
  sandbox_server_port: 8888,
  sandbox_max_output_chars: 6000,
  sandbox_local_timeout_seconds: 20,
};

export function useAppState() {
  const [tab, setTab] = useState("chat");
  const [runtimeKey, setRuntimeKey] = useState(0);
  const [sessions, setSessions] = useState([]);
  const [activeSession, setActiveSession] = useState(null);
  const [shareInFlight, setShareInFlight] = useState(false);
  const [isSharedView, setIsSharedView] = useState(false);
  const [configLoading, setConfigLoading] = useState(false);
  const [configSaving, setConfigSaving] = useState(false);
  const [configError, setConfigError] = useState("");
  const [configMessage, setConfigMessage] = useState("");
  const [adminOpsLoading, setAdminOpsLoading] = useState(false);
  const [adminOpsError, setAdminOpsError] = useState("");
  const [adminOpsData, setAdminOpsData] = useState(null);
  const [sandboxStatusLoading, setSandboxStatusLoading] = useState(false);
  const [sandboxStatusError, setSandboxStatusError] = useState("");
  const [config, setConfig] = useState(defaultConfig);
  const [userId, setUserId] = useState("");
  const [userEmail, setUserEmail] = useState("");
  const [userDisplayName, setUserDisplayName] = useState("");
  const [userTier, setUserTier] = useState("default");
  const [userRoles, setUserRoles] = useState([]);
  const [userCapabilities, setUserCapabilities] = useState([]);
  const [theme, setTheme] = useState(() => {
    if (typeof window === "undefined") return "light";
    return window.localStorage.getItem(THEME_STORAGE_KEY) || "light";
  });

  const apiBase = useMemo(() => {
    const configured = import.meta.env.VITE_API_BASE;
    return configured && configured.length > 0 ? configured : DEFAULT_API_BASE;
  }, []);

  const loadSession = useCallback(
    async (sessionId) => {
      const response = await apiFetch(`${apiBase}/sessions/${sessionId}`);
      if (!response.ok) throw new Error(`Failed to load session ${sessionId}`);
      const data = await response.json();
      setActiveSession({
        ...data,
        sandbox_policy: data?.sandbox_policy || {},
      });
      setRuntimeKey((prev) => prev + 1);
    },
    [apiBase]
  );

  const loadSessionSandboxStatus = useCallback(
    async (sessionId, { silent = false } = {}) => {
      if (!sessionId) return null;
      if (!silent) {
        setSandboxStatusLoading(true);
        setSandboxStatusError("");
      }
      try {
        const response = await apiFetch(`${apiBase}/sessions/${sessionId}/sandbox/status`);
        const data = await response.json();
        if (!response.ok) throw new Error(data?.detail || "Failed to load sandbox status");
        setActiveSession((prev) => {
          if (!prev || prev.session_id !== sessionId) return prev;
          return {
            ...prev,
            sandbox: data?.sandbox || prev?.sandbox,
            sandbox_status: data,
            sandbox_policy: data?.sandbox_policy || prev?.sandbox_policy || {},
          };
        });
        return data;
      } catch (error) {
        if (!silent) setSandboxStatusError(String(error));
        return null;
      } finally {
        if (!silent) setSandboxStatusLoading(false);
      }
    },
    [apiBase]
  );

  const updateSessionSandboxPolicy = useCallback(
    async (sessionId, patch) => {
      if (!sessionId) return null;
      setSandboxStatusLoading(true);
      setSandboxStatusError("");
      try {
        const response = await apiFetch(`${apiBase}/sessions/${sessionId}/sandbox/policy`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(patch || {}),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data?.detail || "Failed to update sandbox policy");
        setActiveSession((prev) => {
          if (!prev || prev.session_id !== sessionId) return prev;
          return {
            ...prev,
            sandbox_policy: data?.sandbox_policy || {},
            sandbox_status: data?.status || prev?.sandbox_status,
            sandbox: data?.status?.sandbox || prev?.sandbox,
          };
        });
        return data;
      } catch (error) {
        setSandboxStatusError(String(error));
        throw error;
      } finally {
        setSandboxStatusLoading(false);
      }
    },
    [apiBase]
  );

  const runSessionSandboxAction = useCallback(
    async (sessionId, action, { wait = false } = {}) => {
      if (!sessionId) return null;
      setSandboxStatusLoading(true);
      setSandboxStatusError("");
      try {
        const response = await apiFetch(`${apiBase}/sessions/${sessionId}/sandbox/actions`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action, wait }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data?.detail || "Failed sandbox action");
        const status = data?.status;
        if (status) {
          setActiveSession((prev) => {
            if (!prev || prev.session_id !== sessionId) return prev;
            return {
              ...prev,
              sandbox_status: status,
              sandbox: status?.sandbox || prev?.sandbox,
              sandbox_policy: status?.sandbox_policy || prev?.sandbox_policy || {},
            };
          });
        }
        return data;
      } catch (error) {
        setSandboxStatusError(String(error));
        throw error;
      } finally {
        setSandboxStatusLoading(false);
      }
    },
    [apiBase]
  );

  const loadSessions = useCallback(async () => {
    const response = await apiFetch(`${apiBase}/sessions`);
    if (!response.ok) throw new Error("Failed to list sessions");
    const data = await response.json();
    const items = Array.isArray(data.sessions) ? data.sessions : [];
    setSessions(items);
    return items;
  }, [apiBase]);

  const loadConfig = useCallback(async () => {
    setConfigLoading(true);
    setConfigError("");
    setConfigMessage("");
    try {
      const response = await apiFetch(`${apiBase}/config`);
      if (!response.ok) throw new Error(`Failed to load config: ${response.status}`);
      const data = await response.json();
      const runtime = data?.toolkits?.sandbox?.runtime || data?.sandbox || {};
      const agentConfig = data?.agent || {};
      setConfig({
        model: agentConfig.model || data.model || "gpt-4o-mini",
        max_tool_calls_per_turn: Number(
          agentConfig.max_tool_calls_per_turn ?? data.max_tool_calls_per_turn ?? 4
        ),
        sandbox_mode: runtime.mode || data.sandbox_mode || "cluster",
        sandbox_profile: runtime.profile || data.sandbox_profile || "persistent_workspace",
        sandbox_api_url: runtime.api_url || data.sandbox_api_url || "",
        sandbox_template_name:
          runtime.template_name || data.sandbox_template_name || "python-runtime-template-small",
        sandbox_namespace: runtime.namespace || data.sandbox_namespace || "alt-default",
        sandbox_server_port: Number(runtime.server_port ?? data.sandbox_server_port ?? 8888),
        sandbox_max_output_chars: Number(
          runtime.max_output_chars ?? data.sandbox_max_output_chars ?? 6000
        ),
        sandbox_local_timeout_seconds: Number(
          runtime.local_timeout_seconds ?? data.sandbox_local_timeout_seconds ?? 20
        ),
      });
    } catch (error) {
      setConfigError(String(error));
    } finally {
      setConfigLoading(false);
    }
  }, [apiBase]);

  const createSession = useCallback(async () => {
    const response = await apiFetch(`${apiBase}/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (!response.ok) throw new Error("Failed to create session");
    const data = await response.json();
    await loadSessions();
    await loadSession(data.session_id);
  }, [apiBase, loadSession, loadSessions]);

  useEffect(() => {
    if (typeof document === "undefined") return;
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.style.colorScheme = theme;
    if (typeof window !== "undefined") {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    }
  }, [theme]);

  useEffect(() => {
    const sharedMatch = window.location.pathname.match(/\/public\/([^/]+)\/?$/);
    const shared = sharedMatch?.[1];
    if (!shared) {
      setIsSharedView(false);
      loadSessions()
        .then((items) => {
          if (items.length > 0) {
            loadSession(items[0].session_id).catch(() => undefined);
          } else {
            createSession().catch(() => undefined);
          }
        })
        .catch(() => undefined);
      return;
    }

    setIsSharedView(true);
    apiFetch(`${apiBase}/public/${shared}`)
      .then((response) => response.json())
      .then((data) => {
        setActiveSession(data);
        setSessions([
          {
            session_id: data.session_id,
            title: data.title,
            preview: "Shared session",
          },
        ]);
        setRuntimeKey((prev) => prev + 1);
      })
      .catch(() => undefined);
  }, [apiBase, createSession, loadSession, loadSessions]);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  useEffect(() => {
    if (isSharedView || tab !== "chat") return undefined;
    const timer = window.setInterval(() => {
      loadSessions().catch(() => undefined);
    }, 4000);
    return () => window.clearInterval(timer);
  }, [isSharedView, loadSessions, tab]);

  useEffect(() => {
    if (isSharedView || tab !== "chat" || !activeSession?.session_id) return undefined;
    const sessionId = activeSession.session_id;
    loadSessionSandboxStatus(sessionId, { silent: true }).catch(() => undefined);
    const timer = window.setInterval(() => {
      loadSessionSandboxStatus(sessionId, { silent: true }).catch(() => undefined);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [activeSession?.session_id, loadSessionSandboxStatus, isSharedView, tab]);

  useEffect(() => {
    if (isSharedView) {
      setUserId("");
      setUserTier("default");
      setUserRoles([]);
      setUserCapabilities([]);
      return;
    }
    apiFetch(`${apiBase}/me`)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        setUserId(typeof data?.user_id === "string" ? data.user_id : "");
        setUserEmail(typeof data?.email === "string" ? data.email : "");
        setUserDisplayName(typeof data?.display_name === "string" ? data.display_name : "");
        setUserTier(typeof data?.tier === "string" && data.tier ? data.tier : "default");
        setUserRoles(Array.isArray(data?.roles) ? data.roles : []);
        setUserCapabilities(Array.isArray(data?.capabilities) ? data.capabilities : []);
      })
      .catch(() => {
        setUserId("");
        setUserEmail("");
        setUserDisplayName("");
        setUserTier("default");
        setUserRoles([]);
        setUserCapabilities([]);
      });
  }, [apiBase, isSharedView]);

  const saveConfig = useCallback(
    async (nextConfig) => {
      const payload = {
        agent: {
          model: nextConfig.model,
          max_tool_calls_per_turn: Number(nextConfig.max_tool_calls_per_turn),
        },
        toolkits: {
          sandbox: {
            runtime: {
              mode: nextConfig.sandbox_mode,
              profile: nextConfig.sandbox_profile,
              api_url: nextConfig.sandbox_api_url,
              template_name: nextConfig.sandbox_template_name,
              namespace: nextConfig.sandbox_namespace,
              server_port: Number(nextConfig.sandbox_server_port),
              max_output_chars: Number(nextConfig.sandbox_max_output_chars),
              local_timeout_seconds: Number(nextConfig.sandbox_local_timeout_seconds),
            },
          },
        },
      };
      const response = await apiFetch(`${apiBase}/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || "Failed to save config");
      return data;
    },
    [apiBase]
  );

  const handleSaveConfig = useCallback(
    async (event) => {
      event.preventDefault();
      setConfigSaving(true);
      setConfigError("");
      setConfigMessage("");
      try {
        await saveConfig(config);
        setConfigMessage("Configuration saved.");
      } catch (error) {
        setConfigError(String(error));
      } finally {
        setConfigSaving(false);
      }
    },
    [config, saveConfig]
  );

  const loadAdminOps = useCallback(async () => {
    setAdminOpsLoading(true);
    setAdminOpsError("");
    try {
      const [workspaceJobsResponse, sandboxIndexResponse] = await Promise.all([
        apiFetch(`${apiBase}/admin/ops/workspace-jobs?limit=200&include_terminal=true`),
        apiFetch(`${apiBase}/admin/ops/sandbox-index?limit=300`),
      ]);

      const jobsPayload = await workspaceJobsResponse.json();
      const indexPayload = await sandboxIndexResponse.json();

      if (!workspaceJobsResponse.ok) {
        throw new Error(jobsPayload?.detail || "Failed to load workspace jobs");
      }
      if (!sandboxIndexResponse.ok) {
        throw new Error(indexPayload?.detail || "Failed to load sandbox index");
      }

      setAdminOpsData({
        workspaceJobs: jobsPayload,
        sandboxIndex: indexPayload,
      });
    } catch (error) {
      setAdminOpsError(String(error));
    } finally {
      setAdminOpsLoading(false);
    }
  }, [apiBase]);

  const handleShare = useCallback(
    async (sessionId) => {
      setShareInFlight(true);
      setConfigError("");
      try {
        const response = await apiFetch(`${apiBase}/sessions/${sessionId}/share`, {
          method: "POST",
        });
        if (!response.ok) throw new Error("Failed to share session");
        const data = await response.json();
        const url = `${window.location.origin}${getAppBasePath()}${data.share_path}`;
        if (navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(url);
        }
        setConfigMessage(`Share URL copied: ${url}`);
        await loadSessions();
      } catch (error) {
        setConfigError(String(error));
      } finally {
        setShareInFlight(false);
      }
    },
    [apiBase, loadSessions]
  );

  const handleResetSession = useCallback(
    async (sessionId) => {
      if (!sessionId) return;
      await apiFetch(`${apiBase}/sessions/${sessionId}/reset`, { method: "POST" });
      const updated = await loadSessions();
      if (updated.length > 0) {
        await loadSession(updated[0].session_id);
      } else {
        await createSession();
      }
    },
    [apiBase, createSession, loadSession, loadSessions]
  );

  return {
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
    updateSessionSandboxPolicy,
    runSessionSandboxAction,
    loadSessionSandboxStatus,
    handleResetSession,
    handleSaveConfig,
    handleShare,
    isSharedView,
    loadConfig,
    loadAdminOps,
    loadSession,
    runtimeKey,
    sessions,
    setConfig,
    setTab,
    setTheme,
    shareInFlight,
    tab,
    theme,
    userId,
    userEmail,
    userDisplayName,
    userRoles,
    userTier,
    userCapabilities,
  };
}
