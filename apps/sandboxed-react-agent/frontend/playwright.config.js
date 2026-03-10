import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testIgnore: ["**/docker-smoke.spec.js"],
  fullyParallel: false,
  use: {
    baseURL: "http://127.0.0.1:4174",
    headless: true,
  },
  webServer: [
    {
      command: "node ./e2e/mock-backend.mjs",
      url: "http://127.0.0.1:8019/api/config",
      reuseExistingServer: false,
      timeout: 120000,
    },
    {
      command:
        "env VITE_BACKEND_URL=http://127.0.0.1:8019 npm run dev -- --host 127.0.0.1 --port 4174",
      url: "http://127.0.0.1:4174",
      reuseExistingServer: false,
      timeout: 120000,
    },
  ],
});
