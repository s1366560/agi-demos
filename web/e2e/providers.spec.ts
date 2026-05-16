import { API_BASE, getAdminAuthToken, getFirstTenantId, loginAsAdmin, test, expect } from './base';

async function createProvider(token: string, name: string): Promise<{ id: string }> {
  const response = await fetch(`${API_BASE}/api/v1/llm-providers/`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      name,
      provider_type: 'openai',
      api_key: `sk-test-${Date.now()}`,
      llm_model: 'gpt-4o-mini',
      llm_small_model: 'gpt-4o-mini',
      is_active: true,
      is_enabled: true,
      is_default: false,
    }),
  });
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`Unable to create provider: ${String(response.status)} ${text}`);
  }
  const provider = JSON.parse(text);
  return { id: provider.id };
}

async function deleteProvider(token: string, id: string): Promise<void> {
  await fetch(`${API_BASE}/api/v1/llm-providers/${id}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  }).catch(() => {});
}

async function updateProviderName(token: string, id: string, name: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/v1/llm-providers/${id}`, {
    method: 'PUT',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ name }),
  });
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`Unable to update provider: ${String(response.status)} ${text}`);
  }
}

test.describe('LLM Providers Management', () => {
  let token: string;
  let createdProviderIds: string[];

  test.beforeEach(async ({ page }) => {
    token = await getAdminAuthToken();
    createdProviderIds = [];
    const tenantId = await getFirstTenantId(token);
    await loginAsAdmin(page);

    // Navigate to providers page
    await page.goto(`/tenant/${tenantId}/providers`);
    await expect(page.getByRole('heading', { name: 'LLM Providers' })).toBeVisible({
      timeout: 10000,
    });
  });

  test.afterEach(async () => {
    await Promise.all(createdProviderIds.map((id) => deleteProvider(token, id)));
  });

  test('should display empty state or list of providers', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'LLM Providers' })).toBeVisible();

    await expect(page.getByText('System Health')).toBeVisible();
    await expect(page.getByPlaceholder('Search by name or model...')).toBeVisible();
  });

  test('should create a new provider', async ({ page }) => {
    const timestamp = Date.now();
    const providerName = `E2E Test Provider ${timestamp}`;

    await page.getByRole('button', { name: 'Add Provider' }).click();
    await expect(page.getByText('Add New Provider')).toBeVisible();
    await page.getByRole('button', { name: 'Cancel' }).click();

    const provider = await createProvider(token, providerName);
    createdProviderIds.push(provider.id);
    await page.reload();
    await expect(page.getByText(providerName)).toBeVisible({ timeout: 10000 });
  });

  test('should validate required fields', async ({ page }) => {
    await page.getByRole('button', { name: 'Add Provider' }).click();

    await expect(page.getByText('Add New Provider')).toBeVisible();
    await page.getByRole('button', { name: 'Next' }).click();
    await expect(page.getByText('Provider Name')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Next' })).toBeDisabled();
  });

  test('should edit an existing provider', async ({ page }) => {
    const timestamp = Date.now();
    const providerName = `Edit Target ${timestamp}`;
    const newName = `Updated ${providerName}`;

    const provider = await createProvider(token, providerName);
    createdProviderIds.push(provider.id);
    await page.reload();
    await expect(page.getByText(providerName)).toBeVisible({ timeout: 10000 });

    await updateProviderName(token, provider.id, newName);
    await page.reload();
    await expect(page.getByText(newName)).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(providerName, { exact: true })).not.toBeVisible();
  });

  test('should delete a provider', async ({ page }) => {
    const timestamp = Date.now();
    const providerName = `Delete Target ${timestamp}`;

    const provider = await createProvider(token, providerName);
    createdProviderIds.push(provider.id);
    await page.reload();
    await expect(page.getByText(providerName)).toBeVisible({ timeout: 10000 });

    await deleteProvider(token, provider.id);
    createdProviderIds = createdProviderIds.filter((id) => id !== provider.id);
    await page.reload();

    await expect(page.getByText(providerName)).not.toBeVisible();
  });
});
