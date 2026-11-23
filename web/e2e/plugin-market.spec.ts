import { expect, test, type Page } from '@playwright/test';

const activeDigest = 'sha256:' + '1'.repeat(64);
const newerDigest = 'sha256:' + '2'.repeat(64);
const installedPage = { id: 'home', title: 'Supply orders', targets: ['web'], routes: ['/orders'] };

async function fixture(page: Page, { admin = true, offline = false } = {}) {
  const writes: { path: string; body: Record<string, unknown> }[] = [];
  let active: string | null = '1.0.0';
  let previous: string | null = null;
  let revision = 4;
  let failure: string | null = null;
  let failApply = false;
  const installation = () =>
    active
      ? {
          plugin_id: 'vendor-supply',
          installed_version: active,
          running_version: active,
          desired_revision: revision,
          actual_digest: active === '1.0.0' ? activeDigest : newerDigest,
          targets: ['python'],
          pages: [installedPage],
          commands: ['orders.read'],
          failure,
        }
      : null;
  const item = () => ({
    plugin_id: 'vendor-supply',
    package_name: '@vendor/supply',
    display_name: { en: 'Supply orders' },
    description: { en: 'Work with purchase orders.' },
    icon: 'not-a-built-in',
    targets: ['web', 'python'],
    latest_version: offline ? null : '2.0.0',
    update_available: !offline && active === '1.0.0',
    installation: installation(),
  });
  const source = {
    source: 'http://npm-registry:4873',
    source_error: offline ? 'Registry offline' : null,
    can_manage: admin,
  };
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path.endsWith('/auth/token')) return route.fulfill({ json: { access_token: 'session' } });
    if (path.endsWith('/auth/me'))
      return route.fulfill({
        json: { user_id: 'buyer', email: 'buyer@example.test', preferred_language: 'en-US' },
      });
    if (path.endsWith('/project-packages/projects/'))
      return route.fulfill({
        json: [
          {
            project_id: 'p',
            tenant_id: 't',
            project_name: 'Purchasing',
            tenant_name: 'Sample',
            can_manage: admin,
            can_execute: true,
          },
        ],
      });
    if (path.endsWith('/npm/catalog')) {
      const matches =
        (url.searchParams.get('view') !== 'updates' || item().update_available) &&
        'Supply orders'.toLowerCase().includes((url.searchParams.get('q') ?? '').toLowerCase());
      return route.fulfill({
        json: { ...source, total: matches ? 1 : 0, items: matches ? [item()] : [] },
      });
    }
    if (path.endsWith('/npm/detail')) {
      const version = url.searchParams.get('version') ?? (offline ? '1.0.0' : '2.0.0');
      return route.fulfill({
        json: {
          ...source,
          ...item(),
          versions: offline ? ['1.0.0'] : ['2.0.0', '1.0.0'],
          desired_revision: revision,
          previous_version: previous,
          current_permissions: ['orders.read'],
          release_error: null,
          release: {
            version,
            digest: version === '1.0.0' ? activeDigest : newerDigest,
            targets: ['python'],
            commands: ['orders.read'],
            permissions: version === '1.0.0' ? ['orders.read'] : ['orders.read', 'orders.write'],
            pages: [installedPage],
          },
        },
      });
    }
    if (route.request().method() === 'POST') {
      writes.push({ path, body: route.request().postDataJSON() as Record<string, unknown> });
      if (path.endsWith('/apply')) {
        if (failApply) {
          failure = 'Worker failed to start';
          return route.fulfill({ status: 409, json: { detail: failure } });
        }
        previous = active;
        active = '2.0.0';
        failure = null;
        revision++;
      } else if (path.endsWith('/rollback')) {
        active = previous;
        previous = null;
        revision++;
      } else if (path.endsWith('/uninstall')) {
        active = null;
        revision++;
      }
      return route.fulfill({ json: installation() ?? { actual_digest: null } });
    }
    return route.fulfill({ json: { items: [] } });
  });
  await page.goto('/plugins?tenant=t&project=p');
  await page.getByLabel('Email', { exact: true }).fill('buyer@example.test');
  await page.getByLabel('Password', { exact: true }).fill('test-only');
  await page.getByRole('button', { name: 'Sign In', exact: true }).click();
  return {
    writes,
    fail: () => {
      failApply = true;
    },
  };
}

test('market confirms the exact update, preserves list state and offers rollback and uninstall', async ({
  page,
}) => {
  const { writes } = await fixture(page);
  const market = page.getByTestId('plugin-market');
  await market.getByRole('button', { name: 'Updates', exact: true }).click();
  await market.getByRole('searchbox').fill('Supply');
  await market.getByRole('button', { name: 'Supply orders', exact: true }).click();
  await expect(page).toHaveURL(/marketPlugin=vendor-supply/);
  await market.getByRole('button', { name: 'Update to 2.0.0' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('New permissions');
  await expect(dialog).toContainText('orders.write');
  expect(writes).toHaveLength(0);
  await dialog.getByRole('button', { name: 'Approve update' }).click();
  await expect(
    market.locator('dt').filter({ hasText: 'Running version' }).locator('+ dd')
  ).toHaveText('2.0.0');
  expect(writes[0]?.body).toEqual({
    tenant_id: 't',
    project_id: 'p',
    package_name: '@vendor/supply',
    version: '2.0.0',
    expected_digest: newerDigest,
    expected_revision: 4,
    approved_permissions: ['orders.read', 'orders.write'],
  });
  await market.getByText('More actions', { exact: true }).click();
  await market.getByRole('button', { name: 'Roll back to 1.0.0' }).click();
  await dialog.getByRole('button', { name: 'Confirm', exact: true }).click();
  await expect(
    market.locator('dt').filter({ hasText: 'Running version' }).locator('+ dd')
  ).toHaveText('1.0.0');
  expect(writes[1]?.body.expected_revision).toBe(5);
  await page.goBack();
  await expect(market.getByRole('searchbox')).toHaveValue('Supply');
  await expect(market.getByRole('button', { name: 'Updates', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true'
  );
  await market.getByRole('button', { name: 'Supply orders', exact: true }).click();
  await market.getByText('More actions', { exact: true }).click();
  await market.getByRole('button', { name: 'Uninstall', exact: true }).click();
  await expect(dialog).toContainText('Project data is retained');
  await expect(dialog).toContainText('orders.read');
  await dialog.getByRole('button', { name: 'Uninstall', exact: true }).click();
  await expect(market.getByRole('button', { name: 'Install', exact: true })).toBeVisible();
});

test('failed update keeps the running feature, reports the error, and permits retry', async ({
  page,
}) => {
  const { fail } = await fixture(page);
  fail();
  const market = page.getByTestId('plugin-market');
  await market.getByRole('button', { name: 'Supply orders', exact: true }).click();
  await market.getByRole('button', { name: 'Update to 2.0.0' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Approve update' }).click();
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('Worker failed');
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click();
  await expect(market.getByRole('button', { name: 'Open feature' })).toBeVisible();
  await expect(
    market.locator('dt').filter({ hasText: 'Running version' }).locator('+ dd')
  ).toHaveText('1.0.0');
  await expect(market.getByRole('alert')).toContainText('Worker failed');
});

test('offline read-only project retains business pages and fits a narrow window', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { writes } = await fixture(page, { admin: false, offline: true });
  const market = page.getByTestId('plugin-market');
  await expect(market.getByText('Registry offline')).toBeVisible();
  await market.getByRole('button', { name: 'Installed', exact: true }).click();
  const card = market.getByRole('button', { name: 'Supply orders', exact: true });
  await card.focus();
  await page.keyboard.press('Enter');
  await expect(market.getByRole('button', { name: 'Open feature' })).toBeVisible();
  await expect(market.getByText('A project administrator can manage this plugin.')).toBeVisible();
  await expect(market.getByText('More actions', { exact: true })).toHaveCount(0);
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)
  ).toBeTruthy();
  expect(writes).toHaveLength(0);
});
