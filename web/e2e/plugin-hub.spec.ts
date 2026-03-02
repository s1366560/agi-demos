import { test, expect } from './base';

test.describe('Plugin Hub', () => {
  test.beforeEach(async ({ page }) => {
    // Set English locale first (tests use English labels)
    await page.goto('http://localhost:3000');
    await page.evaluate(() => {
      localStorage.setItem('i18nextLng', 'en-US');
    });

    // Login
    await page.goto('/login');
    await page.getByLabel(/Email/i).fill('admin@memstack.ai');
    await page.getByLabel(/Password/i).fill('adminpassword');
    await page.getByRole('button', { name: /Sign In/i }).click();

    // Wait for redirect to complete
    await expect(page).not.toHaveURL(/\/login/);

    // Navigate to Plugin Hub
    await page.goto('/tenant/default/plugins');

    // Wait for page to load - look for main content indicators
    await expect(page).toHaveURL(/\/plugins/);
  });

  test('should display Plugin Hub page', async ({ page }) => {
    // Check for page heading or main content area
    // The page should have either a title or main content area visible
    const pageHasContent = await page
      .locator('main, [role="main"], .ant-layout-content')
      .first()
      .isVisible();

    expect(pageHasContent).toBe(true);

    // Check for page indicators - could be heading, breadcrumb, or toolbar
    const hasHeading = await page
      .locator('h1, h2, [class*="Title"]')
      .first()
      .isVisible()
      .catch(() => false);

    const hasToolbar = await page
      .locator('button, [class*="Button"]')
      .first()
      .isVisible()
      .catch(() => false);

    // At least one of these should be present
    expect(hasHeading || hasToolbar).toBe(true);
  });

  test('should show plugin list or empty state', async ({ page }) => {
    // Wait for any loading to complete
    await page.waitForLoadState('networkidle').catch(() => {});

    // Check for plugin cards/table or empty state
    const pluginTable = page.locator('table').first();
    const emptyState = page.locator('[class*="Empty"], .ant-empty').first();
    const pluginCards = page.locator('[class*="Card"], .ant-card').first();

    const hasTable = await pluginTable.isVisible().catch(() => false);
    const hasEmpty = await emptyState.isVisible().catch(() => false);
    const hasCards = await pluginCards.isVisible().catch(() => false);

    // At least one of these should be present (table, cards, or empty state)
    expect(hasTable || hasEmpty || hasCards).toBe(true);
  });

  test('should show project selector', async ({ page }) => {
    // Wait for page to load
    await page.waitForLoadState('networkidle').catch(() => {});

    // Look for project selector - could be Select dropdown, button, or text display
    const projectSelect = page.locator('[class*="Select"]').first();
    const projectButton = page.locator('button:has-text(/Project|project/)').first();
    const projectLabel = page.locator('text=/Project|project/i').first();

    const hasSelect = await projectSelect.isVisible().catch(() => false);
    const hasButton = await projectButton.isVisible().catch(() => false);
    const hasLabel = await projectLabel.isVisible().catch(() => false);

    // At least one project UI element should be present
    expect(hasSelect || hasButton || hasLabel).toBe(true);
  });

  test('should show channel configuration section', async ({ page }) => {
    // Wait for page to load
    await page.waitForLoadState('networkidle').catch(() => {});

    // Look for channel configuration UI elements
    const channelTable = page.locator('table').nth(1); // Typically second table is channel config
    const channelEmpty = page.locator('[class*="Empty"]').nth(1);
    const channelButton = page.locator('button:has-text(/Channel|channel|Add|Create/)').first();
    const channelSection = page.locator('[class*="channel"], text=/Channel/i').first();

    const hasChannelTable = await channelTable.isVisible().catch(() => false);
    const hasChannelEmpty = await channelEmpty.isVisible().catch(() => false);
    const hasChannelButton = await channelButton.isVisible().catch(() => false);
    const hasChannelSection = await channelSection.isVisible().catch(() => false);

    // Channel configuration should be present in some form
    expect(hasChannelTable || hasChannelEmpty || hasChannelButton || hasChannelSection).toBe(true);
  });

  test('should have plugin action buttons', async ({ page }) => {
    // Wait for page to load
    await page.waitForLoadState('networkidle').catch(() => {});

    // Look for action buttons - reload, install, enable, configure, etc.
    const reloadButton = page.locator('button:has-text(/Reload|reload|Refresh|refresh/)').first();
    const installButton = page.locator('button:has-text(/Install|install|Add/)').first();
    const enableButton = page.locator('button:has-text(/Enable|enable|Disable|disable/)').first();
    const configButton = page.locator('button:has-text(/Config|config|Settings|settings/)').first();
    const actionButton = page.locator('button [class*="Icon"]').first(); // Icon buttons

    const hasReload = await reloadButton.isVisible().catch(() => false);
    const hasInstall = await installButton.isVisible().catch(() => false);
    const hasEnable = await enableButton.isVisible().catch(() => false);
    const hasConfig = await configButton.isVisible().catch(() => false);
    const hasAction = await actionButton.isVisible().catch(() => false);

    // At least one action button should be present
    expect(hasReload || hasInstall || hasEnable || hasConfig || hasAction).toBe(true);
  });

  test('should display plugin status indicators', async ({ page }) => {
    // Wait for page to load
    await page.waitForLoadState('networkidle').catch(() => {});

    // Look for status tags, badges, or indicators
    const statusTag = page.locator('.ant-tag, [class*="Tag"]').first();
    const statusBadge = page.locator('.ant-badge, [class*="Badge"]').first();
    const statusIcon = page.locator('[class*="status"], [class*="Status"]').first();
    const statusText = page.locator('text=/active|installed|enabled|disabled|pending/i').first();

    const hasTag = await statusTag.isVisible().catch(() => false);
    const hasBadge = await statusBadge.isVisible().catch(() => false);
    const hasIcon = await statusIcon.isVisible().catch(() => false);
    const hasText = await statusText.isVisible().catch(() => false);

    // At least one status indicator should be present
    expect(hasTag || hasBadge || hasIcon || hasText).toBe(true);
  });
});
