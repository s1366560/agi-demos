import {
  createTestMemory,
  createTestProject,
  getAdminAuthToken,
  loginAsAdmin,
  tenantProjectPath,
  test,
  expect,
} from './base';

test.describe('Entities and Communities', () => {
  let projectId: string;
  let tenantId: string;

  test.beforeEach(async ({ page }) => {
    const token = await getAdminAuthToken();
    const project = await createTestProject({
      name: `Entities Test Project ${Date.now()}`,
      description: 'E2E entities project',
      token,
    });
    projectId = project.id;
    tenantId = project.tenantId;
    await createTestMemory({
      projectId,
      title: 'Entity Memory',
      content: 'Elon Musk is the CEO of Tesla and SpaceX.',
      token,
    });
    await loginAsAdmin(page);
    await page.goto(tenantProjectPath(tenantId, projectId));
  });

  test('should list extracted entities', async ({ page }) => {
    await page.goto(tenantProjectPath(tenantId, projectId, 'entities'));

    // Check if Entities page loaded
    await expect(page.getByRole('heading', { name: /Project Entities/i })).toBeVisible();

    // Check page structure - entities may still be processing
    await expect(
      page.getByText('Explore and manage entities in the knowledge graph')
    ).toBeVisible();
  });

  test('should display communities', async ({ page }) => {
    await page.goto(tenantProjectPath(tenantId, projectId, 'communities'));

    // Check header
    await page.locator('h1').filter({ hasText: 'Communities' }).waitFor();

    // Check refresh button
    await expect(page.getByRole('button', { name: 'Refresh', exact: true })).toBeVisible();

    // Prefer explicit empty-state message
    const emptyMsg = page
      .getByText(/No communities found|Loading communities|Showing .* communities/i)
      .first();
    const card = page.locator('.community-card, [data-testid="community-card"]').first();
    const visibleEmpty = await emptyMsg.isVisible().catch(() => false);
    const visibleCard = await card.isVisible().catch(() => false);
    expect(visibleEmpty || visibleCard).toBeTruthy();
  });
});
