import {
  createTestProject,
  expect,
  getAdminAuthToken,
  getFirstTenantId,
  loginAsAdmin,
  test,
} from './base';

async function setupProjectList(page: Parameters<typeof loginAsAdmin>[0]) {
  const token = await getAdminAuthToken();
  const tenantId = await getFirstTenantId(token);
  await loginAsAdmin(page);
  return { tenantId, token };
}

test.describe('Project Management', () => {
  test('should create a new project', async ({ page }) => {
    const { tenantId } = await setupProjectList(page);
    const projectName = `Test Project ${Date.now()}`;

    await page.goto(`/tenant/${tenantId}/projects/new`);
    await page.getByPlaceholder(/e.g. Finance Knowledge Base/i).fill(projectName);
    await page
      .getByPlaceholder(/Briefly describe the purpose of this project/i)
      .fill('E2E Test Project Description');
    await page.getByRole('button', { name: /Create Project/i }).click();

    await page.waitForURL(new RegExp(`/tenant/${tenantId}/projects$`));
    await expect(page.getByRole('heading', { name: /Project Management/i })).toBeVisible();
    await page.getByPlaceholder(/Search by project name/i).fill(projectName);
    await expect(page.getByRole('link', { name: projectName })).toBeVisible();
  });

  test('should list existing projects', async ({ page }) => {
    const { tenantId, token } = await setupProjectList(page);
    const projectName = `Test Project List ${Date.now()}`;
    await createTestProject({
      name: projectName,
      description: 'E2E project list fixture',
      tenantId,
      token,
    });

    await page.goto(`/tenant/${tenantId}/projects`);
    await expect(page.getByRole('heading', { name: /Project Management/i })).toBeVisible();
    await page.getByPlaceholder(/Search by project name/i).fill(projectName);
    await expect(page.getByRole('link', { name: projectName })).toBeVisible();
  });
});
