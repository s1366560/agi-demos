import {
  createTestProject,
  getAdminAuthToken,
  loginAsAdmin,
  tenantProjectPath,
  test,
  expect,
} from './base';

test.describe('Memory Operations', () => {
  let projectId: string;
  let tenantId: string;

  test.beforeEach(async ({ page }) => {
    const token = await getAdminAuthToken();
    const project = await createTestProject({
      name: `Test Project ${Date.now()}`,
      description: 'E2E memory project',
      token,
    });
    projectId = project.id;
    tenantId = project.tenantId;
    await loginAsAdmin(page);
    await page.goto(tenantProjectPath(tenantId, projectId));
  });

  test('should create a new memory and visualize it', async ({ page }) => {
    // 1. Navigate to Memories Tab explicitly
    await page.getByRole('link', { name: /Memories/i }).click();

    // 2. Use global New Memory action
    await page.getByRole('button', { name: /Add Memory|New Memory/i }).click();

    // 3. Fill memory content
    const memoryContent = 'Playwright E2E Test Memory: ' + Date.now();
    await expect(page.locator('textarea')).toBeVisible();
    await page.locator('textarea').click();
    await page.locator('textarea').type(memoryContent);
    await page.getByPlaceholder(/e.g. Q3 Strategy/i).fill('E2E Memory Title');

    // 4. Save
    await expect(page.getByRole('button', { name: /Save Memory/i })).toBeEnabled();
    const createMemoryResponse = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        response.url().includes('/api/v1/memories') &&
        response.status() === 201
    );
    await page.getByRole('button', { name: /Save Memory/i }).click();

    // 5. Verify the memory was accepted, then return to the list. Background graph
    // processing can outlive the page and is not required for the list entry.
    await createMemoryResponse;
    await page.goto(tenantProjectPath(tenantId, projectId, 'memories'));

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
    await page.goto(tenantProjectPath(tenantId, projectId, 'memories'));

    // Click delete button in the memory list row
    await page.getByText('E2E Memory Title').first().hover();
    await page.getByTitle('Delete memory').click();

    // Confirm deletion in modal
    await page.getByRole('button', { name: 'Delete', exact: true }).click();

    await expect(page.getByRole('heading', { name: 'Delete Memory' })).not.toBeVisible({
      timeout: 15000,
    });

    // Verify redirect to list
    await expect(page).toHaveURL(/\/memories$/);

    // Verify memory is gone
    await expect(page.getByRole('link', { name: 'E2E Memory Title' })).not.toBeVisible({
      timeout: 15000,
    });
  });
});
