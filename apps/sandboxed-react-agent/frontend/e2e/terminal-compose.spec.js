import { expect, test } from "@playwright/test";

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:8080";
const BASE = new URL(BASE_URL);
const APP_BASE_PATH = BASE.pathname.replace(/\/$/, "");
const APP_ORIGIN = BASE.origin;
const LOGIN_EMAIL = process.env.E2E_LOGIN_EMAIL || "";
const LOGIN_PASSWORD = process.env.E2E_LOGIN_PASSWORD || "";

function appUrl(path = "") {
  return `${APP_ORIGIN}${APP_BASE_PATH}${path}`;
}

function apiUrl(path = "") {
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return appUrl(`/api${suffix}`);
}

async function ensureLoggedIn(page) {
  await page.goto(appUrl("/"));

  for (let attempt = 0; attempt < 12; attempt += 1) {
    const currentUrl = new URL(page.url());

    if (
      currentUrl.pathname === APP_BASE_PATH ||
      currentUrl.pathname === `${APP_BASE_PATH}/`
    ) {
      return;
    }

    if (
      currentUrl.pathname.startsWith("/dex/auth") &&
      !currentUrl.pathname.startsWith("/dex/auth/local")
    ) {
      currentUrl.pathname = "/dex/auth/local";
      await page.goto(currentUrl.toString());
      await page.waitForTimeout(500);
      continue;
    }

    if (currentUrl.pathname.startsWith("/dex/auth/local/login")) {
      if (!LOGIN_EMAIL || !LOGIN_PASSWORD) {
        throw new Error(
          "Dex login is required, but E2E_LOGIN_EMAIL/E2E_LOGIN_PASSWORD are not set"
        );
      }
      await page.evaluate(
        ({ email, password }) => {
          const loginField = document.querySelector('input[name="login"]');
          const passwordField = document.querySelector('input[name="password"]');
          if (loginField instanceof HTMLInputElement) {
            loginField.value = email;
            loginField.dispatchEvent(new Event("input", { bubbles: true }));
            loginField.dispatchEvent(new Event("change", { bubbles: true }));
          }
          if (passwordField instanceof HTMLInputElement) {
            passwordField.value = password;
            passwordField.dispatchEvent(new Event("input", { bubbles: true }));
            passwordField.dispatchEvent(new Event("change", { bubbles: true }));
          }
          const form = document.querySelector('form[method="post"]');
          if (form instanceof HTMLFormElement) {
            form.submit();
          }
        },
        { email: LOGIN_EMAIL, password: LOGIN_PASSWORD }
      );
      await page.waitForTimeout(1_000);
      continue;
    }

    if (currentUrl.pathname.startsWith("/dex/approval")) {
      await page.evaluate(() => {
        const approvalInput = document.querySelector(
          'input[name="approval"][value="approve"]'
        );
        const form = approvalInput?.closest("form");
        if (form instanceof HTMLFormElement) {
          form.submit();
        }
      });
      await page.waitForTimeout(1_000);
      continue;
    }

    const emailMethodButton = page.locator('button:has-text("Log in with Email")');
    if (await emailMethodButton.isVisible().catch(() => false)) {
      await emailMethodButton.click();
      await page.waitForTimeout(500);
      continue;
    }

    await page.goto(appUrl("/"));
  }
}

async function forceClusterRuntime(page) {
  const response = await page.request.post(apiUrl("/config"), {
    data: {
      sandbox_mode: "cluster",
      sandbox_api_url: "http://host.docker.internal:18080",
    },
    timeout: 30_000,
  });
  if (!response.ok()) {
    throw new Error(`Failed to switch backend to cluster mode: ${response.status()}`);
  }
  const payload = await response.json();
  const mode = payload?.toolkits?.sandbox?.runtime?.mode;
  const apiUrlValue = payload?.toolkits?.sandbox?.runtime?.api_url;
  if (mode !== "cluster" || apiUrlValue !== "http://host.docker.internal:18080") {
    throw new Error(
      `Config update did not apply expected cluster runtime (${String(mode)} / ${String(apiUrlValue)})`
    );
  }
}

async function createSession(page, title) {
  const response = await page.request.post(apiUrl("/sessions"), {
    data: { title },
    timeout: 30_000,
  });
  if (!response.ok()) {
    throw new Error(`Failed to create session: ${response.status()}`);
  }
  const payload = await response.json();
  const sessionId = String(payload?.session_id || "").trim();
  if (!sessionId) {
    throw new Error("Session creation returned empty session_id");
  }
  return sessionId;
}

async function setSessionClusterPolicy(page, sessionId) {
  const response = await page.request.patch(apiUrl(`/sessions/${sessionId}/sandbox/policy`), {
    data: {
      mode: "cluster",
      execution_model: "session",
    },
    timeout: 30_000,
  });
  if (!response.ok()) {
    throw new Error(`Failed to update session sandbox policy: ${response.status()}`);
  }

  const detailsResponse = await page.request.get(apiUrl(`/sessions/${sessionId}`), {
    timeout: 30_000,
  });
  if (!detailsResponse.ok()) {
    throw new Error(`Failed to load session details: ${detailsResponse.status()}`);
  }
  const details = await detailsResponse.json();
  const mode = details?.sandbox_policy?.mode;
  const executionModel = details?.sandbox_policy?.execution_model;
  if (mode !== "cluster" || executionModel !== "session") {
    throw new Error(
      `Session policy mismatch (${String(mode)} / ${String(executionModel)})`
    );
  }
}

test("docker-compose deployment can open terminal panel", async ({ page }) => {
  test.setTimeout(300_000);

  await ensureLoggedIn(page);
  await forceClusterRuntime(page);

  const title = `Terminal Compose ${Date.now()}`;
  const sessionId = await createSession(page, title);
  await setSessionClusterPolicy(page, sessionId);

  await page.goto(appUrl("/?dev_panel=terminal"));
  await expect(page.getByText(`Session: ${sessionId}`)).toBeVisible({ timeout: 60_000 });

  const terminalShell = page.locator(".terminal-shell");
  await expect(terminalShell.getByRole("button", { name: "Open" })).toBeVisible({
    timeout: 120_000,
  });
  await terminalShell.getByRole("button", { name: "Open" }).click();

  await expect(terminalShell.locator(".terminal-shell-header .pill")).toHaveText("Connected", {
    timeout: 180_000,
  });

  await terminalShell.getByRole("button", { name: "Close" }).click();
  await expect(terminalShell.locator(".terminal-shell-header .pill")).toHaveText("Closed");
});
