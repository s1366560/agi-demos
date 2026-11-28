import { defineConfig, devices } from '@playwright/test';

import { packageHostServer, packageHostTests } from './playwright.project-packages.config';

const port = Number(process.env.PLAYWRIGHT_WEB_PORT ?? 3000);
const baseURL = `http://localhost:${port}`;

/**
 * See https://playwright.dev/docs/test-configuration.
 */
export default defineConfig({
  testDir: './e2e',
  testIgnore: ['**/sandbox-debug.spec.ts', '**/sandbox-manual.spec.ts'],
  /* Run tests in files in parallel */
  fullyParallel: true,
  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,
  /* Retry on CI only */
  retries: process.env.CI ? 2 : 0,
  /* Opt out of parallel tests on CI. */
  workers: process.env.CI ? 1 : undefined,
  /* Reporter to use. See https://playwright.dev/docs/test-reporters */
  reporter: [['html', { open: 'never' }], ['list']],
  /* Shared settings for all the projects below. See https://playwright.dev/docs/api/class-testoptions. */
  use: {
    /* Base URL to use in actions like `await page.goto('/')`. */
    baseURL,

    /* Collect trace when retrying the failed test. See https://playwright.dev/docs/trace-viewer */
    trace: 'on-first-retry',

    /* Increase action timeout to handle potential slow UI/network */
    actionTimeout: 10000,
  },

  /* Increase global timeout */
  timeout: 60000,

  /* Configure projects for major browsers */
  projects: [
    {
      name: 'chromium',
      testIgnore: ['**/sandbox-debug.spec.ts', '**/sandbox-manual.spec.ts', ...packageHostTests],
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'package-host',
      testMatch: packageHostTests,
      use: { ...devices['Desktop Chrome'], baseURL: packageHostServer.url },
    },
  ],

  /* Run your local dev server before starting the tests */
  webServer: [
    {
      command: `corepack pnpm dev --mode full --port ${port}`,
      url: baseURL,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    packageHostServer,
  ],
});
