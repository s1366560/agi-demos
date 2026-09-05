import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const source = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');

test('SubAgent management and both composer paths require V2 authority injection', () => {
  const app = source('App.tsx');
  const settings = source('features/settings/SettingsWindow.tsx');
  const provider = source('features/task/desktopNewThreadComposerCatalogClientProviderV2.ts');
  assert.match(app, /createDesktopTenantSubAgentDefinitionsOperationsV2\(/u);
  assert.match(app, /desktopTenantSubAgentDefinitionsClientV2\.listManagedSubAgents\(signal\)/u);
  assert.match(settings, /tenantSubAgentDefinitionsClientV2\.listManagedSubAgents\(signal\)/u);
  assert.match(settings, /tenantSubAgentDefinitionsClientV2\.setManagedSubAgentEnabled\(/u);
  assert.match(provider, /createDesktopTenantSubAgentDefinitionsClientV2\(/u);
  assert.doesNotMatch(provider, /authority\.listManagedSubAgents/u);
  for (const path of ['useSubAgentDefinitionManagement.ts', 'useSubAgentLibraryManagement.ts']) {
    const hook = source(`features/settings/${path}`);
    assert.doesNotMatch(hook, /new ManagedResourcesClient/u);
    assert.match(hook, /DesktopTenantSubAgentDefinitionsClientV2/u);
  }
});

test('SubAgent static client methods and optional catalog fallback are retired', () => {
  for (const path of ['api/client.ts', 'api/managedResourcesClient.ts']) {
    assert.doesNotMatch(source(path), /async (?:listManagedSubAgents|setManagedSubAgentEnabled|importManagedFilesystemSubAgent|createManagedSubAgent|updateManagedSubAgent|deleteManagedSubAgent)\(/u);
  }
  const composer = source('features/chat/composerCatalogModel.ts');
  assert.doesNotMatch(composer, /listManagedSubAgents\?/u);
});
