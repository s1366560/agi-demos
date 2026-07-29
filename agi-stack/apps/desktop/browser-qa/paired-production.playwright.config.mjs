import { dirname, isAbsolute, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "@playwright/test";

const browserQaRoot = dirname(fileURLToPath(import.meta.url));
const desktopRoot = resolve(browserQaRoot, "..");
const repositoryRoot = resolve(desktopRoot, "../../..");
const webRoot = resolve(repositoryRoot, "web");
const webPort = Number(process.env.AGISTACK_PAIRED_WEB_PORT ?? 5191);
const desktopPort = Number(process.env.AGISTACK_PAIRED_DESKTOP_PORT ?? 5192);
const webBaseURL = `http://127.0.0.1:${webPort}`;
const desktopBaseURL = `http://127.0.0.1:${desktopPort}`;
const buildReceiptPath = process.env.AGISTACK_PAIRED_BUILD_RECEIPT;
const invocationNonce = process.env.AGISTACK_PAIRED_INVOCATION_NONCE;

if (
  !buildReceiptPath ||
  !isAbsolute(buildReceiptPath) ||
  !/^[0-9a-f]{64}$/u.test(invocationNonce ?? "")
) {
  throw new Error(
    "paired Playwright requires a fresh orchestration receipt and invocation nonce",
  );
}

export default defineConfig({
  testDir: ".",
  testMatch: "paired-production.spec.mjs",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: [["line"]],
  outputDir: "paired-results",
  preserveOutput: "always",
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  metadata: {
    webBaseURL,
    desktopBaseURL,
  },
  use: {
    browserName: "chromium",
    screenshot: "on",
    trace: "off",
  },
  webServer: [
    {
      command: `corepack pnpm exec vite preview --host 127.0.0.1 --port ${webPort} --strictPort --outDir dist`,
      cwd: webRoot,
      url: webBaseURL,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `corepack pnpm exec vite preview --host 127.0.0.1 --port ${desktopPort} --strictPort --outDir out/renderer`,
      cwd: desktopRoot,
      url: desktopBaseURL,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
