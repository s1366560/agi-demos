import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { DesktopApiClient } = require('/tmp/agistack-desktop-test-dist/src/api/client.js');
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

const settingsWindowSource = readFileSync(
  new URL('../src/features/settings/SettingsWindow.tsx', import.meta.url),
  'utf8',
);
const managedResourceViewsSource = readFileSync(
  new URL('../src/features/settings/ManagedResourceViews.tsx', import.meta.url),
  'utf8',
);
const skillManagementDialogsSource = readFileSync(
  new URL('../src/features/settings/SkillManagementDialogs.tsx', import.meta.url),
  'utf8',
);
const skillPackageDialogsSource = readFileSync(
  new URL('../src/features/settings/SkillPackageDialogs.tsx', import.meta.url),
  'utf8',
);
const providerSettingsQaSource = readFileSync(
  new URL('../src/qa/ProviderSettingsQa.tsx', import.meta.url),
  'utf8',
);
const i18nSource = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');

const skill = {
  id: 'release-readiness',
  tenant_id: 'tenant-1',
  project_id: 'project-1',
  name: 'release-readiness',
  description: 'Checks release evidence.',
  status: 'active',
  scope: 'project',
  tools: ['run_tests'],
  current_version: 3,
  is_system_skill: false,
};

test('managed skill package APIs preserve JSON, multipart, version, and rollback contracts', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init = {}) => {
    const url = new URL(String(input));
    calls.push({ url, init });
    if (url.pathname.endsWith('/versions')) {
      return Response.json({
        versions: [
          {
            id: 'version-3',
            skill_id: skill.id,
            version_number: 3,
            version_label: '1.2.0',
            change_summary: 'Tighten checks',
            created_by: 'agent',
            created_at: '2026-07-21T10:00:00Z',
          },
        ],
        total: 1,
      });
    }
    if (url.pathname.endsWith('/rollback')) return Response.json(skill);
    return Response.json({
      action: 'import',
      skill,
      version_number: 3,
      version_label: '1.2.0',
    });
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      mode: 'cloud',
      apiBaseUrl: 'https://api.memstack.test',
      apiKey: 'cloud-session',
      tenantId: 'tenant-1',
      projectId: 'project-1',
    });
    await client.importManagedSkillPackage({
      skill_md_content: '---\nname: release-readiness\n---\n\nVerify.',
      resource_files: { 'references/checklist.md': 'Check tests.' },
      scope: 'project',
      project_id: 'project-1',
      overwrite: true,
      change_summary: 'Import package',
    });
    const archive = new File(['skill zip'], 'release-readiness.zip', {
      type: 'application/zip',
    });
    await client.importManagedSkillZip(archive, {
      scope: 'project',
      project_id: 'project-1',
      overwrite: true,
      change_summary: 'Import archive',
    });
    const versions = await client.listManagedSkillVersions(skill.id);
    await client.rollbackManagedSkill(skill.id, 2);

    assert.equal(versions.total, 1);
    assert.equal(versions.versions[0].version_number, 3);
    assert.equal(calls[0].url.pathname, '/api/v1/skills/import');
    assert.equal(calls[0].url.searchParams.get('tenant_id'), 'tenant-1');
    assert.deepEqual(JSON.parse(calls[0].init.body), {
      skill_md_content: '---\nname: release-readiness\n---\n\nVerify.',
      resource_files: { 'references/checklist.md': 'Check tests.' },
      scope: 'project',
      project_id: 'project-1',
      overwrite: true,
      change_summary: 'Import package',
    });

    assert.equal(calls[1].url.pathname, '/api/v1/skills/import/zip');
    assert.equal(calls[1].init.body instanceof FormData, true);
    assert.equal(new Headers(calls[1].init.headers).has('content-type'), false);
    assert.equal(calls[1].init.body.get('archive').name, 'release-readiness.zip');
    assert.equal(calls[1].init.body.get('scope'), 'project');
    assert.equal(calls[1].init.body.get('project_id'), 'project-1');
    assert.equal(calls[1].init.body.get('overwrite'), 'true');
    assert.equal(calls[1].init.body.get('change_summary'), 'Import archive');

    assert.equal(calls[2].url.pathname, '/api/v1/skills/release-readiness/versions');
    assert.equal(calls[2].url.searchParams.get('tenant_id'), 'tenant-1');
    assert.equal(calls[2].url.searchParams.get('limit'), '50');
    assert.equal(calls[3].url.pathname, '/api/v1/skills/release-readiness/rollback');
    assert.deepEqual(JSON.parse(calls[3].init.body), { version_number: 2 });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Desktop skill surfaces expose import, version history, and guarded rollback controls', () => {
  assert.match(settingsWindowSource, /SkillManagementDialogs/);
  assert.match(skillManagementDialogsSource, /SkillImportDialog/);
  assert.match(skillManagementDialogsSource, /SkillVersionsDialog/);
  assert.match(settingsWindowSource, /skillPackageManagement\.openImport/);
  assert.match(settingsWindowSource, /skillPackageManagement\.openVersions/);
  assert.match(managedResourceViewsSource, /settings\.skillPackages\.importAction/);
  assert.match(managedResourceViewsSource, /settings\.skillPackages\.versionsAction/);
  assert.match(skillPackageDialogsSource, /accept="\.zip,application\/zip"/);
  assert.match(skillPackageDialogsSource, /settings\.skillPackages\.overwrite/);
  assert.match(skillPackageDialogsSource, /settings\.skillPackages\.rollbackConfirm/);
  assert.match(
    skillPackageDialogsSource,
    /if \(rollbackVersion === null\) setConfirmVersion\(null\)/,
  );
  assert.match(providerSettingsQaSource, /\/api\/v1\/skills\/import\/zip/);
  assert.match(providerSettingsQaSource, /\/versions\$/);
  assert.match(providerSettingsQaSource, /\/rollback\$/);
  assert.match(i18nSource, /'settings\.skillPackages\.importAction': 'Import'/);
  assert.match(i18nSource, /'settings\.skillPackages\.importAction': '导入'/);
});
