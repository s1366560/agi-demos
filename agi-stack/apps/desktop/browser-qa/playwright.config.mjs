import { existsSync, readdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { defineConfig } from '@playwright/test';

const port = Number(process.env.AGISTACK_DESKTOP_QA_PORT ?? 5187);
const baseURL = `http://127.0.0.1:${port}`;
const executablePath = resolveChromiumExecutable();
const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

function resolveChromiumExecutable() {
  const explicitPath = process.env.AGISTACK_DESKTOP_QA_CHROMIUM;
  if (explicitPath) {
    if (!existsSync(explicitPath)) {
      throw new Error('AGISTACK_DESKTOP_QA_CHROMIUM does not point to a readable browser');
    }
    return explicitPath;
  }

  if (process.platform === 'darwin') {
    const cacheRoot = join(homedir(), 'Library', 'Caches', 'ms-playwright');
    if (existsSync(cacheRoot)) {
      const cachedShell = readdirSync(cacheRoot)
        .filter((name) => name.startsWith('chromium_headless_shell-'))
        .sort()
        .reverse()
        .map((name) =>
          join(
            cacheRoot,
            name,
            'chrome-headless-shell-mac-arm64',
            'chrome-headless-shell',
          ),
        )
        .find((candidate) => existsSync(candidate));
      if (cachedShell) return cachedShell;
    }
    const systemChrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
    if (existsSync(systemChrome)) return systemChrome;
  }
  return undefined;
}

export default defineConfig({
  testDir: '.',
  testMatch: 'desktop-parity.spec.mjs',
  fullyParallel: true,
  forbidOnly: true,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : 4,
  reporter: [
    ['line'],
    ['html', { open: 'never', outputFolder: 'report' }],
  ],
  outputDir: 'results',
  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },
  use: {
    baseURL,
    browserName: 'chromium',
    colorScheme: 'dark',
    launchOptions: executablePath ? { executablePath } : {},
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: `corepack pnpm exec vite --host 127.0.0.1 --port ${port} --strictPort`,
    cwd: desktopRoot,
    url: baseURL,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
