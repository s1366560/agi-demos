import {
  createTestMemory,
  createTestProject,
  getAdminAuthToken,
  loginAsAdmin,
  tenantProjectPath,
  test,
  expect,
} from './base';

test.describe('Graph Visualization', () => {
  let projectId: string;
  let tenantId: string;

  test.beforeEach(async ({ page }) => {
    const token = await getAdminAuthToken();
    const project = await createTestProject({
      name: `Graph Test Project ${Date.now()}`,
      description: 'E2E graph project',
      token,
    });
    projectId = project.id;
    tenantId = project.tenantId;
    await createTestMemory({
      projectId,
      title: 'Graph Data Memory',
      content: 'Alice works at Google. Bob works at Microsoft. Alice knows Bob.',
      token,
    });
    await loginAsAdmin(page);
    await page.goto(tenantProjectPath(tenantId, projectId));
  });

  test('should render cytoscape graph', async ({ page }) => {
    // Mock graph response
    await page.route('**/api/v1/memory/graph*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          elements: [
            { data: { id: 'a', label: 'Alice', type: 'Entity' } },
            { data: { id: 'b', label: 'Bob', type: 'Entity' } },
            { data: { id: 'ab', source: 'a', target: 'b', label: 'KNOWS' } },
          ],
        }),
      });
    });

    await page.goto(tenantProjectPath(tenantId, projectId, 'graph'));

    await expect(page.getByTestId('memory-graph-page')).toBeVisible();
    await expect(page.getByTestId('graph-node-detail-panel')).toBeAttached();

    // Verify graph is not empty (canvas should exist)
    await expect(page.locator('canvas').first()).toBeAttached({ timeout: 10000 });
  });
});
