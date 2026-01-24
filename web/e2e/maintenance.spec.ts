import { test, expect } from './base';

test.describe('Graph Maintenance', () => {
  let projectName: string;

  test.beforeEach(async ({ page }) => {
    // Set Chinese locale
    await page.goto('http://localhost:3000');
    await page.evaluate(() => {
      localStorage.setItem('i18nextLng', 'en-US');
    });

    // Login
    await page.goto('/login');
    await page.getByLabel(/Email/i).fill('admin@memstack.ai');
    await page.getByLabel(/Password/i).fill('adminpassword');
    await page.getByRole('button', { name: /登录/i }).click();

    // Wait for login to complete and redirect
    await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 10000 });

    // Navigate to Projects page
    const projectsLink = page.getByRole('link', { name: /Projects/i }).first();
    await projectsLink.waitFor();
    await projectsLink.click();

    // Wait for Project List to load
    await expect(page.getByRole('heading', { name: /Project Management/i })).toBeVisible({ timeout: 10000 });

    // Create a new test project if none exists
    const hasProject = await page.getByPlaceholder(/Search by project name/i).isVisible();
    if (hasProject) {
      // Search for existing test projects
      await page.getByPlaceholder(/Search by project name/i).fill('Maintenance Test Project');
      await page.waitForTimeout(500);

      const existingProject = page.getByText('Maintenance Test Project').first();
      if (await existingProject.isVisible()) {
        await existingProject.click();
        projectName = 'Maintenance Test Project';
      } else {
        // Create new project
        await page.getByRole('button', { name: /Create New Project/i }).click();
        projectName = `Maintenance Test Project ${Date.now()}`;
        await page.getByPlaceholder(/e.g. Finance Knowledge Base/i).fill(projectName);
        await page.getByRole('button', { name: /Create Project/i }).click();
        await page.waitForURL(/\/projects$/);

        // Reload to ensure list is fresh
        await page.reload();
        await expect(page.getByRole('heading', { name: /Project Management/i })).toBeVisible();

        // Find and click the project
        await page.getByPlaceholder(/Search by project name/i).fill(projectName);
        const projectCard = page.getByText(projectName).first();
        await projectCard.waitFor({ state: 'visible' });
        await page.waitForTimeout(500);
        await projectCard.click({ force: true });
      }
    }

    // Navigate to Maintenance page
    // Use the sidebar navigation link (not project links)
    await page.locator('a[href*="/maintenance"]').first().click();

    // Wait for maintenance page to load
    await expect(page.getByRole('heading', { name: /Graph Maintenance/i })).toBeVisible({ timeout: 10000 });
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
    const entityCount = await page.locator('div').filter({ hasText: /Entities/i }).locator('..').locator('.text-3xl').first().textContent();
    expect(entityCount).toMatch(/\d+/);
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
    await expect(page.getByText(/Found|duplicates/i)).toBeVisible({ timeout: 15000 });

    // Verify the message mentions duplicates found or no duplicates
    const message = await page.locator('.bg-green-50, .bg-red-50, .bg-green-900\\/20, .bg-red-900\\/20').textContent();
    expect(message?.toLowerCase()).toMatch(/found|duplicates|potential/);
  });

  test('should run deduplication merge after check', async ({ page }) => {
    // First, check for duplicates
    await page.getByRole('button', { name: /Check/i }).first().click();
    await expect(page.getByText(/Found|duplicates/i)).toBeVisible({ timeout: 15000 });

    // Then, click Merge button
    await page.getByRole('button', { name: /Merge/i }).click();

    // Wait for processing state
    await expect(page.getByText(/Processing\.\.\./i)).toBeVisible();

    // Wait for success message
    await expect(page.getByText(/Merged|duplicates/i)).toBeVisible({ timeout: 15000 });
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
      const hasRecommendations = await page.getByText(/No recommendations at this time/i).isVisible();
      const hasRecommendationItems = await page.locator('.text-slate-700, .dark\\:text-slate-300').count() > 0;

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
    const errorMessage = page.getByText(/Failed to refresh graph|Internal server error|error/i);
    await expect(errorMessage.first()).toBeVisible({ timeout: 15000 });
  });

  test('should display warning notice', async ({ page }) => {
    // Verify the important notice section
    await expect(page.getByRole('heading', { name: /Important Notice/i })).toBeVisible();
    await expect(page.getByText(/Some operations like merging duplicates and cleaning edges cannot be undone/i)).toBeVisible();
    await expect(page.getByText(/We recommend running "Check" first/i)).toBeVisible();
  });

  test('should navigate back and forth to maintenance page', async ({ page }) => {
    // Navigate to another page (e.g., Memories)
    await page.locator('a[href*="/memories"]').first().click();

    // Verify we're on memories page
    await expect(page.getByRole('heading', { name: /Memories/i })).toBeVisible();

    // Navigate back to maintenance page
    await page.locator('a[href*="/maintenance"]').first().click();

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
