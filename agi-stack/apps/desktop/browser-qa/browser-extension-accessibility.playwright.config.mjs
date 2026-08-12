import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";

const extensionOutput = fileURLToPath(
  new URL("../../browser-extension/.output/chrome-mv3/", import.meta.url),
);

export default defineConfig({
  testDir: fileURLToPath(new URL("./", import.meta.url)),
  testMatch: "browser-extension-accessibility.spec.mjs",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["line"]],
  outputDir: "browser-extension-accessibility-results",
  preserveOutput: "always",
  timeout: 60_000,
  use: {
    baseURL: "http://127.0.0.1:4175",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "python3 -m http.server 4175 --bind 127.0.0.1",
    cwd: extensionOutput,
    url: "http://127.0.0.1:4175/options.html",
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
