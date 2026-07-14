import { expect, test } from '@playwright/test';

test.describe('backend-independent application smoke', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.evaluate(() => {
      localStorage.clear();
      localStorage.setItem('i18nextLng', 'en-US');
    });
    await page.reload();
  });

  test('renders the login boundary and demo credential affordance', async ({ page }) => {
    await expect(page.getByTestId('email-input')).toBeVisible();
    await expect(page.getByTestId('password-input')).toHaveAttribute('type', 'password');

    await page.getByRole('button', { name: /Use admin demo credentials/i }).click();

    await expect(page.getByTestId('email-input')).toHaveValue('admin@memstack.ai');
    await expect(page.getByTestId('password-input')).toHaveValue('adminpassword');
  });

  test('keeps protected routes behind the login boundary', async ({ page }) => {
    await page.goto('/tenant');
    await expect(page).toHaveURL(/\/login/);
  });
});
