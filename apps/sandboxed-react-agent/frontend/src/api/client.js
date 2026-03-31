const AUTH_TOKEN_STORAGE_KEY =
  import.meta.env.VITE_AUTH_TOKEN_STORAGE_KEY || "sandboxed-react-agent-auth-token";

export const getAppBasePath = () => {
  const path = window.location.pathname;
  const strippedPublic = path.replace(/\/public\/[^/]+\/?$/, "");
  const normalized = strippedPublic.replace(/\/$/, "");
  return normalized || "";
};

export const APP_BASE_PATH = getAppBasePath();
export const DEFAULT_API_BASE = `${APP_BASE_PATH}/api`;

const getAuthToken = () => {
  if (typeof window === "undefined") return "";
  const staticToken = import.meta.env.VITE_AUTH_TOKEN || "";
  if (staticToken) return staticToken;
  if (typeof window.__AUTH_TOKEN__ === "string" && window.__AUTH_TOKEN__.trim()) {
    return window.__AUTH_TOKEN__.trim();
  }
  const localToken = window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) || "";
  if (localToken.trim()) return localToken.trim();
  const sessionToken = window.sessionStorage.getItem(AUTH_TOKEN_STORAGE_KEY) || "";
  return sessionToken.trim();
};

const withAuthHeaders = (headersInit) => {
  const headers = new Headers(headersInit || {});
  const token = getAuthToken();
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return headers;
};

export const apiFetch = (input, init = {}) =>
  fetch(input, {
    ...init,
    credentials: init.credentials || "include",
    headers: withAuthHeaders(init.headers),
  });

export const resolveAppUrl = (url) => {
  if (typeof url !== "string" || !url) return url;
  if (url.startsWith("http://") || url.startsWith("https://") || url.startsWith("data:")) {
    return url;
  }
  if (url.startsWith("/api/")) {
    return APP_BASE_PATH ? `${APP_BASE_PATH}${url}` : url;
  }
  return url;
};

export const authHeadersObject = () => Object.fromEntries(withAuthHeaders().entries());
