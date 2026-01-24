import { test, expect } from './base';

test.describe('Memory Operations', () => {
    const projectName = `Test Project ${Date.now()}`;

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
        await expect(page).not.toHaveURL(/\/login/);

        // Navigate to Projects
        const projectsLink = page.getByRole('link', { name: /Projects/i }).first();
        if (await projectsLink.isVisible()) {
            await projectsLink.click();
        }

        // Create new project
        await page.getByRole('button', { name: /Create New Project/i }).click();
        await page.getByPlaceholder(/e.g. Finance Knowledge Base/i).fill(projectName);
        await page.getByRole('button', { name: /Create Project/i }).click();
        
        // Wait for project creation and navigation
        await page.waitForURL(/\/projects$/);
        await page.reload();
        await expect(page.getByRole('heading', { name: /Project Management/i })).toBeVisible();

        // Navigate into the project
        await page.getByPlaceholder(/Search by project name/i).fill(projectName);
        // Wait for search results to update
        await page.waitForTimeout(1000); 
        
        const projectCard = page.getByText(projectName).first();
        await projectCard.waitFor({ state: 'visible', timeout: 20000 });
        await projectCard.click();
        
        // Verify we are in the project details
        await expect(page.getByRole('heading', { name: /Overview/i })).toBeVisible();
    });

    test('should create a new memory and visualize it', async ({ page }) => {
        // 1. Navigate to Memories Tab explicitly
        await page.getByRole('link', { name: /Memories/i }).click();
        
        // 2. Use global New Memory action
        await page.getByRole('button', { name: /New Memory/i }).click();

        // 3. Fill memory content
        const memoryContent = 'Playwright E2E Test Memory: ' + Date.now();
        await expect(page.locator('textarea')).toBeVisible();
        await page.locator('textarea').click();
        await page.locator('textarea').type(memoryContent);
        await page.getByPlaceholder(/e.g. Q3 Strategy/i).fill('E2E Memory Title');

        // 4. Save
        await expect(page.getByRole('button', { name: /Save Memory/i })).toBeEnabled();
        await page.getByRole('button', { name: /Save Memory/i }).click();

        // 5. Verify redirect to memory list and content visibility
        await expect(page).toHaveURL(/\/memories$/, { timeout: 15000 });
        
        // Wait for the memory to appear
        const memoryItem = page.getByText('E2E Memory Title').first();
        await memoryItem.waitFor({ state: 'visible' });
        
        // Check for status (optional, if UI shows it)
        // If the UI shows "Processing" or "Completed", we can check it.
        // For now, just ensuring it exists is good.
        
        // 6. Navigate to Graph view (Knowledge Graph)
        await page.getByRole('link', { name: /Knowledge Graph/i }).click();

        // 7. Verify graph elements
        await expect(page.getByText(/Nodes:/i)).toBeVisible();
        await expect(page.getByText(/Edges:/i)).toBeVisible();

        // 8. Delete memory
        // Navigate back to detail or use delete button if available in graph view (it's not usually)
        // Go back to list or detail
        await page.goBack(); // Back to detail
        
        // Click delete button in toolbar
        await page.getByTitle('Delete').click();
        
        // Confirm deletion in modal
        // Use class selector to be specific to the modal's primary action button
        await page.locator('button.bg-red-600').click();
        
        // Verify redirect to list
        await expect(page).toHaveURL(/\/memories$/);
        
        // Verify memory is gone
        await expect(page.getByText('E2E Memory Title')).not.toBeVisible();
    });
});
