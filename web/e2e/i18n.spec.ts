/**
 * i18n.spec.ts
 *
 * End-to-end smoke tests for language switching. These exercises require the
 * backend on http://localhost:8000 and frontend on http://localhost:3000.
 */

import { API_BASE, test, expect } from './base';

async function chooseLanguage(page: import('@playwright/test').Page, label: string) {
  await page.getByTestId('language-switcher').click();
  await page
    .locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden)')
    .getByText(label, { exact: true })
    .click();
}

test.describe('i18n: language switch', () => {
  test('English (en-US) UI renders English login labels', async ({ page }) => {
    await page.goto('/login');
    await chooseLanguage(page, 'English');

    await expect(page.getByLabel('Email')).toBeVisible();
    await expect(page.getByLabel('Password')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Sign In' })).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('lang', 'en-US');
  });

  test('Chinese (zh-CN) UI renders translated login labels', async ({ page }) => {
    await page.goto('/login');
    await chooseLanguage(page, '简体中文');

    await expect(page.getByLabel('邮箱')).toBeVisible();
    await expect(page.getByLabel('密码')).toBeVisible();
    await expect(page.getByRole('button', { name: '登录' })).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
  });

  test('Language preference persists across reloads', async ({ page }) => {
    await page.goto('/login');
    await chooseLanguage(page, '简体中文');
    await page.reload();
    await expect(page.getByRole('button', { name: '登录' })).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
  });
});

test.describe('i18n: backend Accept-Language', () => {
  test('Backend validation errors are translated when Accept-Language=zh-CN', async ({
    request,
  }) => {
    const response = await request.post(`${API_BASE}/api/v1/auth/token`, {
      headers: { 'Accept-Language': 'zh-CN' },
      form: { username: 'bogus@example.com', password: 'wrong' },
    });
    expect(response.status()).toBe(401);
    expect(response.headers()['content-language']).toBe('zh-CN');
    const body = await response.json();
    expect(typeof body.detail).toBe('string');
    expect(body.detail).toMatch(/[\u4e00-\u9fff]/);
  });

  test('Backend validation errors stay English when Accept-Language=en-US', async ({
    request,
  }) => {
    const response = await request.post(`${API_BASE}/api/v1/auth/token`, {
      headers: { 'Accept-Language': 'en-US' },
      form: { username: 'bogus@example.com', password: 'wrong' },
    });
    expect(response.status()).toBe(401);
    expect(response.headers()['content-language']).toBe('en-US');
    const body = await response.json();
    expect(typeof body.detail).toBe('string');
    expect(body.detail).not.toMatch(/[\u4e00-\u9fff]/);
  });
});
