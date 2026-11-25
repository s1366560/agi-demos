import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: 'rich-package-pages.spec.ts',
  timeout: 60_000,
  use: {
    ...devices['Desktop Chrome'],
    baseURL: 'http://127.0.0.1:3345',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'corepack pnpm exec vite --mode project-packages --host 127.0.0.1 --port 3345 --strictPort',
    url: 'http://127.0.0.1:3345',
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
