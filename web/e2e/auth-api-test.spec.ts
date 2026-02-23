/**
 * Test API authentication directly
 */

import { test } from '@playwright/test';

test('test API authentication', async ({ page }) => {
  // Login first
  await page.goto('http://localhost:3000/login');
  await page.getByLabel(/Email/i).fill('admin@memstack.ai');
  await page.getByLabel(/Password/i).fill('adminpassword');
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

  console.log('Token:', token?.substring(0, 50));
  console.log('Token length:', token?.length);

  // Test API call using fetch
  const apiResult = await page.evaluate(async (accessToken) => {
    try {
      const response = await fetch('http://localhost:8000/api/v1/projects', {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Content-Type': 'application/json',
        },
      });
      const status = response.status;
      const text = await response.text();
      return { status, text };
    } catch (error) {
      return { error: String(error) };
    }
  }, token);

  console.log('API Result:', apiResult);

  // Test sandbox API
  const sandboxResult = await page.evaluate(async (accessToken) => {
    try {
      const response = await fetch('http://localhost:8000/api/v1/sandbox', {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Content-Type': 'application/json',
        },
      });
      const status = response.status;
      const text = await response.text();
      return { status, text };
    } catch (error) {
      return { error: String(error) };
    }
  }, token);

  console.log('Sandbox API Result:', sandboxResult);

  await page.waitForTimeout(3000);
});
