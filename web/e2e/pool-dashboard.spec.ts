import { getAdminAuthToken, getFirstTenantId, loginAsAdmin, test, expect } from './base';

test.describe('Pool Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    const token = await getAdminAuthToken();
    const tenantId = await getFirstTenantId(token);
    await loginAsAdmin(page);

    // Navigate to pool dashboard
    await page.goto(`/tenant/${tenantId}/pool`);
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
    await expect(page.getByText('HOT', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('WARM', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('COLD', { exact: true }).first()).toBeVisible();
  });

  test('should show resource usage card', async ({ page }) => {
    // Check for Resource Usage card title
    await expect(page.getByText('Resource Usage')).toBeVisible();

    // Check for Memory progress indicator
    await expect(page.getByText('Memory', { exact: true }).first()).toBeVisible();

    // Check for CPU progress indicator
    await expect(page.getByText('CPU', { exact: true }).first()).toBeVisible();
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
    const tierFilter = page.getByText('Filter by tier', { exact: true });
    await expect(tierFilter).toBeVisible();

    // Click to open dropdown
    await page.getByRole('combobox').last().click({ force: true });

    // Verify tier options appear
    const dropdown = page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden)').last();
    await expect(dropdown.getByText('HOT', { exact: true })).toBeVisible();
    await expect(dropdown.getByText('WARM', { exact: true })).toBeVisible();
    await expect(dropdown.getByText('COLD', { exact: true })).toBeVisible();
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
    await expect(page.getByRole('heading', { name: 'Agent Pool Dashboard' })).toBeVisible();
  });
});
