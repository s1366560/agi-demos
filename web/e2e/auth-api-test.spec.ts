/**
 * Test API authentication directly
 */

import { expect, test } from '@playwright/test';

test('test API authentication', async ({ page }) => {
  // Login first
  await page.goto('http://localhost:3000/login');
  await page.getByTestId('email-input').fill('admin@memstack.ai');
  await page.getByTestId('password-input').fill('adminpassword');
  await page.getByRole('button', { name: /Sign In/i }).click();

  // Wait for navigation
  await page.waitForURL(/\//, { timeout: 10000 });
  await page.waitForTimeout(3000);

  // Get token from localStorage
  const token = await page.evaluate(() => {
    const storage = localStorage.getItem('memstack-auth-storage');
    if (storage) {
      const parsed = JSON.parse(storage);
      return parsed.state?.token || parsed.token || null;
    }
    return null;
  });

  console.log('Token present:', Boolean(token), 'length:', token?.length ?? 0);

  // Test API call using fetch
  const apiResult = await page.evaluate(async (accessToken) => {
    try {
      const response = await fetch('http://localhost:8000/api/v1/projects', {
        headers: {
          Authorization: `Bearer ${accessToken}`,
          'Content-Type': 'application/json',
        },
      });
      return { ok: response.ok, status: response.status };
    } catch (error) {
      return { error: String(error) };
    }
  }, token);

  console.log('Projects API result:', apiResult);
  expect(apiResult).toEqual({ ok: true, status: 200 });

  // Test sandbox API
  const sandboxResult = await page.evaluate(async (accessToken) => {
    try {
      const response = await fetch('http://localhost:8000/api/v1/sandbox', {
        headers: {
          Authorization: `Bearer ${accessToken}`,
          'Content-Type': 'application/json',
        },
      });
      return { ok: response.ok, status: response.status };
    } catch (error) {
      return { error: String(error) };
    }
  }, token);

  console.log('Sandbox API result:', sandboxResult);
  expect(sandboxResult).toEqual({ ok: true, status: 200 });

  await page.waitForTimeout(3000);
});
