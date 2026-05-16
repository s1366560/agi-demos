import { createTestProject, getAdminAuthToken, loginAsAdmin, test, expect } from './base';

test.describe('Plugin Hub', () => {
  test.beforeEach(async ({ page }) => {
    const token = await getAdminAuthToken();
    const projectName = `Playwright E2E Test Plugin ${Date.now()}`;
    const project = await createTestProject({
      name: projectName,
      description: 'Plugin Hub E2E project',
      token,
    });
    await loginAsAdmin(page);

    // Navigate to Plugin Hub
    await page.goto(`/tenant/${project.tenantId}/plugins?projectId=${project.id}`);

    // Wait for page to load - look for main content indicators
    await expect(page).toHaveURL(/\/plugins/);
    await expect(page.getByRole('heading', { name: 'Plugin Hub' })).toBeVisible({
      timeout: 10000,
    });
  });

  test('should display Plugin Hub page', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Plugin Hub' })).toBeVisible();
    await expect(
      page.getByText('Discover, install, and manage plugins for your workspace')
    ).toBeVisible();
  });

  test('should show plugin list or empty state', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Installed Plugins' })).toBeVisible();
    await expect(page.locator('.ant-table').first()).toBeVisible();
  });

  test('should show project selector', async ({ page }) => {
    await expect(page.getByRole('combobox').nth(1)).toBeVisible();
  });

  test('should show channel configuration section', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Configured Channels' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Add Channel' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Channel Type' })).toBeVisible();
  });

  test('should have plugin action buttons', async ({ page }) => {
    await expect(page.getByRole('button', { name: 'Install', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Reload', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Add Channel', exact: true })).toBeVisible();
  });

  test('should display plugin status indicators', async ({ page }) => {
    await expect(
      page.getByRole('heading', { name: 'Channel Catalog & Diagnostics' })
    ).toBeVisible();
    await expect(
      page.locator('.ant-tag').first().or(page.getByText('No channel adapters discovered.'))
    ).toBeVisible();
  });
});
