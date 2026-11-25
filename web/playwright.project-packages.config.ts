import { defineConfig, devices } from '@playwright/test';

export const packageHostTests = ['**/rich-package-pages.spec.ts', '**/plugin-market.spec.ts'];
export const packageHostServer = {
  command: 'corepack pnpm dev --mode project-packages --host 127.0.0.1 --port 3345 --strictPort',
  url: 'http://127.0.0.1:3345',
  reuseExistingServer: false,
  timeout: 120_000,
};
export default defineConfig({
  testDir: './e2e',
  testMatch: packageHostTests,
  timeout: 60_000,
  use: {
    ...devices['Desktop Chrome'],
    baseURL: packageHostServer.url,
    trace: 'retain-on-failure',
  },
  webServer: packageHostServer,
});
