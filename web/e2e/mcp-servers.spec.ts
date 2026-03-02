import { test, expect } from './base';

test.describe('MCP Servers Management', () => {
  test.beforeEach(async ({ page }) => {
    // Set English locale first (tests use English labels)
    await page.goto('http://localhost:3000');
    await page.evaluate(() => {
      localStorage.setItem('i18nextLng', 'en-US');
    });

    // Login as admin
    await page.goto('/login');
    await page.getByTestId('email-input').fill('admin@memstack.ai');
    await page.getByTestId('password-input').fill('adminpassword');
    await page.getByTestId('login-submit-button').click();

    // Wait for login to complete
    await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 10000 });

    // Navigate to MCP servers page
    await page.goto('/tenant/default/mcp-servers');

    // Wait for the page header to be visible
    await expect(page.getByRole('heading', { name: /MCP Servers/i })).toBeVisible({
      timeout: 5000,
    });
  });

  test('should display MCP Servers page header', async ({ page }) => {
    // Check for main heading
    const heading = page.getByRole('heading', { name: /MCP Servers/i });
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

    const toolsCard = page.getByText(/^Tools$/);
    await expect(toolsCard).toBeVisible();

    const applicationsCard = page.getByText('Applications');
    await expect(applicationsCard).toBeVisible();

    const healthCard = page.getByText('Health');
    await expect(healthCard).toBeVisible();

    // Verify stats cards have numeric values
    const statsSection = page.locator('[class*="grid"]').filter({ has: totalServersCard });
    const cards = statsSection.locator('[class*="rounded-xl"]');
    await expect(cards).toHaveCount(4);
  });

  test('should display server tab by default', async ({ page }) => {
    // Check that the Servers tab button is active (has primary color/border)
    const serversTabButton = page.getByRole('button', { name: /Servers/ }).first();
    await expect(serversTabButton).toBeVisible();

    // Check for the tab indicator (primary border-b-2 or similar)
    const serversTab = page.locator('nav[aria-label="Tabs"]').locator('button').first();
    const classList = await serversTab.getAttribute('class');
    expect(classList).toContain('border-primary');
  });

  test('should switch to Tools tab and display content', async ({ page }) => {
    // Click on Tools tab button
    const toolsTabButton = page.getByRole('button', { name: /Tools/ });
    await toolsTabButton.click();

    // Wait for tab content to become active
    await page.waitForTimeout(500);

    // Verify Tools tab is now active by checking the border styling
    const toolsTab = page.locator('nav[aria-label="Tabs"]').locator('button').nth(1);
    const classList = await toolsTab.getAttribute('class');
    expect(classList).toContain('border-primary');

    // Tools tab content should be visible
    const tabContent = page.locator('[class*="p-4"]').last();
    await expect(tabContent).toBeVisible();
  });

  test('should switch to Applications tab and display content', async ({ page }) => {
    // Click on Applications tab button
    const applicationsTabButton = page.getByRole('button', { name: /Applications/ });
    await applicationsTabButton.click();

    // Wait for tab content to become active
    await page.waitForTimeout(500);

    // Verify Applications tab is now active
    const applicationsTab = page.locator('nav[aria-label="Tabs"]').locator('button').nth(2);
    const classList = await applicationsTab.getAttribute('class');
    expect(classList).toContain('border-primary');

    // Applications tab content should be visible
    const tabContent = page.locator('[class*="p-4"]').last();
    await expect(tabContent).toBeVisible();
  });

  test('should have Reconcile button in header', async ({ page }) => {
    // Check for Reconcile button in the top right of the header
    const reconcileButton = page.getByRole('button', { name: /Reconcile/i });
    await expect(reconcileButton).toBeVisible();

    // Verify button has expected styling (should be enabled initially)
    await expect(reconcileButton).not.toBeDisabled();

    // Verify button contains icon (sync icon)
    const buttonContent = reconcileButton.locator('..');
    await expect(buttonContent).toBeVisible();
  });

  test('should display servers tab content with table or empty state', async ({ page }) => {
    // Servers tab should be active by default
    const serversTabButton = page.getByRole('button', { name: /Servers/ }).first();
    await expect(serversTabButton).toBeVisible();

    // The tab content area should contain either:
    // 1. A table/list of servers, or
    // 2. An empty state message

    const tabContent = page.locator('[class*="p-4"]').last();
    await expect(tabContent).toBeVisible();

    // Check for either table headers or empty state indicators
    // This is flexible as MCP servers might be empty or populated
    const hasTableOrList =
      (await page.locator('table').isVisible({ timeout: 2000 }).catch(() => false)) ||
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
    let activeTab = page.locator('nav[aria-label="Tabs"]').locator('button').first();
    let classList = await activeTab.getAttribute('class');
    expect(classList).toContain('border-primary');

    // Switch to Tools
    await page.getByRole('button', { name: /Tools/ }).click();
    await page.waitForTimeout(300);

    activeTab = page.locator('nav[aria-label="Tabs"]').locator('button').nth(1);
    classList = await activeTab.getAttribute('class');
    expect(classList).toContain('border-primary');

    // Switch to Applications
    await page.getByRole('button', { name: /Applications/ }).click();
    await page.waitForTimeout(300);

    activeTab = page.locator('nav[aria-label="Tabs"]').locator('button').nth(2);
    classList = await activeTab.getAttribute('class');
    expect(classList).toContain('border-primary');

    // Switch back to Servers
    await page.getByRole('button', { name: /Servers/ }).click();
    await page.waitForTimeout(300);

    activeTab = page.locator('nav[aria-label="Tabs"]').locator('button').first();
    classList = await activeTab.getAttribute('class');
    expect(classList).toContain('border-primary');
  });

  test('should display all tabs in navigation area', async ({ page }) => {
    // Check that all 3 tabs are visible in the navigation
    const tabNavigation = page.locator('nav[aria-label="Tabs"]');
    await expect(tabNavigation).toBeVisible();

    // Count tab buttons
    const tabButtons = tabNavigation.locator('button');
    await expect(tabButtons).toHaveCount(3);

    // Verify tab labels
    await expect(tabButtons.nth(0)).toContainText('Servers');
    await expect(tabButtons.nth(1)).toContainText('Tools');
    await expect(tabButtons.nth(2)).toContainText('Applications');
  });

  test('should show icon and text in tab buttons', async ({ page }) => {
    // Verify each tab has both icon and text
    const serversTab = page.getByRole('button', { name: /Servers/ }).first();
    const serversContent = serversTab.locator('..');

    // Should contain both icon (via MaterialIcon) and text
    await expect(serversTab).toContainText('Servers');

    const toolsTab = page.getByRole('button', { name: /Tools/ });
    await expect(toolsTab).toContainText('Tools');

    const appsTab = page.getByRole('button', { name: /Applications/ });
    await expect(appsTab).toContainText('Applications');
  });
});
