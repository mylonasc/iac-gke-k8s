export const DEFAULT_API_BASE = (
  import.meta.env.VITE_API_BASE || "/cluster-authz-manager/api"
).replace(/\/+$/, "");

export function withApiBase(path) {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${DEFAULT_API_BASE}${normalized}`;
}

export async function apiFetch(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });
  return response;
}

export async function apiFetchJson(url, options = {}) {
  const response = await apiFetch(withApiBase(url), options);
  const contentType = response.headers.get("content-type") || "";

  let payload = null;
  if (contentType.includes("application/json")) {
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
  } else {
    try {
      const text = await response.text();
      payload = text ? { detail: text } : null;
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const detail =
      (typeof payload?.detail === "string" && payload.detail) ||
      `Request failed (${response.status})`;
    const error = new Error(detail);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }

  return payload;
}
