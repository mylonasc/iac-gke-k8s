import { expect, test } from "@playwright/test";

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:8080";
const BASE = new URL(BASE_URL);
const APP_BASE_PATH = BASE.pathname.replace(/\/$/, "");
const APP_ORIGIN = BASE.origin;
const LOGIN_EMAIL = process.env.E2E_LOGIN_EMAIL || "";
const LOGIN_PASSWORD = process.env.E2E_LOGIN_PASSWORD || "";

const CHAT_PROMPTS = [
  "Use the sandbox shell tool to run `pwd` and show the output.",
  "Use the sandbox shell tool to run `ls -1` and show the output.",
  "Use the sandbox shell tool again to run `python --version` and show the output.",
  "Use the sandbox shell tool one more time to run `whoami` and show the output.",
];

function countSandboxToolCalls(sessionPayload) {
  const numericCandidates = [
    sessionPayload?.tool_calls,
    sessionPayload?.session?.tool_calls,
    sessionPayload?.sandbox?.tool_calls,
  ];
  for (const candidate of numericCandidates) {
    if (typeof candidate === "number" && Number.isFinite(candidate)) {
      return candidate;
    }
  }

  const messages = Array.isArray(sessionPayload?.messages)
    ? sessionPayload.messages
    : [];

  const uiMessages = Array.isArray(sessionPayload?.ui_messages)
    ? sessionPayload.ui_messages
    : [];

  return messages
    .concat(uiMessages)
    .flatMap((message) =>
      Array.isArray(message?.content) ? message.content : []
    )
    .filter(
      (part) =>
        (part?.type === "tool-call" || part?.type === "tool_call") &&
        typeof (part?.toolName || part?.tool_name) === "string" &&
        (part.toolName || part.tool_name).startsWith("sandbox_exec_")
    ).length;
}

function appUrl(path = "") {
  return `${APP_ORIGIN}${APP_BASE_PATH}${path}`;
}

function apiUrl(path = "") {
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return appUrl(`/api${suffix}`);
}

async function readSession(page, sessionId) {
  const response = await page.request.get(apiUrl(`/sessions/${sessionId}`));
  if (!response.ok()) {
    return null;
  }
  return response.json();
}

async function readSessionToolCallsFromList(page, sessionId) {
  const response = await page.request.get(apiUrl("/sessions"));
  if (!response.ok()) {
    return null;
  }
  const payload = await response.json();
  const sessions = Array.isArray(payload?.sessions) ? payload.sessions : [];
  const match = sessions.find((session) => session?.session_id === sessionId);
  if (!match) {
    return null;
  }
  return typeof match?.tool_calls === "number" ? match.tool_calls : null;
}

async function waitForSandboxToolCalls(page, sessionId, minimum, timeoutMs) {
  const startedAt = Date.now();
  let latestCount = 0;
  while (Date.now() - startedAt < timeoutMs) {
    const listedCount = await readSessionToolCallsFromList(page, sessionId);
    if (typeof listedCount === "number") {
      latestCount = listedCount;
      if (latestCount >= minimum) {
        return latestCount;
      }
    }

    const payload = await readSession(page, sessionId);
    if (payload) {
      latestCount = countSandboxToolCalls(payload);
      if (latestCount >= minimum) {
        return latestCount;
      }
    }
    await page.waitForTimeout(5_000);
  }
  return latestCount;
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

test("acquires a claim and executes sandbox tools at least twice", async ({
  page,
}) => {
  test.setTimeout(900_000);

  await ensureLoggedIn(page);

  let createSessionResponse = null;
  let lastCreateFailure = "";
  for (let attempt = 0; attempt < 8; attempt += 1) {
    try {
      createSessionResponse = await page.request.post(apiUrl("/sessions"), {
        data: { title: `Sandbox capability ${Date.now()}` },
        timeout: 120_000,
      });
    } catch (error) {
      lastCreateFailure = String(error);
      await ensureLoggedIn(page);
      continue;
    }
    if (createSessionResponse.ok()) {
      break;
    }
    const responseBody = (await createSessionResponse.text()).slice(0, 500);
    if ([502, 503, 504].includes(createSessionResponse.status())) {
      lastCreateFailure = `status ${createSessionResponse.status()}: ${responseBody}`;
      await page.waitForTimeout(2_000);
      continue;
    }
    if (
      responseBody.includes("Log in to dex") ||
      responseBody.includes("<!DOCTYPE html>")
    ) {
      await ensureLoggedIn(page);
      continue;
    }
    throw new Error(
      `Create session failed with status ${createSessionResponse.status()}: ${responseBody}`
    );
  }

  if (!createSessionResponse || !createSessionResponse.ok()) {
    throw new Error(
      `Failed to create session after authentication retries. Last failure: ${lastCreateFailure}`
    );
  }
  const createdSession = await createSessionResponse.json();
  expect(typeof createdSession.session_id).toBe("string");
  expect(createdSession.session_id.length).toBeGreaterThan(0);
  const sessionId = createdSession.session_id;

  let sandboxToolCalls = 0;
  let lastTransientChatFailure = "";
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const prompt = CHAT_PROMPTS[attempt % CHAT_PROMPTS.length];
    let chatResponse = null;
    let sawTransient = false;
    try {
      chatResponse = await page.request.post(apiUrl("/chat"), {
        data: {
          message: prompt,
          session_id: sessionId,
        },
        timeout: 120_000,
      });
    } catch (error) {
      lastTransientChatFailure = String(error);
      sawTransient = true;
    }
    if (chatResponse && !chatResponse.ok()) {
      const errorBody = (await chatResponse.text()).slice(0, 500);
      if ([502, 503, 504].includes(chatResponse.status())) {
        lastTransientChatFailure = `status ${chatResponse.status()}: ${errorBody}`;
        sawTransient = true;
      } else {
        throw new Error(
          `Chat request failed with status ${chatResponse.status()}: ${errorBody}`
        );
      }
    }

    if (chatResponse && chatResponse.ok()) {
      const chatPayload = await chatResponse.json();
      expect(chatPayload.session_id).toBe(sessionId);
      expect(chatPayload.error || "").toBe("");
    }

    sandboxToolCalls = await waitForSandboxToolCalls(
      page,
      sessionId,
      2,
      sawTransient ? 330_000 : 45_000
    );
    if (sandboxToolCalls >= 2) {
      break;
    }
  }

  if (sandboxToolCalls < 2 && lastTransientChatFailure) {
    throw new Error(
      `Could not reach two sandbox tool calls after retries; last transient chat failure was ${lastTransientChatFailure}`
    );
  }

  expect(sandboxToolCalls).toBeGreaterThanOrEqual(2);

  await expect
    .poll(
      async () => {
        const response = await page.request.get(apiUrl(`/sessions/${sessionId}/sandbox`));
        if (!response.ok()) {
          return null;
        }
        const payload = await response.json();
        return payload?.sandbox || null;
      },
      {
        message: "session sandbox should have an active ready claim",
        timeout: 120_000,
        intervals: [1_000, 2_000, 4_000],
      }
    )
    .toMatchObject({
      status: "ready",
      has_active_claim: true,
    });

  const sandboxStatusResponse = await page.request.get(apiUrl(`/sessions/${sessionId}/sandbox`));
  expect(sandboxStatusResponse.ok()).toBeTruthy();
  const sandboxStatusPayload = await sandboxStatusResponse.json();
  expect(typeof sandboxStatusPayload?.sandbox?.claim_name).toBe("string");
  expect(sandboxStatusPayload.sandbox.claim_name.length).toBeGreaterThan(0);
});
