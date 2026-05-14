/**
 * i18n.spec.ts
 *
 * End-to-end smoke tests for language switching. These exercises require a
 * running backend on http://localhost:8000 and frontend on
 * http://localhost:3000 (see Makefile: make dev / make dev-web).
 *
 * The current state of the project ships with translation catalogs but the
 * language toggle in the UI is being finalized. These tests are marked with
 * `test.fixme` so they appear in `pnpm test:e2e` reports without failing the
 * suite. Remove the `.fixme` once the toggle and locale persistence are
 * wired end-to-end.
 */

import { test, expect } from '@playwright/test';

const ADMIN_EMAIL = 'admin@memstack.ai';
const ADMIN_PASSWORD = 'adminpassword';

async function login(page: import('@playwright/test').Page) {
  await page.goto('http://localhost:3000/login');
  await page.getByLabel(/Email/i).fill(ADMIN_EMAIL);
  await page.getByLabel(/Password/i).fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: /Sign In|登录/i }).click();
  await page.waitForURL(/\/(projects|workspace|tenant|$)/, { timeout: 15000 });
}

test.describe('i18n: language switch', () => {
  test.fixme('English (en-US) UI renders English navigation labels', async ({ page }) => {
    await login(page);
    // Switch to en-US via the language toggle (selector TBD once finalized).
    await page.getByRole('button', { name: /Language|语言/ }).click();
    await page.getByRole('menuitem', { name: /English/ }).click();

    await expect(page.getByRole('link', { name: 'Projects' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Memory' })).toBeVisible();
  });

  test.fixme('Chinese (zh-CN) UI renders translated navigation labels', async ({
    page,
  }) => {
    await login(page);
    await page.getByRole('button', { name: /Language|语言/ }).click();
    await page.getByRole('menuitem', { name: /中文/ }).click();

    await expect(page.getByRole('link', { name: '项目' })).toBeVisible();
    await expect(page.getByRole('link', { name: '记忆' })).toBeVisible();
  });

  test.fixme('Language preference persists across reloads', async ({ page }) => {
    await login(page);
    await page.getByRole('button', { name: /Language|语言/ }).click();
    await page.getByRole('menuitem', { name: /中文/ }).click();
    await page.reload();
    await expect(page.getByRole('link', { name: '项目' })).toBeVisible();
  });
});

test.describe('i18n: backend Accept-Language', () => {
  test.fixme(
    'Backend validation errors are translated when Accept-Language=zh-CN',
    async ({ request }) => {
      const response = await request.post(
        'http://localhost:8000/api/v1/auth/token',
        {
          headers: { 'Accept-Language': 'zh-CN' },
          form: { username: 'bogus@example.com', password: 'wrong' },
        }
      );
      expect(response.status()).toBe(401);
      const body = await response.json();
      // The exact translated string is owned by the catalog; smoke-test by
      // asserting the response contains CJK content rather than pinning the
      // exact wording.
      expect(typeof body.detail).toBe('string');
      expect(body.detail).toMatch(/[\u4e00-\u9fff]/);
    }
  );

  test.fixme(
    'Backend validation errors stay English when Accept-Language=en-US',
    async ({ request }) => {
      const response = await request.post(
        'http://localhost:8000/api/v1/auth/token',
        {
          headers: { 'Accept-Language': 'en-US' },
          form: { username: 'bogus@example.com', password: 'wrong' },
        }
      );
      expect(response.status()).toBe(401);
      const body = await response.json();
      expect(typeof body.detail).toBe('string');
      expect(body.detail).not.toMatch(/[\u4e00-\u9fff]/);
    }
  );
});
