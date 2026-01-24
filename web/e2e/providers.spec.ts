import { test, expect } from './base';

test.describe('LLM Providers Management', () => {
    test.beforeEach(async ({ page }) => {
        // Set Chinese locale
        await page.goto('http://localhost:3000');
        await page.evaluate(() => {
            localStorage.setItem('i18nextLng', 'en-US');
        });

        // Login as admin
        await page.goto('/login');
        await page.getByLabel(/邮箱/i).fill('admin@memstack.ai');
        await page.getByLabel(/密码/i).fill('adminpassword');
        await page.getByRole('button', { name: /登录/i }).click();

        // Wait for login to complete
        await page.waitForURL((url) => !url.pathname.includes('/login'));

        // Navigate to providers page
        await page.goto('/tenant/providers');
    });

    test('should display empty state or list of providers', async ({ page }) => {
        await expect(page.getByRole('heading', { name: 'LLM Providers' })).toBeVisible();

        // Either table or empty state should be visible
        const table = page.locator('table');
        const emptyState = page.getByText('No providers configured');

        await expect(table.or(emptyState)).toBeVisible();
    });

    test('should create a new provider', async ({ page }) => {
        const timestamp = Date.now();
        const providerName = `E2E Test Provider ${timestamp}`;

        // Click Add Provider
        await page.getByRole('button', { name: 'Add Provider' }).click();

        // Wait for modal
        await expect(page.getByText('Add LLM Provider')).toBeVisible();

        // Fill Basic Info
        await page.getByLabel('Provider Name *').fill(providerName);
        await page.getByLabel('Provider Type *').selectOption('openai');
        await page.getByLabel('API Key *').fill('sk-test-key-123456');

        // Switch to Models tab to verify defaults or change them
        await page.getByRole('button', { name: 'Models' }).click();
        await expect(page.getByLabel('Primary LLM Model *')).toHaveValue(/gpt-4/);

        // Submit
        await page.getByRole('button', { name: 'Create Provider' }).click();

        // Verify modal closes
        await expect(page.getByText('Add LLM Provider')).not.toBeVisible();

        // Wait for list to reload (loading state might appear)
        // We expect the new provider to appear eventually
        await expect(page.getByText(providerName)).toBeVisible({ timeout: 10000 });
    });

    test('should validate required fields', async ({ page }) => {
        await page.getByRole('button', { name: 'Add Provider' }).click();

        // Click Create without filling anything
        // Note: The browser validation might prevent submission, or the button might not do anything.
        // Since we are using standard HTML5 validation (required attribute), 
        // we can check if the input is invalid or try to fill just one field.

        // Let's try to fill only name and see if API key is required
        await page.getByLabel('Provider Name *').fill('Invalid Provider');

        // The browser's built-in validation is hard to test directly with Playwright without some tricks.
        // Instead, we can check that the modal is still open after clicking submit.
        await page.getByRole('button', { name: 'Create Provider' }).click();
        await expect(page.getByText('Add LLM Provider')).toBeVisible();
    });

    test('should edit an existing provider', async ({ page }) => {
        // Ensure we have at least one provider (reuse creation logic or rely on previous test if serial)
        // For robustness, let's create one first
        const timestamp = Date.now();
        const providerName = `Edit Target ${timestamp}`;

        await page.getByRole('button', { name: 'Add Provider' }).click();
        await page.getByLabel('Provider Name *').fill(providerName);
        await page.getByLabel('Provider Type *').selectOption('openai');
        await page.getByLabel('API Key *').fill('sk-test-key');
        await page.getByRole('button', { name: 'Create Provider' }).click();

        // Find the row with our provider
        const row = page.getByRole('row', { name: providerName });
        await expect(row).toBeVisible();

        // Click Edit button (pencil icon)
        await row.getByRole('button', { name: 'Edit' }).click();

        // Verify Edit Modal
        await expect(page.getByText('Edit Provider')).toBeVisible();

        // Change name
        const newName = `Updated ${providerName}`;
        await page.getByLabel('Provider Name *').fill(newName);

        // Save
        await page.getByRole('button', { name: 'Update Provider' }).click();

        // Verify update
        await expect(page.getByText(newName)).toBeVisible();
        await expect(page.getByText(providerName, { exact: true })).not.toBeVisible();
    });

    test('should delete a provider', async ({ page }) => {
        // Create a provider to delete
        const timestamp = Date.now();
        const providerName = `Delete Target ${timestamp}`;

        await page.getByRole('button', { name: 'Add Provider' }).click();
        await page.getByLabel('Provider Name *').fill(providerName);
        await page.getByLabel('Provider Type *').selectOption('openai');
        await page.getByLabel('API Key *').fill('sk-test-key');
        await page.getByRole('button', { name: 'Create Provider' }).click();

        // Find row
        const row = page.getByRole('row', { name: providerName });
        await expect(row).toBeVisible();

        // Setup dialog handler for confirmation
        page.on('dialog', dialog => dialog.accept());

        // Click Delete button (trash icon)
        await row.getByRole('button', { name: 'Delete' }).click();

        // Verify deletion
        await expect(page.getByText(providerName)).not.toBeVisible();
    });
});
