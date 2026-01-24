import { test, expect } from './base';

test.describe('Authentication', () => {
  test('should login successfully with valid credentials', async ({ page }) => {
    // Set English locale first (tests use English labels)
    await page.goto('http://localhost:3000');
    await page.evaluate(() => {
      localStorage.setItem('i18nextLng', 'en-US');
    });

    // Navigate to login page
    await page.goto('/login');

    // Check if we are on the login page
    await expect(page).toHaveURL(/\/login/);

    // Wait for form to be ready
    await expect(page.getByLabel(/Email/i)).toBeVisible();
    await expect(page.getByLabel(/Password/i)).toBeVisible();

    // Fill in credentials
    await page.getByLabel(/Email/i).fill('admin@memstack.ai');
    await page.getByLabel(/Password/i).fill('adminpassword');

    // Click login button
    await page.getByRole('button', { name: /Sign In/i }).click();

    // Wait for navigation - login should redirect away from /login
    // Increase timeout to allow for API call and navigation
    await page.waitForURL((url) => {
      return !url.pathname.includes('/login');
    }, { timeout: 10000 });

    // Verify we are no longer on login page
    await expect(page).not.toHaveURL(/\/login/);
  });
});
