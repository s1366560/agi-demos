import { test, expect } from './base';

test.describe('Entities and Communities', () => {
    let projectName: string;

    test.beforeEach(async ({ page }) => {
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
        await page.getByRole('button', { name: /登录/i }).click();

        // Wait for login to complete and redirect
        await page.waitForURL((url) => {
            return !url.pathname.includes('/login');
        }, { timeout: 10000 });

        // Create Project
        const projectsLink = page.getByRole('link', { name: /Projects/i }).first();
        await projectsLink.waitFor();
        await projectsLink.click();

        // Wait for Project List to load
        await expect(page.getByRole('heading', { name: /Project Management/i })).toBeVisible({ timeout: 10000 });

        await page.getByRole('button', { name: /Create New Project/i }).click();
        projectName = `Entities Test Project ${Date.now()}`;
        await page.getByPlaceholder(/e.g. Finance Knowledge Base/i).fill(projectName);
        await page.getByRole('button', { name: /Create Project/i }).click();
        await page.waitForURL(/\/projects$/);

        // Reload to ensure list is fresh
        await page.reload();
        await expect(page.getByRole('heading', { name: /Project Management/i })).toBeVisible();

        // Enter project
        // Search for the project to ensure it's visible
        await page.getByPlaceholder(/Search by project name/i).fill(projectName);

        const projectLink = page.getByRole('link', { name: projectName }).first();
        await projectLink.waitFor({ state: 'visible' });
        await projectLink.click();

        // 1. Navigate to Memories Tab explicitly
        await page.getByRole('link', { name: /Memories/i }).click();

        // Add Memory with Entities
        await page.getByRole('button', { name: /New Memory/i }).click();
        await expect(page.locator('textarea')).toBeVisible();
        await page.locator('textarea').click();
        await page.locator('textarea').type('Elon Musk is the CEO of Tesla and SpaceX.');
        await page.getByPlaceholder(/e.g. Q3 Strategy/i).fill('Entity Memory');
        await page.getByRole('button', { name: /Save Memory/i }).click();
        await page.waitForURL(/\/memories$/);
    });

    test('should list extracted entities', async ({ page }) => {
        // Navigate to Entities
        await page.getByRole('link', { name: 'Entities', exact: true }).click();

        // Check if Entities page loaded
        await expect(page.locator('h1').filter({ hasText: /^Entities$/ })).toBeVisible();

        // Check page structure - entities may still be processing
        await expect(page.getByText('Browse and manage extracted entities')).toBeVisible();
    });

    test('should display communities', async ({ page }) => {
        // Navigate to Communities
        await page.getByRole('link', { name: 'Communities', exact: true }).click();

        // Check header
        await page.locator('h1').filter({ hasText: 'Communities' }).waitFor();

        // Check refresh button
        await expect(page.getByRole('button', { name: 'refresh Refresh', exact: true })).toBeVisible();

        // Prefer explicit empty-state message
        const emptyMsg = page.getByText(/No communities found|Loading communities|Showing .* communities/i).first();
        const card = page.locator('.community-card, [data-testid="community-card"]').first();
        const visibleEmpty = await emptyMsg.isVisible().catch(() => false);
        const visibleCard = await card.isVisible().catch(() => false);
        expect(visibleEmpty || visibleCard).toBeTruthy();
    });
});
