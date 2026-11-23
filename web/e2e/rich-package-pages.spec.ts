import { expect, test } from '@playwright/test';

test('opaque guest receives scoped commands and can cancel an active host request', async ({
  page,
}) => {
  await page.goto('/e2e/fixtures/rich-package-host.html');
  const guest = page.frameLocator('iframe[data-page-ready="true"]').frameLocator('iframe');
  await expect(guest.locator('output')).toHaveText(
    JSON.stringify({
      result: { payloadPresent: false },
      denied: 'page_capability_unavailable',
      device: 'page_capability_unavailable',
      id: 'p',
    })
  );
  await guest.getByRole('button', { name: 'Cancel' }).click();
  await expect(page.locator('#host-log')).toHaveText('cancelled');
  await expect(guest.getByText('AbortError')).toBeVisible();
});

test('corrupt bundle bytes leave the guest unmounted', async ({ page }) => {
  await page.goto('/e2e/fixtures/rich-package-host.html?bad');
  await expect(page.getByRole('alert')).toHaveText('page_asset_digest_mismatch');
  await expect(page.locator('iframe')).toHaveCount(0);
});

test('package host restores a verified session and scopes project links through account changes', async ({
  page,
}) => {
  let available = true;
  let account = 'first';
  let offline = false;
  const accesses: string[] = [];
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    const token = route.request().headers().authorization;
    if (url.pathname.endsWith('/auth/token')) {
      return route.fulfill({ json: { access_token: 'test-' + account } });
    }
    if (url.pathname.endsWith('/auth/me')) {
      if (offline) return route.fulfill({ status: 503, json: { detail: 'offline' } });
      if (!available || token !== 'Bearer test-' + account)
        return route.fulfill({ status: 401, json: {} });
      return route.fulfill({
        json: { user_id: account, email: account + '@example.test', preferred_language: 'en-US' },
      });
    }
    if (url.pathname.endsWith('/project-packages/projects/')) {
      return route.fulfill({
        json: ['one', 'two'].map((project) => ({
          tenant_id: account,
          tenant_name: account,
          project_id: project,
          project_name: project,
          can_manage: false,
          can_execute: true,
        })),
      });
    }
    if (url.searchParams.has('project_id')) accesses.push(url.searchParams.get('project_id')!);
    return route.fulfill({ json: { items: [] } });
  });
  await page.goto('/tenant/first/project/two/workspaces');
  const login = async () => {
    await page.locator('input[name=email]').fill(account + '@example.test');
    await page.locator('input[name=password]').fill('test-only');
    await page.locator('button[type=submit]').click();
  };
  await login();
  await expect(page.getByRole('combobox').first()).toHaveValue('two');
  expect(accesses).not.toContain('one');
  offline = true;
  await page.reload();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByRole('combobox')).toHaveCount(0);
  offline = false;
  await page.getByRole('button', { name: /retry/i }).click();
  await expect(page.getByRole('combobox').first()).toHaveValue('two');
  await page.getByRole('combobox').first().selectOption('one');
  await expect(page).toHaveURL(/project=one/);
  available = false;
  await page.reload();
  await expect(page.locator('input[name=email]')).toBeVisible();
  account = 'second';
  available = true;
  await login();
  await expect(page.getByRole('combobox').first()).toHaveValue('');
  await expect(page.locator('iframe')).toHaveCount(0);
});

test('published React Billing page renders the same invoice table as the desktop client', async ({
  page,
}) => {
  await page.goto('/e2e/fixtures/rich-package-host.html?billing');
  const guest = page.frameLocator('iframe[data-page-ready="true"]').frameLocator('iframe');
  await guest.getByRole('button', { name: 'pro', exact: true }).click();
  await expect(guest.locator('output')).toContainText('65,536 bytes');
  await guest.getByRole('button', { name: 'Project invoices' }).click();
  await expect(guest.getByRole('cell')).toHaveText(['INV-123', 'USD 1250', 'pending']);
});

test('sandbox page binds terminal requests to the run revision and disables a degraded authority', async ({
  page,
}) => {
  await page.goto('/e2e/fixtures/rich-package-host.html?sandbox-degraded');
  const guest = page.frameLocator('iframe[data-page-ready="true"]').frameLocator('iframe');
  const authorize = guest.getByRole('button', { name: 'Request terminal authorization' });
  await expect(authorize).toBeDisabled();
  await expect(guest.getByText('terminal_authority_unavailable')).toBeVisible();
  await page.goto('/e2e/fixtures/rich-package-host.html?sandbox');
  await expect(authorize).toBeEnabled();
  await guest.getByLabel('Run ID').fill('run-2');
  await guest.getByLabel('Current run revision').fill('8');
  await authorize.click();
  await expect(page.locator('#host-log')).toHaveText(
    JSON.stringify({ run_id: 'run-2', expected_run_revision: 8 })
  );
  await expect(guest.getByText('Authorized through 2030-10-01T00:00:00Z')).toBeVisible();
});

test('failed resource preparation preserves the previously mounted rich page', async ({ page }) => {
  await page.goto('/e2e/fixtures/rich-package-host.html?upgrade');
  const previous = page.frameLocator('iframe[data-page-ready="true"]').frameLocator('iframe');
  await expect(previous.getByRole('button', { name: 'Cancel' })).toBeVisible();
  await page.getByRole('button', { name: 'Install next version' }).click();
  await expect(page.getByRole('alert')).toHaveText('page_asset_digest_mismatch');
  await page.getByText('Page diagnostics').click();
  const diagnostics = page.locator('details');
  await expect(
    diagnostics.locator('dt', { hasText: 'Selected digest' }).locator('+ dd')
  ).toHaveText('sha256:' + 'b'.repeat(64));
  await expect(diagnostics.locator('dt', { hasText: 'Loaded digest' }).locator('+ dd')).toHaveText(
    'sha256:' + 'a'.repeat(64)
  );
  await expect(diagnostics.locator('dt', { hasText: 'Load error' }).locator('+ dd')).toHaveText(
    'page_asset_digest_mismatch'
  );
  await expect(previous.getByRole('button', { name: 'Cancel' })).toBeVisible();
});

test('a successful release switch drains admitted calls before retiring the old frame', async ({
  page,
}) => {
  await page.goto('/e2e/fixtures/rich-package-host.html?drain');
  const old = page.locator('iframe[data-release-digest^="sha256:aaaa"]');
  const next = page.locator('iframe[data-release-digest^="sha256:bbbb"]');
  const finish = page.getByRole('button', { name: 'Finish admitted request' });
  await expect(finish).toBeVisible();
  await page.getByRole('button', { name: 'Install next version' }).click();
  await expect(next).toBeVisible();
  await expect(old).toBeHidden();
  await expect(old).toHaveCount(1);
  await finish.click();
  await expect(old).toHaveCount(0);
  await expect(page.locator('#host-log')).not.toHaveText('cancelled');
});

test('a page navigates to a signed sibling only within the authenticated project', async ({
  page,
}) => {
  await page.goto('/e2e/fixtures/rich-package-host.html');
  const guest = page.frameLocator('iframe[data-page-ready="true"]').frameLocator('iframe');
  const body = guest.locator('body');
  await body.evaluate(() => window.memstack.navigate('/project/p/details/record'));
  await expect(page.locator('#host-log')).toHaveText('/project/p/details/record');
  expect(
    await body.evaluate(() =>
      window.memstack.navigate('/project/other/details/record').catch((e) => e.message)
    )
  ).toBe('page_navigation_denied');
  expect(
    await body.evaluate(() => window.memstack.navigate('/settings').catch((e) => e.message))
  ).toBe('page_navigation_denied');
});
