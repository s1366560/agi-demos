import { expect, getAdminAuthToken, getFirstTenantId, loginAsAdmin, test } from './base';

test.describe('Tenant Overview', () => {
  test('should render memory usage history from tenant stats', async ({ page }) => {
    const token = await getAdminAuthToken();
    const tenantId = await getFirstTenantId(token);
    await loginAsAdmin(page);

    await page.goto(`/tenant/${tenantId}/overview`);

    await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible({
      timeout: 15000,
    });
    await expect(
      page.getByRole('img', { name: 'Tenant memory usage history chart' })
    ).toBeVisible();
    await expect(page.getByText('Latest usage')).toBeVisible();
  });
});
