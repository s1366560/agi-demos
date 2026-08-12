import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "@playwright/test";

const browserQaRoot = dirname(fileURLToPath(import.meta.url));
const desktopRoot = resolve(browserQaRoot, "..");
const repositoryRoot = resolve(desktopRoot, "../../..");
const webRoot = resolve(repositoryRoot, "web");
const evidenceRoot = resolve(
  process.env.NEO4J_MATCHED_STATE_EVIDENCE_DIR ??
    resolve(repositoryRoot, "neo4j-runtime-logs/matched-state"),
);
const webPort = Number(process.env.NEO4J_MATCHED_STATE_WEB_PORT ?? 5195);
const desktopPort = Number(
  process.env.NEO4J_MATCHED_STATE_DESKTOP_PORT ?? 5196,
);
const webBaseURL = `http://127.0.0.1:${webPort}`;
const desktopBaseURL = `http://127.0.0.1:${desktopPort}`;

export default defineConfig({
  testDir: ".",
  testMatch: "neo4j-matched-state.spec.mjs",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: [["line"]],
  outputDir: resolve(evidenceRoot, "playwright"),
  preserveOutput: "always",
  timeout: 180_000,
  expect: {
    timeout: 20_000,
  },
  metadata: {
    desktopBaseURL,
    evidenceRoot,
    webBaseURL,
  },
  use: {
    browserName: "chromium",
    colorScheme: "light",
    locale: "en-US",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  webServer: [
    {
      command: `pnpm exec vite --host 127.0.0.1 --port ${webPort} --strictPort`,
      cwd: webRoot,
      url: webBaseURL,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `pnpm exec vite --host 127.0.0.1 --port ${desktopPort} --strictPort`,
      cwd: desktopRoot,
      url: desktopBaseURL,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
