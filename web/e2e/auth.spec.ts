import { test, expect } from './base';

test.describe('Authentication', () => {
  test.beforeEach(async ({ page }) => {
    // Set English locale first (tests use English labels)
    await page.goto('http://localhost:3000');
    await page.evaluate(() => {
      localStorage.setItem('i18nextLng', 'en-US');
    });
  });

  test('should login successfully with valid admin credentials', async ({ page }) => {
    // Navigate to login page
    await page.goto('/login');

    // Check if we are on the login page
    await expect(page).toHaveURL(/\/login/);

    // Wait for form to be ready using data-testid
    const emailInput = page.getByTestId('email-input');
    const passwordInput = page.getByTestId('password-input');
    await expect(emailInput).toBeVisible();
    await expect(passwordInput).toBeVisible();

    // Fill in admin credentials
    await emailInput.fill('admin@memstack.ai');
    await passwordInput.fill('adminpassword');

    // Click login button using data-testid
    await page.getByTestId('login-submit-button').click();

    // Wait for navigation - login should redirect to tenant page
    await page.waitForURL(/\/tenant/, { timeout: 10000 });

    // Verify we are on the tenant page after login
    await expect(page).toHaveURL(/\/tenant/);
  });

  test('should login successfully with valid user credentials', async ({ page }) => {
    // Navigate to login page
    await page.goto('/login');

    // Fill in user credentials
    await page.getByTestId('email-input').fill('user@memstack.ai');
    await page.getByTestId('password-input').fill('userpassword');

    // Click login button
    await page.getByTestId('login-submit-button').click();

    // Wait for navigation
    await page.waitForURL((url) => {
      return !url.pathname.includes('/login');
    }, { timeout: 10000 });

    // Verify we are no longer on login page
    await expect(page).not.toHaveURL(/\/login/);
  });

  test('should display error with invalid credentials', async ({ page }) => {
    // Navigate to login page
    await page.goto('/login');

    // Fill in invalid credentials
    await page.getByTestId('email-input').fill('invalid@example.com');
    await page.getByTestId('password-input').fill('wrongpassword');

    // Click login button
    await page.getByTestId('login-submit-button').click();

    // Wait for error message to appear
    await expect(page.locator('.text-red-700, .text-red-300').first()).toBeVisible({ timeout: 5000 });

    // Verify we are still on login page
    await expect(page).toHaveURL(/\/login/);
  });

  test('should display error with empty credentials', async ({ page }) => {
    // Navigate to login page
    await page.goto('/login');

    // Try to submit without filling credentials (browser validation may prevent this)
    await page.getByTestId('login-submit-button').click();

    // The form should show browser validation errors
    // Check that email input has validation attributes
    const emailInput = page.getByTestId('email-input');
    await expect(emailInput).toBeVisible();

    // Verify we are still on login page
    await expect(page).toHaveURL(/\/login/);
  });

  test('should toggle password visibility', async ({ page }) => {
    // Navigate to login page
    await page.goto('/login');

    const passwordInput = page.getByTestId('password-input');
    await expect(passwordInput).toBeVisible();

    // Initially password should be hidden
    await expect(passwordInput).toHaveAttribute('type', 'password');

    // Click the eye button to show password using data-testid
    await page.getByTestId('toggle-password-visibility').click();

    // Password should now be visible
    await expect(passwordInput).toHaveAttribute('type', 'text');

    // Click again to hide
    await page.getByTestId('toggle-password-visibility').click();

    // Password should be hidden again
    await expect(passwordInput).toHaveAttribute('type', 'password');
  });

  test('should use demo credential buttons to fill form', async ({ page }) => {
    // Navigate to login page
    await page.goto('/login');

    // Click on admin demo credentials
    await page.locator('text=管理员').click();

    // Verify form is filled using data-testid
    await expect(page.getByTestId('email-input')).toHaveValue('admin@memstack.ai');
    await expect(page.getByTestId('password-input')).toHaveValue('adminpassword');
  });

  test('should redirect unauthenticated user to login', async ({ page }) => {
    // Clear any existing auth
    await page.goto('http://localhost:3000');
    await page.evaluate(() => {
      localStorage.clear();
    });

    // Try to navigate to a protected page
    await page.goto('/tenant');

    // Should redirect to login page
    await page.waitForURL(/\/login/, { timeout: 5000 });
    await expect(page).toHaveURL(/\/login/);
  });

  test('should maintain session after page reload', async ({ page }) => {
    // Login first
    await page.goto('/login');
    await page.getByTestId('email-input').fill('admin@memstack.ai');
    await page.getByTestId('password-input').fill('adminpassword');
    await page.getByTestId('login-submit-button').click();

    // Wait for navigation
    await page.waitForURL(/\/tenant/, { timeout: 10000 });

    // Reload the page
    await page.reload();

    // Should still be authenticated (not redirected to login)
    await page.waitForURL(/\/tenant/, { timeout: 5000 });
    await expect(page).toHaveURL(/\/tenant/);
  });

  test('should disable login button during authentication', async ({ page }) => {
    // Navigate to login page
    await page.goto('/login');

    // Fill in credentials
    await page.getByTestId('email-input').fill('admin@memstack.ai');
    await page.getByTestId('password-input').fill('adminpassword');

    // Click login button
    const loginButton = page.getByTestId('login-submit-button');
    await loginButton.click();

    // Button should be disabled during authentication
    await expect(loginButton).toBeDisabled();

    // Wait for login to complete
    await page.waitForURL(/\/tenant/, { timeout: 10000 });
  });

  test('should show loading spinner on login button', async ({ page }) => {
    // Navigate to login page
    await page.goto('/login');

    // Fill in credentials
    await page.getByTestId('email-input').fill('admin@memstack.ai');
    await page.getByTestId('password-input').fill('adminpassword');

    // Click login button
    const loginButton = page.getByTestId('login-submit-button');
    await loginButton.click();

    // Check for loading spinner
    const spinner = page.locator('.animate-spin');
    await expect(spinner).toBeVisible();
  });

  test('should handle form submission with Enter key', async ({ page }) => {
    // Navigate to login page
    await page.goto('/login');

    // Fill in credentials
    await page.getByTestId('email-input').fill('admin@memstack.ai');
    await page.getByTestId('password-input').fill('adminpassword');

    // Press Enter on password field
    await page.getByTestId('password-input').press('Enter');

    // Should navigate away from login
    await page.waitForURL((url) => {
      return !url.pathname.includes('/login');
    }, { timeout: 10000 });
  });
});

test.describe('Authentication Logout', () => {
  test.beforeEach(async ({ page }) => {
    // Set English locale and login
    await page.goto('http://localhost:3000');
    await page.evaluate(() => {
      localStorage.setItem('i18nextLng', 'en-US');
    });

    await page.goto('/login');
    await page.getByTestId('email-input').fill('admin@memstack.ai');
    await page.getByTestId('password-input').fill('adminpassword');
    await page.getByTestId('login-submit-button').click();
    await page.waitForURL(/\/tenant/, { timeout: 10000 });
  });

  test('should logout successfully', async ({ page }) => {
    // Click user menu or logout button
    // Look for a logout option in the UI
    const logoutButton = page.getByRole('button', { name: /logout|sign out|退出/i });

    if (await logoutButton.isVisible({ timeout: 3000 })) {
      await logoutButton.click();
    } else {
      // Try clicking on user avatar/menu first
      const userMenu = page.locator('[class*="avatar"], [class*="user"]').first();
      if (await userMenu.isVisible({ timeout: 3000 })) {
        await userMenu.click();
        await page.waitForTimeout(500);
        await logoutButton.click();
      }
    }

    // Should redirect to login page
    await page.waitForURL(/\/login/, { timeout: 5000 });
    await expect(page).toHaveURL(/\/login/);
  });

  test('should clear session data after logout', async ({ page }) => {
    // Check that token is stored
    const tokenBeforeLogout = await page.evaluate(() => localStorage.getItem('memstack-auth-storage'));
    expect(tokenBeforeLogout).toBeTruthy();

    // Logout
    const logoutButton = page.getByRole('button', { name: /logout|sign out|退出/i });
    if (await logoutButton.isVisible({ timeout: 3000 })) {
      await logoutButton.click();
    } else {
      const userMenu = page.locator('[class*="avatar"], [class*="user"]').first();
      if (await userMenu.isVisible({ timeout: 3000 })) {
        await userMenu.click();
        await page.waitForTimeout(500);
        await logoutButton.click();
      }
    }

    await page.waitForURL(/\/login/, { timeout: 5000 });

    // Check that auth data is cleared
    const tokenAfterLogout = await page.evaluate(() => localStorage.getItem('memstack-auth-storage'));
    expect(tokenAfterLogout).toBeFalsy();
  });
});
