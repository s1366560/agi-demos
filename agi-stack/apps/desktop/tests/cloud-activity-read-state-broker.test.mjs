import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { executeVaultBoundCloudRequest } = require(
  '/tmp/agistack-desktop-test-dist/electron/main/cloudRequestPolicy.js',
);

test('full desktop does not transport legacy activity read-state HTTP', async () => {
  const dependencies = {
    async loadTrustedSession() {
      throw new Error('activity HTTP must be rejected before the vault');
    },
    async fetch() {
      throw new Error('activity HTTP must not reach the network');
    },
  };
  const path = '/api/v1/projects/project-one/activity/read-state';
  await assert.rejects(
    executeVaultBoundCloudRequest({ method: 'GET', path }, dependencies),
    /cloud request endpoint is not allowed/,
  );
  await assert.rejects(
    executeVaultBoundCloudRequest(
      {
        method: 'PUT',
        path,
        body: { expected_authority_revision: 3, entries: [] },
      },
      dependencies,
    ),
    /cloud request endpoint is not allowed/,
  );
});
