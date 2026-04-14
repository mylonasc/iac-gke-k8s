import { defineConfig } from "vite";

const backendTarget = process.env.VITE_BACKEND_URL;

export default defineConfig({
  base: "/",
  server: backendTarget
    ? {
        proxy: {
          "/api": {
            target: backendTarget,
            changeOrigin: true,
            ws: true,
          },
        },
      }
    : undefined,
  define: {
    "process.env": {},
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.js",
    globals: true,
    include: ["src/**/*.test.{js,jsx}"],
  },
});
