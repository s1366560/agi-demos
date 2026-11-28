import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const root = process.env.CLOUD_MEMORY_TEST_DIST ?? '/tmp/agistack-desktop-test-dist';
const { executeVaultBoundCloudRequest } = require(`${root}/electron/main/cloudRequestPolicy.js`);

const mutation = {
  kind: 'memory-command',
  expected_revision: 0,
  idempotency_key: '00000000-0000-0000-0000-00000000000a',
};

test('full desktop does not admit legacy memory commands', async () => {
  const dependencies = {
    async loadTrustedSession() {
      throw new Error('memory HTTP must be rejected before the vault');
    },
    async fetch() {
      throw new Error('memory HTTP must not reach the network');
    },
  };
  for (const request of [
    { method: 'POST', path: '/api/v1/memories/', mutation, body: { project_id: 'project-1', title: 'Title', content: 'Content' } },
    { method: 'PATCH', path: '/api/v1/memories/memory-1?project_id=project-1', mutation, body: { title: 'Next' } },
    { method: 'DELETE', path: '/api/v1/memories/memory-1?project_id=project-1', mutation },
    { method: 'GET', path: '/api/v1/memories/memory-1?project_id=project-1' },
  ]) {
    await assert.rejects(
      executeVaultBoundCloudRequest(request, dependencies),
      /cloud request memory endpoint is not allowed|cloud request endpoint is not allowed/,
    );
  }
});
