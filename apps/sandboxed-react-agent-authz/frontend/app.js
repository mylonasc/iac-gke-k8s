const editor = document.getElementById("editor");
const statusNode = document.getElementById("status");
const auditNode = document.getElementById("auditlog");
const params = new URLSearchParams(window.location.search);

const appBase = window.location.pathname
  .replace(/\/index\.html$/, "")
  .replace(/\/$/, "");
const queryApiBase = params.get("api_base");
const apiBase = queryApiBase && queryApiBase.trim() ? queryApiBase.trim().replace(/\/$/, "") : `${appBase}/api`;
const apiPath = (suffix) => `${apiBase}${suffix}`;

let currentSha256 = "";

const describeErrorPayload = (payload, fallback) => {
  const detail = payload?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (detail && typeof detail === "object") {
    try {
      return JSON.stringify(detail);
    } catch (_error) {
      return fallback;
    }
  }
  return fallback;
};

const setStatus = (message, isError = false) => {
  statusNode.textContent = message;
  statusNode.className = isError ? "status error" : "status";
};

const loadPolicy = async () => {
  setStatus("Loading policy...");
  try {
    const response = await fetch(apiPath("/policy/current"), { credentials: "include" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(describeErrorPayload(payload, "Failed to load policy"));
    }
    editor.value = String(payload?.policy_yaml || "");
    currentSha256 = String(payload?.sha256 || "").trim();
    setStatus(`Loaded policy sha256=${currentSha256}`);
  } catch (error) {
    setStatus(String(error), true);
  }
};

const validatePolicy = async () => {
  setStatus("Validating policy...");
  try {
    const response = await fetch(apiPath("/policy/validate"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ policy_yaml: editor.value }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(describeErrorPayload(payload, "Validation failed"));
    }
    setStatus(`Validation passed. version=${payload?.version || "?"}`);
  } catch (error) {
    setStatus(String(error), true);
  }
};

const savePolicy = async () => {
  setStatus("Saving policy...");
  try {
    const response = await fetch(apiPath("/policy/current"), {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        ...(currentSha256 ? { "If-Match": currentSha256 } : {}),
      },
      credentials: "include",
      body: JSON.stringify({ policy_yaml: editor.value }),
    });
    const payload = await response.json();
    if (!response.ok) {
      if (response.status === 409) {
        const detail = payload?.detail;
        const message = typeof detail?.message === "string" ? detail.message : "Policy update conflict";
        const nextSha = typeof detail?.current_sha256 === "string" ? detail.current_sha256 : "";
        currentSha256 = nextSha || currentSha256;
        throw new Error(`${message}. Reload and retry.`);
      }
      throw new Error(describeErrorPayload(payload, "Save failed"));
    }
    currentSha256 = String(payload?.sha256 || "").trim();
    setStatus(`Saved. sha256=${currentSha256}`);
  } catch (error) {
    setStatus(String(error), true);
  }
};

const loadAudit = async () => {
  setStatus("Loading audit...");
  try {
    const response = await fetch(apiPath("/policy/audit?limit=50"), {
      credentials: "include",
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(describeErrorPayload(payload, "Failed to load audit"));
    }
    const events = Array.isArray(payload?.events) ? payload.events : [];
    auditNode.textContent = events.map((item) => JSON.stringify(item)).join("\n");
    setStatus(`Loaded ${events.length} audit events`);
  } catch (error) {
    setStatus(String(error), true);
  }
};

document.getElementById("reload").addEventListener("click", loadPolicy);
document.getElementById("validate").addEventListener("click", validatePolicy);
document.getElementById("save").addEventListener("click", savePolicy);
document.getElementById("audit").addEventListener("click", loadAudit);

loadPolicy().catch(() => undefined);
