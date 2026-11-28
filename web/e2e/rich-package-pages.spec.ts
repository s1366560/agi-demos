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

test('signed terminal uses the admitted run revision and cannot connect with a degraded authority', async ({ page }) => {
  const request = JSON.stringify({ run_id: 'run-2', expected_run_revision: 8, open_channel: true });
  const guest = page.frameLocator('iframe[data-page-ready="true"]').frameLocator('iframe');
  await page.goto('/e2e/fixtures/rich-package-host.html?sandbox-degraded');
  await expect(page.locator('#host-log')).toHaveText(request);
  await expect(guest.getByRole('button', { name: 'Reconnect' })).toBeVisible();
  await expect(guest.getByText(/qa-run-2/)).toHaveCount(0);
  await page.goto('/e2e/fixtures/rich-package-host.html?sandbox');
  await expect(page.locator('#host-log')).toHaveText(request);
  await expect(guest.getByText(/qa-run-2/)).toBeVisible();
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

test('a signed page link opens only the declared installed destination in its own scope', async ({ page }) => {
  await page.goto('/e2e/fixtures/rich-package-host.html?page-links');
  const guest = page.frameLocator('iframe[data-page-ready="true"]').frameLocator('iframe');
  const body = guest.locator('body');
  await body.evaluate(() => window.memstack.openPage('boards', 'overview'));
  await expect(page.locator('#host-log')).toHaveText('/project/p/board');
  await body.evaluate(() => window.memstack.openPage('boards','overview','/project/p/board/42?tab=files&unknown=a#x'));
  await expect(page.locator('#host-log')).toHaveText('/project/p/board/42?tab=files#x');
  for (const destination of ['/project/other/board/42', '/settings', '/project/p/board?tenant=x']) {
    expect(await body.evaluate((_element, path) => window.memstack.openPage('boards','overview',path).catch(e=>e.message),destination)).toBe('page_navigation_denied');
  }
  expect(await body.evaluate(() =>
    window.memstack.openPage('uninstalled', 'overview').catch((e) => e.message)
  )).toBe('page_destination_unavailable');
  expect(await body.evaluate(() =>
    window.memstack.openPage('boards', 'settings').catch((e) => e.message)
  )).toBe('page_navigation_denied');
});

test('signed Agent page keeps local replay read-only on Web and routes cloud turns to the cloud', async ({
  page,
}) => {
  await page.goto('/e2e/fixtures/rich-package-host.html?chat-web');
  const guest = page.frameLocator('iframe[data-page-ready="true"]').frameLocator('iframe');
  await expect(guest.getByText('Saved local')).toBeVisible();
  await expect(guest.locator('[data-surface=web]')).toHaveAttribute('data-readonly', 'true');
  await expect(guest.getByTestId('chat-input')).toBeDisabled();
  await expect(guest.getByLabel('New conversation location')).toBeHidden();
  await page.goto('/e2e/fixtures/rich-package-host.html?chat-web-cloud');
  await expect(guest.getByText('Saved cloud')).toBeVisible();
  await expect(guest.getByRole('table').getByText('signed')).toBeVisible();
  await expect(guest.locator('pre').getByText('const value = 1;', {exact:false})).toBeVisible();
  await expect(guest.getByText('ts', {exact:true})).toBeVisible();
  await guest.locator('textarea').fill('hello cloud');
  await guest.getByTestId('send-button').click();
  await expect(page.locator('#host-log')).toContainText('"command_id":"chat-turn"');
  await expect(page.locator('#host-log')).not.toContainText('local_chat');
});

test('desktop Agent page binds execute and stop to the same local turn and replays synced history', async ({
  page,
}) => {
  await page.goto('/e2e/fixtures/rich-package-host.html?chat-desktop');
  const guest = page.frameLocator('iframe[data-page-ready="true"]').frameLocator('iframe');
  const target = guest.getByRole('combobox', { name: 'Execution location' });
  await expect(target).toHaveValue('local');
  await expect(guest.getByText('QA Workspace')).toBeVisible();
  await target.selectOption('cloud');
  await expect(guest.getByText('Default environment')).toBeVisible();
  await target.selectOption('local');
  await guest.locator('textarea').fill('hello device');
  await guest.getByTestId('send-button').click();
  await guest.getByRole('button', { name: 'Stop' }).click();
  await expect(guest.getByText('Device turn cancelled')).toBeVisible();
  const [create, execute, stop] = JSON.parse(await page.locator('#host-log').innerText());
  expect(create.input.execution_target).toBe('local');
  expect(execute.tool).toBe('local_chat');
  expect(stop.tool).toBe('local_chat');
  expect(execute.payload).toEqual({
    action: 'execute',
    conversation_id: 'new',
    message: 'hello device',
    idempotency_key: expect.any(String),
  });
  expect(stop.payload).toEqual({
    action: 'stop',
    conversation_id: 'new',
    idempotency_key: execute.payload.idempotency_key,
  });
  expect(stop.digest).toBe(execute.digest);
});

test('desktop Agent page preserves the draft and retry key when device settings are incomplete', async ({
  page,
}) => {
  await page.goto('/e2e/fixtures/rich-package-host.html?chat-denied');
  const guest = page.frameLocator('iframe[data-page-ready="true"]').frameLocator('iframe');
  await expect(guest.getByText('Saved local')).toBeVisible();
  await guest.locator('textarea').fill('private draft');
  await guest.getByTestId('send-button').click();
  await expect(guest.getByRole('alert')).toContainText('Choose a workspace in device settings');
  await expect(guest.locator('textarea')).toHaveValue('private draft');
  await guest.getByTestId('send-button').click();
  await expect
    .poll(async () => JSON.parse(await page.locator('#host-log').innerText()).length)
    .toBe(2);
  const [first, retry] = JSON.parse(await page.locator('#host-log').innerText());
  expect(first.payload).toEqual(retry.payload);
});

test('desktop Agent page surfaces a revoked release grant and retains the draft', async ({
  page,
}) => {
  await page.goto('/e2e/fixtures/rich-package-host.html?chat-revoked');
  const guest = page.frameLocator('iframe[data-page-ready="true"]').frameLocator('iframe');
  await expect(guest.getByText('Saved local')).toBeVisible();
  await guest.locator('textarea').fill('retry when approved');
  await guest.getByTestId('send-button').click();
  await expect(guest.getByRole('alert')).toHaveText(
    'Approve this Agent release in device settings. device_plugin_grant_revoked'
  );
  await expect(guest.locator('textarea')).toHaveValue('retry when approved');
  await expect(page.locator('#host-log')).not.toContainText('chat-turn');
});

test('the project opens its signed home, keeps deep links, and exposes management separately', async ({
  page,
}) => {
  const webTarget = ['web'];
  const application = (id: string, route: string, home = false) => ({
    id,
    title: 'Screen ' + id,
    routes: [route],
    targets: webTarget,
    home,
  });
  const detail = application('detail', '/reports/:id', true);
  const first = application('overview', '/overview');
  const home = application('tasks', '/tasks', true);
  let pages = [detail, first, home];
  const release = 'sha256:' + 'a'.repeat(64);
  const source = Buffer.from(
    "document.getElementById('root').textContent = 'Signed application running'"
  );
  const { createHash } = await import('node:crypto');
  await page.route('**/api/v1/**', async (request) => {
    const url = new URL(request.request().url());
    if (url.pathname.endsWith('/auth/token'))
      return request.fulfill({ json: { access_token: 'test-token' } });
    if (url.pathname.endsWith('/auth/me'))
      return request.fulfill({
        json: { user_id: 'tester', email: 'test@example.test', preferred_language: 'en-US' },
      });
    if (url.pathname.endsWith('/project-packages/projects/'))
      return request.fulfill({
        json: [
          {
            tenant_id: 't',
            project_id: 'p',
            tenant_name: 'Tenant',
            project_name: 'Project',
            can_manage: true,
            can_execute: true,
          },
        ],
      });
    if (url.pathname.endsWith('/npm/catalog')) {
      return request.fulfill({ json: {
        source: 'local npm', source_error: null, can_manage: true, total: 0, items: [],
      } });
    }
    if (url.pathname.endsWith('/ui')) {
      const descriptor = pages.find((item) => item.id === url.searchParams.get('page_id'));
      return request.fulfill({
        json: {
          ...descriptor,
          schema: 'memstack.rich-page/1',
          release_digest: release,
          target: 'web',
          commands: [],
          device_tools: [],
          entry: {
            path: 'ui/run.js',
            digest: 'sha256:' + createHash('sha256').update(source).digest('hex'),
            bytes_base64: source.toString('base64'),
          },
        },
      });
    }
    return request.fulfill({
      json: {
        items: pages.length
          ? [{ plugin_id: 'example.vendor', status: 'enabled', actual_digest: release, pages }]
          : [],
      },
    });
  });
  const guest = page.frameLocator('iframe[data-page-ready=true]').frameLocator('iframe');
  await page.goto('/');
  await page.getByLabel('Email', { exact: true }).fill('test@example.test');
  await page.getByLabel('Password', { exact: true }).fill('test-only');
  await page.getByRole('button', { name: 'Sign In', exact: true }).click();
  await expect(page).toHaveURL(/\/tasks\?/);
  await expect(guest.getByText('Signed application running')).toBeVisible();
  await expect(page.getByTestId('plugin-market')).toHaveCount(0);
  const menu = page.getByRole('combobox', { name: 'Applications' });
  await menu.selectOption('/overview');
  await expect(page).toHaveURL(/\/overview\?/);
  await page.getByRole('button', { name: 'Manage plugins' }).click();
  await expect(page.getByTestId('plugin-market')).toBeVisible();
  await expect(page.locator('iframe[data-page-ready]')).toHaveCount(0);
  await page.goBack();
  await expect(menu).toHaveValue('/overview');
  await page.goto('/reports/123');
  await expect(guest.getByText('Signed application running')).toBeVisible();
  await expect(page).toHaveURL(/\/reports\/123$/);
  pages = [detail, first];
  await page.goto('/');
  await expect(page).toHaveURL(/\/overview\?/);
  pages = [];
  await page.goto('/');
  await expect(page.getByText('This project has no available application pages.')).toBeVisible();
  await expect(page.getByTestId('plugin-market')).toHaveCount(0);
  await page.getByRole('button', { name: 'Manage plugins' }).click();
  await expect(page.getByTestId('plugin-market')).toBeVisible();
});

test('npm source previews the signed release and installs its reviewed permissions only on approval', async ({
  page,
}) => {
  const scope = { tenant_id: 't', project_id: 'p' };
  const item = {
    plugin_id: 'memstack-sample', package_name: '@memstack/sample', display_name: { en: 'Sample' },
    description: { en: 'Sample package' }, icon: null, latest_version: '2.1.1',
    targets: ['web'], installation: null, update_available: false,
  };
  const versions = ['2.1.1', '2.1.0'];
  const releases = versions.map((version, index) => ({
    version, digest: 'sha256:' + (index ? 'a' : 'b').repeat(64),
    permissions: index ? ['tools.execute'] : ['tools.read'], commands: [], pages: [], targets: ['web'],
  }));
  const candidate = releases[1]!;
  let installs = 0;
  await page.route('**/api/v1/**', async (request) => {
    const path = new URL(request.request().url()).pathname;
    if (path.endsWith('/auth/token'))
      return request.fulfill({ json: { access_token: 'local-fixture' } });
    if (path.endsWith('/auth/me'))
      return request.fulfill({
        json: { user_id: 'admin', email: 'admin@example.test', preferred_language: 'en-US' },
      });
    if (path.endsWith('/project-packages/projects/'))
      return request.fulfill({
        json: [
          {
            ...scope,
            tenant_name: 'Tenant',
            project_name: 'Project',
            can_manage: true,
            can_execute: true,
          },
        ],
      });
    if (path.endsWith('/npm/catalog')) {
      return request.fulfill({ json: { source: 'local npm', source_error: null, items: [item], total: 1, can_manage: true } });
    }
    if (path.endsWith('/npm/detail')) {
      const query = new URL(request.request().url()).searchParams;
      expect(query.get('plugin_id')).toBe(item.plugin_id);
      const version = query.get('version') ?? item.latest_version;
      return request.fulfill({ json: {
        ...item, versions, release: releases.find((r) => r.version === version),
        source: 'local npm', source_error: null, release_error: null, can_manage: true, can_execute: true,
        desired_revision: 4, previous_version: null, current_permissions: [],
      } });
    }
    if (path.endsWith('/npm/apply')) {
      expect(request.request().postDataJSON()).toEqual({
        ...scope, package_name: item.package_name, version: candidate.version,
        expected_revision: 4, expected_digest: candidate.digest, approved_permissions: candidate.permissions,
      });
      installs++;
      return request.fulfill({ json: { plugin_id: item.plugin_id, actual_digest: candidate.digest,
        desired_revision: 5, installed_version: candidate.version, running_version: candidate.version } });
    }
    return request.fulfill({ json: { items: [] } });
  });
  await page.goto('/plugins');
  await page.getByLabel('Email', { exact: true }).fill('admin@example.test');
  await page.getByLabel('Password', { exact: true }).fill('test-only');
  await page.getByRole('button', { name: 'Sign In', exact: true }).click();
  await page.locator('#pm-card-memstack-sample').click();
  const version = page.getByRole('combobox', { name: 'Select version' });
  await expect(version).toHaveValue('2.1.1');
  await version.selectOption(candidate.version);
  await expect(page.locator('.pm-spec .pm-digest')).toHaveText(candidate.digest);
  await page.getByRole('button', { name: 'Install', exact: true }).click();
  const review = page.getByRole('dialog');
  await expect(review).toContainText(candidate.version);
  await expect(review).toContainText(candidate.digest);
  await expect(review).toContainText('tools.execute');
  await expect(review).not.toContainText('tools.read');
  expect(installs).toBe(0);
  await review.getByRole('button', { name: 'Approve and enable' }).click();
  await expect.poll(() => installs).toBe(1);
});

test('anchored signed pane keeps source input and uses the installed child scope', async ({ page }) => {
  await page.goto('/e2e/fixtures/rich-package-host.html?anchor');
  const guest = page.frameLocator('iframe[data-page-ready="true"]').first().frameLocator('iframe');
  await guest.getByPlaceholder('Draft').fill('unsent');
  const section = page.getByRole('region', {name:'Signed pane'});
  const child = section.frameLocator('iframe').frameLocator('iframe');
  await expect(child.locator('body')).toContainText('?selection=first');
  await expect(child.locator('body')).not.toContainText('ignored');
  const denied = await guest.locator('body').evaluate(() =>
    window.memstack.invoke('child-op').then(() => '', error => error.message)
  );
  expect(denied).toBe('page_capability_unavailable');
  const unavailable = await guest.locator('body').evaluate(element => new Promise<string>(resolve => {
    const close = window.memstack.anchorSlot('unknown@1', element, '', reason => { close(); resolve(reason); });
  }));
  expect(unavailable).toBe('page_slot_denied');
  await child.getByRole('button', {name:'Operate'}).click();
  await expect(page.locator('#host-log')).toContainText('/child/commands');
  await expect(page.locator('#host-log')).toContainText('"project_id":"p"');
  await expect(section).toHaveCSS('width','280px');
  await guest.getByRole('button', { name: 'Drag divider' }).hover();
  await page.mouse.down();
  await expect(section).toHaveCSS('pointer-events', 'none');
  const box = await section.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await page.mouse.up();
  await expect(section).toHaveCSS('pointer-events', 'auto');
  await guest.getByRole('button',{name:'Resize pane'}).click();
  await expect(section).toHaveCSS('width','340px');
  await child.getByRole('button',{name:'Subscribe'}).click();
  await expect(page.locator('#host-log')).toHaveText('subscribed');
  await page.getByRole('button',{name:'Toggle pane installation'}).click();
  await expect(section).toHaveCount(0);
  await expect(page.locator('#host-log')).toHaveText('cancelled');
  await expect(page.getByRole('status').filter({hasText:'child/pane'})).toBeVisible();
  await page.getByRole('button',{name:'Toggle pane installation'}).click();
  await expect(child.getByRole('button',{name:'Operate'})).toBeVisible();
  await guest.getByRole('button',{name:'Close pane'}).click();
  await expect(section).toHaveCount(0);
  await expect(guest.getByPlaceholder('Draft')).toHaveValue('unsent');
});
