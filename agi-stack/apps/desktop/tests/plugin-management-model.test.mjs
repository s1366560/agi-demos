import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  managedPluginFromMarketplaceEntry,
  marketplacePluginTargets,
} = require('/tmp/agistack-desktop-test-dist/src/api/pluginMarketplaceModel.js');

const installed = {
  plugin_id: 'release/notifier',
  version: '2.4.1',
  publisher: 'MemStack Labs',
  artifact_digest: 'sha256:artifact',
  artifact_registry: 'registry.example.test',
  artifact_repository: 'plugins/release-notifier',
  oci_manifest_digest: 'sha256:manifest',
  install_status: 'installed',
  manifest: {
    targets: ['python'],
    manifests: [
      {
        modules: [
          { targets: ['desktop-renderer', 'python'] },
          { targets: ['desktop-sidecar'] },
        ],
      },
    ],
  },
  signature: { algorithm: 'Ed25519' },
  provenance: { builder_id: 'builder-v2' },
  security_scan_status: 'passed',
  revoked: false,
  revocation_reason: null,
};

test('marketplace packages map to stable exact-version managed plugin records', () => {
  assert.deepEqual(managedPluginFromMarketplaceEntry(installed), {
    ...installed,
    id: 'release/notifier@2.4.1',
    name: 'release/notifier',
    source: 'marketplace-v2',
    package: 'plugins/release-notifier',
    kind: 'bundle-v2',
    enabled: true,
    discovered: true,
    targets: ['python', 'desktop-renderer', 'desktop-sidecar'],
  });
});

test('marketplace status and revocation deterministically remove composer availability', () => {
  assert.equal(
    managedPluginFromMarketplaceEntry({ ...installed, install_status: 'uninstalled' }).enabled,
    false,
  );
  assert.equal(
    managedPluginFromMarketplaceEntry({
      ...installed,
      revoked: true,
      revocation_reason: 'compromised signer',
    }).discovered,
    false,
  );
});

test('target projection is declared-data only, stable, and deduplicated', () => {
  assert.deepEqual(marketplacePluginTargets(installed.manifest), [
    'python',
    'desktop-renderer',
    'desktop-sidecar',
  ]);
  assert.deepEqual(marketplacePluginTargets({ arbitrary: 'desktop-renderer' }), []);
});
