import { createHash } from 'node:crypto';

import { createTestProject, getAdminAuthToken, loginAsAdmin, test, expect } from './base';

function slotDocument(title: string) {
  const bytes = Buffer.from(
    JSON.stringify({
      schema: 'memstack.slot-ui/1',
      title,
      actions: [{ id: 'save', label: 'Save note' }],
    })
  );
  return {
    bytes,
    digest: `sha256:${createHash('sha256').update(bytes).digest('hex')}`,
    bytes_base64: bytes.toString('base64'),
  };
}

test('plugin hub installs, enables, rolls back, and uninstalls a signed package', async ({
  page,
}) => {
  test.setTimeout(180_000);
  page.setDefaultTimeout(30_000);
  const token = await getAdminAuthToken();
  const project = await createTestProject({
    name: `Optional business ${Date.now()}`,
    description: 'Signed package lifecycle',
    token,
  });
  const notes = slotDocument('Notes');
  const updated = slotDocument('Notes updated');
  const documents: Record<string, ReturnType<typeof slotDocument>> = {
    '1.0.0': notes,
    '1.1.0': updated,
  };
  let recorded = false;
  let revision = 0;
  let installed = '1.0.0';
  let applied: string | null = null;
  const history: string[] = [];
  let phase = 'inactive';

  await page.route('**/optional-business/**', async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    const path = url.pathname;
    if (method === 'GET' && path.endsWith('/optional-business/')) {
      await route.fulfill({ json: { items: recorded ? [{ plugin_id: 'sample.notes' }] : [] } });
      return;
    }
    if (method === 'POST' && path.endsWith('/inspect')) {
      const version = Buffer.from(
        route.request().postDataJSON().archive_base64,
        'base64'
      ).toString();
      await route.fulfill({
        json: {
          plugin_id: 'sample.notes',
          version,
          digest: documents[version]!.digest,
          permissions: ['tools.execute', 'ui.slot'],
        },
      });
      return;
    }
    if (method === 'POST' && path.endsWith('/install')) {
      revision++;
      recorded = true;
      installed = Buffer.from(route.request().postDataJSON().archive_base64, 'base64').toString();
      await new Promise((resolve) => setTimeout(resolve, 200));
      await route.fulfill({ json: { status: 'recorded', plugin_id: 'sample.notes' } });
      return;
    }
    if (
      method === 'POST' &&
      ['enable', 'rollback', 'disable', 'uninstall'].includes(path.split('/').pop() ?? '')
    ) {
      expect(route.request().postDataJSON().expected_revision).toBe(revision);
      revision++;
    }
    if (method === 'POST' && path.endsWith('/enable')) {
      if (applied !== installed) {
        if (applied) history.push(applied);
        applied = installed;
      }
      phase = 'active';
      await route.fulfill({
        json: { status: 'enable', runtime_phase: phase, retention: 'retained' },
      });
      return;
    }
    if (method === 'POST' && path.endsWith('/rollback')) {
      const prior = history.pop();
      if (prior) applied = prior;
      phase = 'active';
      await route.fulfill({
        json: { status: 'rollback', runtime_phase: phase, retention: 'retained' },
      });
      return;
    }
    if (method === 'POST' && path.endsWith('/disable')) {
      phase = 'inactive';
      await route.fulfill({
        json: { status: 'disable', runtime_phase: phase, retention: 'retained' },
      });
      return;
    }
    if (method === 'POST' && path.endsWith('/uninstall')) {
      recorded = false;
      applied = null;
      phase = 'inactive';
      await route.fulfill({
        json: { status: 'uninstall', runtime_phase: phase, retention: 'retained' },
      });
      return;
    }
    if (method === 'GET' && path.endsWith('/ui')) {
      const document = applied ? documents[applied] : undefined;
      if (!document || phase !== 'active') {
        await route.fulfill({ status: 409, json: { detail: 'ui is not mounted' } });
        return;
      }
      await route.fulfill({
        json: {
          digest: document.digest,
          bytes_base64: document.bytes_base64,
          source: 'signed-package://sample.notes/ui.json',
          module_ref: 'signed:sample.notes/tool_result_renderer',
        },
      });
      return;
    }
    if (!recorded) {
      await route.fulfill({ status: 404, json: { detail: 'package is not recorded' } });
      return;
    }
    const document = applied ? documents[applied] : documents[installed];
    await route.fulfill({
      json: {
        plugin_id: 'sample.notes',
        version: applied ?? installed,
        package_recorded: true,
        has_web_ui: true,
        installed_version: installed,
        desired_revision: revision,
        running_version: applied,
        commands: [],
        desired_enabled: phase === 'active',
        runtime_phase: phase,
        actual_digest: document?.digest ?? null,
        failure: null,
        retention: 'retained',
      },
    });
  });

  const hub = `/tenant/${project.tenantId}/plugins?projectId=${project.id}&optionalPlugin=sample.notes`;
  async function showRecordedPhase(text: string) {
    const phase = page.getByTestId('optional-business-phase');
    try {
      await expect(phase).toHaveText(text, { timeout: 5_000 });
    } catch {
      await page.goto(hub);
      await expect(page.getByRole('heading', { name: 'Plugin Hub' })).toBeVisible({
        timeout: 45_000,
      });
      await expect(phase).toHaveText(text);
    }
  }

  await loginAsAdmin(page);
  await page.goto(`/tenant/${project.tenantId}/plugins?projectId=${project.id}`);
  await expect(page.getByRole('heading', { name: 'Plugin Hub' })).toBeVisible({ timeout: 45_000 });
  await page.getByTestId('optional-business-package').setInputFiles({
    name: 'notes-1.0.0.mspkg',
    mimeType: 'application/zip',
    buffer: Buffer.from('1.0.0'),
  });
  await expect(page.getByTestId('optional-business-panel')).toHaveAttribute(
    'data-package-ready',
    'yes'
  );
  await expect(page.getByTestId('optional-business-install')).toBeEnabled();
  await page.getByTestId('optional-business-install').click();
  await expect(page.getByTestId('optional-business-progress')).toBeVisible();
  await showRecordedPhase('inactive');
  await expect(page.getByTestId('signed-business-slot')).toHaveCount(0);

  await expect(page.getByTestId('optional-business-enable')).toBeEnabled({ timeout: 45_000 });
  await page.getByTestId('optional-business-enable').click();
  const frame = page.getByTestId('signed-business-slot');
  await expect(frame).toBeVisible();
  await expect(frame).toHaveAttribute('srcdoc', /<h1>Notes</);

  await page.getByTestId('optional-business-package').setInputFiles({
    name: 'notes-1.1.0.mspkg',
    mimeType: 'application/zip',
    buffer: Buffer.from('1.1.0'),
  });
  await expect(page.getByTestId('optional-business-panel')).toHaveAttribute(
    'data-package-ready',
    'yes'
  );
  await expect(page.getByTestId('optional-business-install')).toBeEnabled();
  await page.getByTestId('optional-business-install').click();
  await showRecordedPhase('active');
  await expect(page.getByTestId('optional-business-enable')).toBeEnabled({ timeout: 45_000 });
  await page.getByTestId('optional-business-enable').click();
  await expect(frame).toHaveAttribute('srcdoc', /Notes updated/);
  await page.getByTestId('optional-business-rollback').click();
  await expect(frame).toHaveAttribute('srcdoc', /<h1>Notes</, { timeout: 15_000 });
  await page.getByTestId('optional-business-uninstall').click();
  await expect(page.getByTestId('signed-business-slot')).toHaveCount(0);
  await expect(page.getByTestId('optional-business-phase')).toHaveText('not recorded');
});
