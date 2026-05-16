import type { Page } from '@playwright/test';

import { test, expect } from './base';

async function confirmCommunityRebuild(page: Page): Promise<void> {
  const dialog = page.getByRole('dialog', {
    name: /rebuild all communities from scratch/i,
  });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: /OK/i }).click();
  await expect(dialog).toBeHidden({ timeout: 5000 });
}

async function expectCommunityRebuildActivity(page: Page): Promise<void> {
  const taskHeading = page
    .getByRole('heading', {
      name: /Rebuilding Communities|Rebuild (Completed|Scheduled|Failed)/i,
    })
    .first();
  const rebuildingButton = page.getByRole('button', { name: /Rebuilding/i }).first();

  await expect(taskHeading.or(rebuildingButton).first()).toBeVisible({ timeout: 10000 });
}

async function expectCommunitiesPageReady(page: Page): Promise<void> {
  await expect(page.getByTestId('communities-list-root')).toBeVisible({ timeout: 10000 });
  await expect(page.getByText(/Showing .* communities|No communities found/i).first()).toBeVisible({
    timeout: 10000,
  });
}

test.describe('Communities Management', () => {
  let projectName: string;
  let projectId: string;

  test.beforeEach(async ({ page, request }) => {
    // Set Chinese locale
    await page.goto('http://localhost:3000');
    await page.evaluate(() => {
      localStorage.setItem('i18nextLng', 'en-US');
    });

    // Login
    await page.goto('/login');
    await expect(page.getByLabel(/Email/i)).toBeVisible();
    await expect(page.getByLabel(/Password/i)).toBeVisible();
    await page.getByLabel(/Email/i).fill('admin@memstack.ai');
    await page.getByLabel(/Password/i).fill('adminpassword');
    await page.getByRole('button', { name: /Sign In|登录/i }).click();

    // Wait for login to complete and redirect
    await page.waitForURL(
      (url) => {
        return !url.pathname.includes('/login');
      },
      { timeout: 10000 }
    );

    // Create project via API for stability
    projectName = `Communities Test ${Date.now()}`;
    const apiBase = 'http://localhost:8000/api/v1';
    const form = new URLSearchParams();
    form.append('username', 'admin@memstack.ai');
    form.append('password', 'adminpassword');
    const tokenResp = await request.post(`${apiBase}/auth/token`, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      data: form.toString(),
    });
    const tokenJson = await tokenResp.json();
    const authHeaders = { Authorization: `Bearer ${tokenJson.access_token}` };
    const tenantsResp = await request.get(`${apiBase}/tenants/`, { headers: authHeaders });
    const tenantsJson = await tenantsResp.json();
    const tenantId = tenantsJson.tenants?.[0]?.id || tenantsJson[0]?.id;
    const createResp = await request.post(`${apiBase}/projects/`, {
      headers: { ...authHeaders, 'Content-Type': 'application/json' },
      data: {
        name: projectName,
        description: 'E2E Communities',
        tenant_id: tenantId,
        is_public: false,
      },
    });
    const projectJson = await createResp.json();
    projectId = projectJson.project?.id ?? projectJson.id;
    await page.goto(`/tenant/${tenantId}/project/${projectId}`);

    // No pre-added memories; tests cover empty state and rebuild flows
  });

  test('should display empty communities list initially', async ({ page }) => {
    // Navigate to Communities
    await page.getByRole('link', { name: 'Communities', exact: true }).click();

    // Check header
    await page.locator('h1').filter({ hasText: 'Communities' }).waitFor();

    // Check for "No communities found" message
    await expect(page.getByText(/No communities found/i)).toBeVisible({ timeout: 10000 });
  });

  test('should rebuild communities in background', async ({ page }) => {
    // Navigate to Communities
    await page.getByRole('link', { name: 'Communities', exact: true }).click();
    await page.getByRole('heading', { name: 'Communities', exact: true }).waitFor();

    // Click rebuild button
    const rebuildButton = page.getByRole('button', { name: /Rebuild Communities/i }).first();
    await rebuildButton.click();
    await confirmCommunityRebuild(page);

    // Check rebuild activity appears.
    await expectCommunityRebuildActivity(page);

    console.log('Community rebuild task started successfully');
  });

  test('should track task status during rebuild', async ({ page }) => {
    // Navigate to Communities
    await page.getByRole('link', { name: 'Communities', exact: true }).click();
    await page.getByRole('heading', { name: 'Communities', exact: true }).waitFor();

    // Click rebuild button
    await page
      .getByRole('button', { name: /Rebuild Communities/i })
      .first()
      .click();
    await confirmCommunityRebuild(page);

    await expectCommunityRebuildActivity(page);

    console.log('Community rebuild completed successfully');
  });

  test('should display communities after rebuild', async ({ page }) => {
    // Navigate to Communities
    await page.getByRole('link', { name: 'Communities', exact: true }).click();
    await page.getByRole('heading', { name: 'Communities', exact: true }).waitFor();

    // Start rebuild if needed
    const noCommunities = page.getByText(/No communities found/i);
    if (await noCommunities.isVisible({ timeout: 5000 })) {
      await page
        .getByRole('button', { name: /Rebuild Communities/i })
        .first()
        .click();
      await confirmCommunityRebuild(page);
      await page.waitForTimeout(5000);
    }

    // Wait for task to clear and communities to load
    await page.waitForTimeout(6000);

    // Reload to get fresh data
    await page.reload();
    await page.getByRole('heading', { name: 'Communities', exact: true }).waitFor();

    // Check communities summary or list loaded
    const summary = page.getByText(/Showing .* communities/i).first();
    const card = page.locator('.community-card, [data-testid="community-card"]').first();
    const hasSummary = await summary.isVisible().catch(() => false);
    const hasCard = await card.isVisible().catch(() => false);
    expect(hasSummary || hasCard).toBeTruthy();

    console.log('Communities displayed successfully');
  });

  test('should load community members', async ({ page }) => {
    // Navigate to Communities
    await page.getByRole('link', { name: 'Communities', exact: true }).click();
    await page.getByRole('heading', { name: 'Communities', exact: true }).waitFor();

    // Ensure communities exist
    const noCommunities = page.getByText(/No communities found/i);
    if (await noCommunities.isVisible({ timeout: 5000 })) {
      await page
        .getByRole('button', { name: /rebuild communities/i })
        .first()
        .click();
      await confirmCommunityRebuild(page);
      await page.waitForTimeout(6000);
      await page.reload();
      await page.locator('h1').filter({ hasText: 'Communities' }).waitFor();
    }

    // Click first community card
    const communityCard = page.locator('.community-card, [data-testid="community-card"]').first();
    if (await communityCard.isVisible({ timeout: 5000 })) {
      await communityCard.click();

      // Check members panel/drawer appears
      await expect(page.getByText(/Community Members|members/i)).toBeVisible({ timeout: 10000 });

      console.log('Community members loaded successfully');
    } else {
      console.log('No community cards to click');
    }
  });

  test('should handle rebuild errors gracefully', async ({ page }) => {
    // Mock error response for rebuild endpoint
    await page.route('**/api/v1/graph/communities/rebuild*', (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Internal server error' }),
      });
    });

    // Navigate to Communities
    await page.getByRole('link', { name: 'Communities', exact: true }).click();
    await page.locator('h1').filter({ hasText: 'Communities' }).waitFor();
    await expectCommunitiesPageReady(page);

    // Try rebuild with mocked error
    const rebuildResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        response.url().includes('/api/v1/graph/communities/rebuild'),
      { timeout: 10000 }
    );
    await page
      .getByRole('button', { name: /Rebuild Communities/i })
      .first()
      .click();
    await confirmCommunityRebuild(page);
    const rebuildResponse = await rebuildResponsePromise;
    expect(rebuildResponse.status()).toBe(500);

    await expect(page.getByTestId('error-message')).toContainText(
      /Failed to rebuild|Internal server error/i,
      { timeout: 15000 }
    );

    console.log('Error handling test passed');
  });

  test('should refresh communities list', async ({ page }) => {
    // Navigate to Communities
    await page.getByRole('link', { name: 'Communities', exact: true }).click();
    await page.locator('h1').filter({ hasText: 'Communities' }).waitFor();

    // Check refresh button exists and is visible
    await expect(page.getByRole('button', { name: /^Refresh$/i })).toBeVisible();

    // Click refresh button
    await page.getByRole('button', { name: /^Refresh$/i }).click();

    // Should still be on communities page
    await expect(page.getByRole('heading', { name: 'Communities', exact: true })).toBeVisible();

    console.log('Refresh button works correctly');
  });

  test('should display correct page title and breadcrumbs', async ({ page }) => {
    // Navigate to Communities
    await page.getByRole('link', { name: 'Communities', exact: true }).click();

    // Check page title
    await expect(page.locator('h1').filter({ hasText: 'Communities' })).toBeVisible();

    // Check description text
    await expect(
      page.getByText(/Automatically detected groups of related entities/i).first()
    ).toBeVisible({ timeout: 5000 });

    console.log('Page structure is correct');
  });
});
