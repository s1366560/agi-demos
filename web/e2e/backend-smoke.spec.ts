import {
  API_BASE,
  createTestProject,
  expect,
  getAdminAuthToken,
  getFirstTenantId,
  test,
} from './base';

test.describe('backend-dependent smoke', () => {
  test('authenticates the bootstrap admin against the real API', async () => {
    const rejected = await fetch(`${API_BASE}/api/v1/auth/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        username: 'admin@memstack.ai',
        password: 'invalid-password',
      }),
    });
    expect(rejected.status).toBe(401);

    const token = await getAdminAuthToken();
    const me = await fetch(`${API_BASE}/api/v1/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    expect(me.status).toBe(200);
    await expect(me.json()).resolves.toMatchObject({
      email: 'admin@memstack.ai',
    });
  });

  test('persists a project through the authenticated API and renders it in the Web UI', async ({
    page,
  }) => {
    const token = await getAdminAuthToken();
    const tenantId = await getFirstTenantId(token);
    const projectName = `Backend Smoke ${Date.now()}`;
    await createTestProject({
      name: projectName,
      description: 'Backend-dependent Playwright smoke fixture',
      tenantId,
      token,
    });

    await page.goto('/login');
    await page.getByTestId('email-input').fill('admin@memstack.ai');
    await page.getByTestId('password-input').fill('adminpassword');
    await page.getByTestId('login-submit-button').click();
    await page.waitForURL(/\/tenant/);

    await page.goto(`/tenant/${tenantId}/projects`);
    await page.getByPlaceholder(/Search by project name/i).fill(projectName);
    await expect(page.getByRole('link', { name: projectName })).toBeVisible();
  });
});
