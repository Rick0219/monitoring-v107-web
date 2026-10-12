import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  timeout: 60000,
  workers: 1,
  use: {
    baseURL: process.env.WEB_TEST_URL || "http://127.0.0.1:8007",
    headless: true,
    channel: process.env.PLAYWRIGHT_CHANNEL || "msedge",
    viewport: { width: 1440, height: 1000 },
  },
  reporter: [["list"], ["html", { open: "never" }]],
});
