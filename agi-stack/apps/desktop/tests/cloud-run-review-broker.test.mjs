import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { executeVaultBoundCloudRequest } = require(
  '/tmp/agistack-desktop-test-dist/electron/main/cloudRequestPolicy.js',
);

test('full desktop does not transport legacy run review HTTP', async () => {
  const dependencies = {
    async loadTrustedSession() {
      throw new Error('run review HTTP must be rejected before the vault');
    },
    async fetch() {
      throw new Error('run review HTTP must not reach the network');
    },
  };
  for (const path of [
    '/api/v1/agent/runs/run-one/summary',
    '/api/v1/agent/runs/run-one/changes',
  ]) {
    await assert.rejects(
      executeVaultBoundCloudRequest({ method: 'GET', path }, dependencies),
      /cloud request endpoint is not allowed/,
    );
  }
});
