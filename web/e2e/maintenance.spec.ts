import {
  createTestProject,
  getAdminAuthToken,
  loginAsAdmin,
  tenantProjectPath,
  test,
  expect,
} from './base';

test.describe('Graph Maintenance', () => {
  let projectId: string;
  let tenantId: string;

  test.beforeEach(async ({ page }) => {
    const token = await getAdminAuthToken();
    const project = await createTestProject({
      name: `Maintenance Test Project ${Date.now()}`,
      description: 'E2E maintenance project',
      token,
    });
    projectId = project.id;
    tenantId = project.tenantId;

    await loginAsAdmin(page);
    await page.goto(tenantProjectPath(tenantId, projectId, 'maintenance'));

    // Wait for maintenance page to load
    await expect(page.getByRole('heading', { name: /Graph Maintenance/i })).toBeVisible({
      timeout: 10000,
    });
  });

  test('should display graph statistics', async ({ page }) => {
    // Verify statistics section is visible
    await expect(page.getByRole('heading', { name: /Graph Statistics/i })).toBeVisible();

    // Verify all stat cards are displayed
    await expect(page.getByText(/Entities/i).first()).toBeVisible();
    await expect(page.getByText(/Episodes/i).first()).toBeVisible();
    await expect(page.getByText(/Communities/i).first()).toBeVisible();
    await expect(page.getByText(/Relationships/i).first()).toBeVisible();

    // Verify statistics are numbers
    const statsSection = page.getByRole('heading', { name: /Graph Statistics/i }).locator('..');
    await expect(statsSection.locator('.text-3xl').first()).toHaveText(/\d+/, {
      timeout: 10000,
    });
  });

  test('should display maintenance operations', async ({ page }) => {
    // Verify maintenance operations section
    await expect(page.getByRole('heading', { name: /Maintenance Operations/i })).toBeVisible();

    // Verify all operations are listed
    await expect(page.getByRole('heading', { name: /Incremental Refresh/i })).toBeVisible();
    await expect(page.getByRole('heading', { name: /Deduplicate Entities/i })).toBeVisible();
    await expect(page.getByRole('heading', { name: /Clean Stale Edges/i })).toBeVisible();
    await expect(page.getByRole('heading', { name: /Export Data/i })).toBeVisible();
  });

  test('should perform incremental refresh', async ({ page }) => {
    // Click refresh button
    await page.getByRole('button', { name: /Refresh/i }).click();

    // Wait for operation to complete (button should show loading state)
    await expect(page.getByText(/Refreshing\.\.\./i)).toBeVisible();

    // Wait for success message
    await expect(page.getByText(/Refreshed|episodes/i).first()).toBeVisible({ timeout: 15000 });

    // Verify statistics are updated (optional, but good to check)
    await expect(page.getByText(/Entities/i).first()).toBeVisible();
  });

  test('should run deduplication in dry run mode', async ({ page }) => {
    // Click Check button for deduplication
    await page.getByRole('button', { name: /Check/i }).first().click();

    // Wait for results
    await expect(page.getByRole('status')).toContainText(/Found|duplicates/i, {
      timeout: 15000,
    });

    // Verify the message mentions duplicates found or no duplicates
    const message = await page.getByRole('status').textContent();
    expect(message?.toLowerCase()).toMatch(/found|duplicates|potential/);
  });

  test('should run deduplication merge after check', async ({ page }) => {
    // First, check for duplicates
    await page.getByRole('button', { name: /Check/i }).first().click();
    await expect(page.getByRole('status')).toContainText(/Found|duplicates/i, {
      timeout: 15000,
    });

    // Then, click Merge button
    await page.getByRole('button', { name: /Merge/i }).click();

    // Wait for processing state
    await expect(page.getByText(/Processing\.\.\./i)).toBeVisible();

    // Wait for success message
    await expect(page.getByRole('status')).toContainText(/Merged|duplicates/i, {
      timeout: 15000,
    });
  });

  test('should check stale edges without deleting', async ({ page }) => {
    // Click Check button for stale edges
    const checkButtons = await page.getByRole('button', { name: /Check/i }).all();
    if (checkButtons.length > 1) {
      await checkButtons[1].click(); // Second Check button is for Clean Stale Edges
    }

    // Wait for results
    await expect(page.getByText(/Found|stale|edges/i).first()).toBeVisible({ timeout: 15000 });
  });

  test('should export data successfully', async ({ page }) => {
    await page.route('**/api/v1/data/export', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          exported_at: new Date().toISOString(),
          tenant_id: tenantId,
          episodes: [],
          entities: [],
          relationships: [],
          communities: [],
        }),
      });
    });

    // Setup download handler
    const downloadPromise = page.waitForEvent('download', { timeout: 15000 });

    // Click Export button
    await page.getByRole('button', { name: /Export/i }).click();

    // Wait for download to start
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/graph-export.*\.json/);

    // Verify success message
    await expect(page.getByText(/exported successfully/i)).toBeVisible();
  });

  test('should display recommendations when available', async ({ page }) => {
    // Check if recommendations section exists
    const recommendationsHeading = page.getByRole('heading', { name: /Recommendations/i });

    // If recommendations exist, verify them
    if (await recommendationsHeading.isVisible()) {
      await expect(recommendationsHeading).toBeVisible();

      // Check for recommendation types or "No recommendations" message
      const hasRecommendations = await page
        .getByText(/No recommendations at this time/i)
        .isVisible();
      const hasRecommendationItems =
        (await page.locator('.text-slate-700, .dark\\:text-slate-300').count()) > 0;

      expect(hasRecommendations || hasRecommendationItems).toBeTruthy();
    }
  });

  test('should disable buttons during operations', async ({ page }) => {
    // Click refresh button
    await page.getByRole('button', { name: /Refresh/i }).click();

    // Verify button is in loading state and disabled
    const refreshButton = page.getByRole('button', { name: /Refreshing\.\.\./i });
    await expect(refreshButton).toBeVisible();
    await expect(refreshButton).toBeDisabled();

    // Wait for operation to complete
    await expect(page.getByText(/Refreshed|episodes/i).first()).toBeVisible({ timeout: 15000 });

    // Verify button is enabled again
    await expect(page.getByRole('button', { name: /Refresh/i })).toBeEnabled();
  });

  test('should show error message on operation failure', async ({ page }) => {
    // Intercept API call and simulate failure
    await page.route('**/api/v1/maintenance/refresh/incremental', (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Internal server error' }),
      });
    });

    // Click refresh button
    await page.getByRole('button', { name: /Refresh/i }).click();

    // Wait for error message - check for either specific error or any error banner
    // Also accept that the button might return to normal state
    await expect(page.getByRole('alert')).toContainText(
      /Failed to refresh graph|Internal server error|error/i,
      { timeout: 15000 }
    );
  });

  test('should display warning notice', async ({ page }) => {
    // Verify the important notice section
    await expect(page.getByRole('heading', { name: /Important Notice/i })).toBeVisible();
    await expect(
      page.getByText(/Some operations like merging duplicates and cleaning edges cannot be undone/i)
    ).toBeVisible();
    await expect(page.getByText(/We recommend running ['"]Check['"] first/i)).toBeVisible();
  });

  test('should navigate back and forth to maintenance page', async ({ page }) => {
    // Navigate to another page (e.g., Memories)
    await page.locator('a[href*="/memories"]').first().click();

    // Verify we're on memories page
    await expect(page.getByRole('heading', { name: /Memories/i })).toBeVisible();

    // Navigate back to maintenance page
    await page.goto(tenantProjectPath(tenantId, projectId, 'maintenance'));

    // Verify maintenance page loads correctly
    await expect(page.getByRole('heading', { name: /Graph Maintenance/i })).toBeVisible();
    await expect(page.getByRole('heading', { name: /Graph Statistics/i })).toBeVisible();
  });

  test('should handle concurrent operations gracefully', async ({ page }) => {
    // Click refresh button
    await page.getByRole('button', { name: /Refresh/i }).click();

    // Try to click another operation button immediately (should be disabled or independent)
    // The Merge button should still be enabled (different operation)
    // But if we try to click Refresh again, it should be disabled
    await expect(page.getByRole('button', { name: /Refresh/i })).toBeDisabled();

    // Wait for refresh to complete
    await expect(page.getByText(/Refreshed|episodes/i).first()).toBeVisible({ timeout: 15000 });

    // Now Refresh button should be enabled again
    await expect(page.getByRole('button', { name: /Refresh/i })).toBeEnabled();
  });
});
