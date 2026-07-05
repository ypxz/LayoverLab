import { defineConfig, devices } from "@playwright/test";

const CI = !!process.env.CI;

export default defineConfig({
  testDir: "./tests",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1, // the fixture stack shares one SQLite DB; keep runs deterministic
  retries: CI ? 1 : 0,
  reporter: CI ? [["list"], ["html", { open: "never" }]] : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    permissions: ["clipboard-read", "clipboard-write"],
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "bash scripts/start-api.sh",
      url: "http://localhost:8000/api/health",
      timeout: 180_000,
      reuseExistingServer: !CI,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: "bash scripts/start-web.sh",
      url: "http://localhost:3000",
      timeout: 300_000,
      reuseExistingServer: !CI,
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
});
