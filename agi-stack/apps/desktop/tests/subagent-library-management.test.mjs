import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { DesktopApiClient } = require('/tmp/agistack-desktop-test-dist/src/api/client.js');
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('managed SubAgent library APIs preserve template install and filesystem import scope', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init = {}) => {
    const url = new URL(String(input));
    calls.push({ url, init });
    if (url.pathname.endsWith('/templates/list')) {
      return Response.json({
        templates: [
          {
            id: 'template-release-reviewer',
            tenant_id: 'tenant-1',
            name: 'release-reviewer',
            version: '1.0.0',
            display_name: 'Release reviewer',
            description: 'Reviews release evidence.',
            category: 'engineering',
            tags: ['release'],
            system_prompt: 'Review the release.',
            trigger_description: 'Use for release review.',
            trigger_keywords: ['release'],
            trigger_examples: [],
            model: 'inherit',
            max_tokens: 4096,
            temperature: 0.4,
            max_iterations: 10,
            allowed_tools: ['run_tests'],
            author: 'MemStack',
            is_builtin: true,
            is_published: true,
            install_count: 4,
            rating: 4.8,
            metadata: null,
            created_at: null,
            updated_at: null,
          },
        ],
        total: 1,
      });
    }
    return Response.json({
      id: 'subagent-release-reviewer',
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      name: 'release-reviewer',
      enabled: true,
      source: 'database',
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
    const templates = await client.listManagedSubAgentTemplates();
    await client.installManagedSubAgentTemplate(templates.templates[0].id);
    await client.importManagedFilesystemSubAgent('filesystem/researcher', 'project-1');

    assert.equal(templates.total, 1);
    assert.equal(calls[0].url.pathname, '/api/v1/subagents/templates/list');
    assert.equal(calls[0].url.searchParams.get('tenant_id'), 'tenant-1');
    assert.equal(calls[0].url.searchParams.get('limit'), '100');
    assert.equal(
      calls[1].url.pathname,
      '/api/v1/subagents/templates/template-release-reviewer/install',
    );
    assert.equal(calls[1].init.method, 'POST');
    assert.equal(
      calls[2].url.pathname,
      '/api/v1/subagents/filesystem/filesystem%2Fresearcher/import',
    );
    assert.equal(calls[2].url.searchParams.get('project_id'), 'project-1');
    assert.equal(calls[2].url.searchParams.get('tenant_id'), 'tenant-1');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Desktop SubAgent surfaces expose the governed library and filesystem import', () => {
  const settingsSource = readFileSync(
    new URL('../src/features/settings/SettingsWindow.tsx', import.meta.url),
    'utf8',
  );
  const resourceSource = readFileSync(
    new URL('../src/features/settings/ManagedResourceViews.tsx', import.meta.url),
    'utf8',
  );
  const dialogSource = readFileSync(
    new URL('../src/features/settings/SubAgentLibraryDialog.tsx', import.meta.url),
    'utf8',
  );
  const dialogsSource = readFileSync(
    new URL('../src/features/settings/SettingsManagementDialogs.tsx', import.meta.url),
    'utf8',
  );
  const managementSource = readFileSync(
    new URL('../src/features/settings/useSubAgentLibraryManagement.ts', import.meta.url),
    'utf8',
  );
  const qaSource = readFileSync(new URL('../src/qa/ProviderSettingsQa.tsx', import.meta.url), 'utf8');
  const i18nSource = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');

  assert.match(settingsSource, /useSubAgentLibraryManagement/);
  assert.match(settingsSource, /if \(resourceLoading\) return;/);
  assert.match(dialogsSource, /SubAgentLibraryDialog/);
  assert.match(resourceSource, /settings\.subagentLibrary\.action/);
  assert.match(resourceSource, /settings\.subagentLibrary\.importFilesystem/);
  assert.match(dialogSource, /onInstall/);
  assert.match(managementSource, /installManagedSubAgentTemplate/);
  assert.match(managementSource, /importManagedFilesystemSubAgent/);
  assert.equal(
    managementSource.match(/await onReload\(created\.id\);/g)?.length,
    2,
  );
  assert.match(qaSource, /subagents\/templates\/list/);
  assert.match(qaSource, /filesystemSubagentImportMatch/);
  assert.match(i18nSource, /'settings\.subagentLibrary\.action': 'Template library'/);
  assert.match(i18nSource, /'settings\.subagentLibrary\.action': '模板库'/);
});
