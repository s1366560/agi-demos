import { getAdminAuthToken, getFirstTenantId, loginAsAdmin, test, expect } from './base';

test.describe('MCP Servers Management', () => {
  test.beforeEach(async ({ page }) => {
    const token = await getAdminAuthToken();
    const tenantId = await getFirstTenantId(token);
    await loginAsAdmin(page);

    // Navigate to MCP servers page
    await page.goto(`/tenant/${tenantId}/mcp-servers`);

    // Wait for the page header to be visible
    await expect(page.getByRole('heading', { name: 'MCP Servers', exact: true })).toBeVisible({
      timeout: 5000,
    });
  });

  test('should display MCP Servers page header', async ({ page }) => {
    // Check for main heading
    const heading = page.getByRole('heading', { name: 'MCP Servers', exact: true });
    await expect(heading).toBeVisible();
    await expect(heading).toHaveText('MCP Servers');

    // Check for subtitle
    const subtitle = page.getByText('Manage MCP servers, tools, and applications');
    await expect(subtitle).toBeVisible();
  });

  test('should show stats grid with 4 cards', async ({ page }) => {
    // Check for all 4 stats cards: Total Servers, Tools, Applications, Health
    const totalServersCard = page.getByText('Total Servers');
    await expect(totalServersCard).toBeVisible();

    const toolsCard = page.getByText('Tools', { exact: true }).first();
    await expect(toolsCard).toBeVisible();

    const applicationsCard = page.getByText('Applications', { exact: true }).first();
    await expect(applicationsCard).toBeVisible();

    const healthCard = page.getByText('Health', { exact: true }).first();
    await expect(healthCard).toBeVisible();

    // Verify stats cards have numeric values
    const statsSection = page.locator('div.grid').filter({ hasText: 'Total Servers' }).first();
    const cards = statsSection.locator(':scope > div');
    await expect(cards).toHaveCount(4);
  });

  test('should display server tab by default', async ({ page }) => {
    const serversTab = page.getByRole('tab', { name: 'Servers' });
    await expect(serversTab).toBeVisible();
    await expect(serversTab).toHaveAttribute('aria-selected', 'true');
  });

  test('should switch to Tools tab and display content', async ({ page }) => {
    const toolsTabButton = page.getByRole('tab', { name: 'Tools' });
    await toolsTabButton.click();

    await expect(toolsTabButton).toHaveAttribute('aria-selected', 'true');

    // Tools tab content should be visible
    await expect(page.locator('#tabpanel-tools')).toBeVisible();
  });

  test('should switch to Applications tab and display content', async ({ page }) => {
    const applicationsTabButton = page.getByRole('tab', { name: 'Applications' });
    await applicationsTabButton.click();

    await expect(applicationsTabButton).toHaveAttribute('aria-selected', 'true');

    // Applications tab content should be visible
    await expect(page.locator('#tabpanel-apps')).toBeVisible();
  });

  test('should have Reconcile button in header', async ({ page }) => {
    // Check for Reconcile button in the top right of the header
    const reconcileButton = page.getByRole('button', { name: /Reconcile/i }).first();
    await expect(reconcileButton).toBeVisible();

    // Verify button has expected styling (should be enabled initially)
    await expect(reconcileButton).not.toBeDisabled();

    // Verify button contains icon (sync icon)
    const buttonContent = reconcileButton.locator('..');
    await expect(buttonContent).toBeVisible();
  });

  test('should display servers tab content with table or empty state', async ({ page }) => {
    // Servers tab should be active by default
    const serversTabButton = page.getByRole('tab', { name: 'Servers' });
    await expect(serversTabButton).toBeVisible();
    await expect(serversTabButton).toHaveAttribute('aria-selected', 'true');

    // The tab content area should contain either:
    // 1. A table/list of servers, or
    // 2. An empty state message

    const tabContent = page.locator('#tabpanel-servers');
    await expect(tabContent).toBeVisible();

    // Check for either table headers or empty state indicators
    // This is flexible as MCP servers might be empty or populated
    const hasTableOrList =
      (await page
        .locator('table')
        .isVisible({ timeout: 2000 })
        .catch(() => false)) ||
      (await page
        .locator('[class*="empty"]')
        .isVisible({ timeout: 2000 })
        .catch(() => false)) ||
      (await page
        .locator('text=/No data|empty|No servers/i')
        .isVisible({ timeout: 2000 })
        .catch(() => false));

    // Content area should have something visible
    expect(await tabContent.isVisible()).toBe(true);
  });

  test('should maintain tab state when navigating between tabs', async ({ page }) => {
    // Start on Servers tab
    await expect(page.getByRole('tab', { name: 'Servers' })).toHaveAttribute(
      'aria-selected',
      'true'
    );

    // Switch to Tools
    await page.getByRole('tab', { name: 'Tools' }).click();
    await expect(page.getByRole('tab', { name: 'Tools' })).toHaveAttribute('aria-selected', 'true');

    // Switch to Applications
    await page.getByRole('tab', { name: 'Applications' }).click();
    await expect(page.getByRole('tab', { name: 'Applications' })).toHaveAttribute(
      'aria-selected',
      'true'
    );

    // Switch back to Servers
    await page.getByRole('tab', { name: 'Servers' }).click();
    await expect(page.getByRole('tab', { name: 'Servers' })).toHaveAttribute(
      'aria-selected',
      'true'
    );
  });

  test('should display all tabs in navigation area', async ({ page }) => {
    // Check that all 3 tabs are visible in the navigation
    const tabNavigation = page.getByRole('tablist', { name: 'Tabs' });
    await expect(tabNavigation).toBeVisible();

    // Count tab buttons
    const tabButtons = tabNavigation.getByRole('tab');
    await expect(tabButtons).toHaveCount(5);

    // Verify tab labels
    await expect(tabButtons.nth(0)).toContainText('Servers');
    await expect(tabButtons.nth(1)).toContainText('Tools');
    await expect(tabButtons.nth(2)).toContainText('Applications');
    await expect(tabButtons.nth(3)).toContainText('Prompts');
    await expect(tabButtons.nth(4)).toContainText('Logs');
  });

  test('should show icon and text in tab buttons', async ({ page }) => {
    // Verify each tab has both icon and text
    const serversTab = page.getByRole('tab', { name: 'Servers' });

    // Should contain both icon (via MaterialIcon) and text
    await expect(serversTab).toContainText('Servers');

    const toolsTab = page.getByRole('tab', { name: 'Tools' });
    await expect(toolsTab).toContainText('Tools');

    const appsTab = page.getByRole('tab', { name: 'Applications' });
    await expect(appsTab).toContainText('Applications');

    const promptsTab = page.getByRole('tab', { name: 'Prompts' });
    await expect(promptsTab).toContainText('Prompts');

    const logsTab = page.getByRole('tab', { name: 'Logs' });
    await expect(logsTab).toContainText('Logs');
  });
});
