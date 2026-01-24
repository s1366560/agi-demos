import { test, expect } from './base';

test.describe('Project Management', () => {
    // Assuming we need to login before accessing project management
    test.beforeEach(async ({ page }) => {
        // Set English locale first (tests use English labels)
        await page.goto('http://localhost:3000');
        await page.evaluate(() => {
            localStorage.setItem('i18nextLng', 'en-US');
        });

        await page.goto('/login');
        // Assuming auth state is preserved or we need to login each time.
        // For simplicity, logging in each time. In a real setup, we might reuse auth state.
        await page.getByLabel(/Email/i).fill('admin@memstack.ai');
        await page.getByLabel(/Password/i).fill('adminpassword');
        await page.getByRole('button', { name: /Sign In/i }).click();

        // Wait for redirect to dashboard/tenant overview
        // Assuming default redirect goes to a tenant workspace or list
        await expect(page).not.toHaveURL(/\/login/);
    });

    test('should create a new project', async ({ page }) => {
        // Handle dialogs (confirm delete)
        page.on('dialog', dialog => dialog.accept());

        // Navigate to project list
        // Use first() to avoid strict mode violation if multiple "Projects" links exist (e.g. sidebar and dashboard widget)
        // Or target the sidebar specifically if possible. For now, first() is a quick fix if both lead to same place.
        const projectsLink = page.getByRole('link', { name: /Projects/i }).first();
        if (await projectsLink.isVisible()) {
            await projectsLink.click();
        }

        // Check if we need to cleanup (if limit reached or just to be safe)
        // We can try to delete a project if any exists
        const moreButton = page.locator('button:has(.material-symbols-outlined:text("more_vert"))').first();
        if (await moreButton.isVisible()) {
            await moreButton.click();
            await page.getByText('Delete Project').click();
            // Wait for deletion to reflect (optional, or just wait for list update)
            await page.waitForTimeout(1000);
        }

        // Now on Project List page
        await page.getByRole('button', { name: /Create New Project/i }).click();

        // Now on New Project page
        await expect(page).toHaveURL(/\/projects\/new/);

        // Fill form
        const projectName = `Test Project ${Date.now()}`;
        // Use getByRole 'textbox' or a more generic label match to avoid issues with asterisks or hidden text
        // The input has a placeholder "e.g. Finance Knowledge Base"
        await page.getByPlaceholder(/e.g. Finance Knowledge Base/i).fill(projectName);
        // Use placeholder for description as well
        await page.getByPlaceholder(/Briefly describe the purpose of this project/i).fill('E2E Test Project Description');

        // Capture console logs to debug backend errors
        page.on('console', msg => console.log(`BROWSER LOG: ${msg.text()}`));

        // Submit
        await page.getByRole('button', { name: /Create Project/i }).click();

        // Wait for navigation to complete
        await page.waitForURL(/\/projects$/);

        // Ensure the list is updated
        await page.reload();
        await expect(page.getByRole('heading', { name: /Project Management/i })).toBeVisible();

        // Search for the project to ensure visibility
        await page.getByPlaceholder(/Search by project name/i).fill(projectName);

        await expect(page.getByText(projectName)).toBeVisible();
    });

    test('should list existing projects', async ({ page }) => {
        // Navigate to project list
        const projectsLink = page.getByRole('link', { name: /Projects/i }).first();
        if (await projectsLink.isVisible()) {
            await projectsLink.click();
        }

        // Check if the list container is present
        // Based on ProjectList.tsx, we can look for "Project Management" header
        await expect(page.getByRole('heading', { name: /Project Management/i })).toBeVisible();

        // Check if grid is visible (or empty state)
        // There is a search input
        await expect(page.getByPlaceholder(/Search by project name/i)).toBeVisible();
    });
});
