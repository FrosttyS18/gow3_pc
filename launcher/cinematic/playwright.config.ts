import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testMatch: "test_ci.mjs",
  timeout: 30000,
  retries: 0,
  use: {
    headless: true,
    viewport: { width: 1280, height: 720 },
    baseURL: "http://localhost:3120",
  },
  webServer: {
    command: "npx vite --port 3120 --strictPort",
    port: 3120,
    reuseExistingServer: false,
    timeout: 30000,
  },
});
