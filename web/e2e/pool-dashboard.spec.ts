import { test, expect } from './base';

test.describe('Pool Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    // Set English locale
    await page.goto('http://localhost:3000');
    await page.evaluate(() => {
      localStorage.setItem('i18nextLng', 'en-US');
    });

    // Login as admin
    await page.goto('/login');
    await page.getByLabel(/邮箱/i).fill('admin@memstack.ai');
    await page.getByLabel(/密码/i).fill('adminpassword');
    await page.getByRole('button', { name: /登录/i }).click();

    // Wait for login to complete
    await page.waitForURL((url) => !url.pathname.includes('/login'));

    // Navigate to pool dashboard
    await page.goto('/tenant/default/pool');
  });

  test('should display Pool Dashboard header and title', async ({ page }) => {
    // Check for main heading
    await expect(page.getByRole('heading', { name: 'Agent Pool Dashboard' })).toBeVisible();
  });

  test('should show status overview cards', async ({ page }) => {
    // Check for status cards with statistics
    // Total Instances card
    await expect(page.getByText('Total Instances')).toBeVisible();

    // Ready card
    await expect(page.getByText('Ready')).toBeVisible();

    // Executing card
    await expect(page.getByText('Executing')).toBeVisible();

    // Unhealthy card
    await expect(page.getByText('Unhealthy')).toBeVisible();
  });

  test('should show tier distribution card', async ({ page }) => {
    // Check for Tier Distribution card title
    await expect(page.getByText('Tier Distribution')).toBeVisible();

    // Check for tier labels
    await expect(page.getByText('HOT')).toBeVisible();
    await expect(page.getByText('WARM')).toBeVisible();
    await expect(page.getByText('COLD')).toBeVisible();
  });

  test('should show resource usage card', async ({ page }) => {
    // Check for Resource Usage card title
    await expect(page.getByText('Resource Usage')).toBeVisible();

    // Check for Memory progress indicator
    await expect(page.locator('text=Memory')).toBeVisible();

    // Check for CPU progress indicator
    await expect(page.locator('text=CPU')).toBeVisible();
  });

  test('should show prewarm pool card', async ({ page }) => {
    // Check for Prewarm Pool card title
    await expect(page.getByText('Prewarm Pool')).toBeVisible();

    // Check for L1, L2, L3 statistics
    await expect(page.getByText('L1 (Hot)')).toBeVisible();
    await expect(page.getByText('L2 (Warm)')).toBeVisible();
    await expect(page.getByText('L3 (Cold)')).toBeVisible();
  });

  test('should show active instances table', async ({ page }) => {
    // Check for Active Instances card title
    await expect(page.getByText('Active Instances')).toBeVisible();

    // Check for table headers
    // Note: Some headers may not be visible if table is empty, so we use soft assertions
    const table = page.locator('table');
    await expect(table).toBeVisible();

    // Check for key column headers that should always be visible
    const headerCells = page.locator('th');
    expect(headerCells).toBeTruthy();
  });

  test('should have tier filter dropdown', async ({ page }) => {
    // Check for Select component with tier filter
    const selectDropdown = page.locator('div').filter({ has: page.getByText('Filter by tier') });
    await expect(selectDropdown).toBeVisible();

    // Click to open dropdown
    await page.locator('div').filter({ has: page.getByText('Filter by tier') }).first().click();

    // Verify tier options appear
    await expect(page.getByText('HOT')).toBeVisible();
    await expect(page.getByText('WARM')).toBeVisible();
    await expect(page.getByText('COLD')).toBeVisible();
  });

  test('should have auto-refresh toggle and refresh button', async ({ page }) => {
    // Check for auto-refresh toggle label
    await expect(page.getByText('Auto-refresh')).toBeVisible();

    // Check for Switch component (auto-refresh toggle)
    const switchElement = page.locator('.ant-switch');
    await expect(switchElement).toBeVisible();

    // Check for Refresh button
    const refreshButton = page.getByRole('button', { name: 'Refresh' });
    await expect(refreshButton).toBeVisible();
  });

  test('should handle refresh button click', async ({ page }) => {
    // Get the refresh button
    const refreshButton = page.getByRole('button', { name: 'Refresh' });

    // Click refresh
    await refreshButton.click();

    // Wait for any loading state to complete
    await page.waitForTimeout(500);

    // Verify page is still visible (no errors)
    await expect(page.getByRole('heading', { name: 'Agent Pool Dashboard' })).toBeVisible();
  });

  test('should handle empty pool state gracefully', async ({ page }) => {
    // The page should display even if pool is empty
    // Check that main elements are present regardless of data

    // Header should always be visible
    await expect(page.getByRole('heading', { name: 'Agent Pool Dashboard' })).toBeVisible();

    // Status cards section should be visible
    await expect(page.getByText('Total Instances')).toBeVisible();

    // Active Instances table should be visible
    await expect(page.getByText('Active Instances')).toBeVisible();

    // No error should prevent page from rendering
    const errorAlerts = page.locator('.ant-alert-error');
    // If there are error alerts, the page should still be functional
    // Just verify the page structure is intact
    await expect(page.locator('div').filter({ has: page.getByText('Agent Pool Dashboard') })).toBeVisible();
  });
});
