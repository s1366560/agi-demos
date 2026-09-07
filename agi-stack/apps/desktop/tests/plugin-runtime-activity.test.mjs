import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  return readFileSync(new URL(`../${relativePath}`, import.meta.url), 'utf8');
}

test('desktop plugin management is V2 marketplace-only', () => {
  const client = source('src/api/client.ts');
  const management = source('src/features/settings/usePluginManagement.ts');
  const dialogs = source('src/features/settings/PluginManagementDialogs.tsx');
  const settings = source('src/features/settings/SettingsWindow.tsx');

  assert.match(client, /plugin-marketplace\/packages\?include_revoked=true/u);
  assert.match(client, /uninstallMarketplacePlugin/u);
  assert.match(client, /tenant_id:\s*tenantId/u);
  assert.match(client, /version:\s*requireValue\(version/u);

  for (const content of [client, management, dialogs, settings]) {
    assert.doesNotMatch(
      content,
      /listManagedPlugins|getManagedPluginRuntime|setManagedPluginEnabled|installManagedPlugin|reloadManagedPlugins|getManagedPluginConfig|updateManagedPluginConfig|PluginRuntimeActivity/u,
    );
  }
  assert.doesNotMatch(
    client,
    /channels\/tenants\/\$\{encodeURIComponent\(tenantId\)\}\/plugins`/u,
  );
});
