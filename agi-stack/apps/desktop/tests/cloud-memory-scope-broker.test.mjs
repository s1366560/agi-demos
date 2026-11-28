import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const root = process.env.CLOUD_MEMORY_AUTHORITY_DIST ?? '/tmp/agistack-desktop-test-dist';
const { executeVaultBoundCloudRequest } = require(`${root}/electron/main/cloudRequestPolicy.js`);

test('full desktop rejects memory scope on the old memories HTTP surface', async () => {
  await assert.rejects(
    executeVaultBoundCloudRequest(
      {
        path: '/api/v1/memories/',
        method: 'POST',
        memory_scope: {
          actor_id: 'actor',
          tenant_id: 'tenant',
          project_id: 'project',
          context_revision: 7,
        },
        mutation: {
          kind: 'memory-command',
          expected_revision: 0,
          idempotency_key: '00000000-0000-0000-0000-00000000000a',
        },
        body: { project_id: 'project', title: 'Title', content: 'Body' },
      },
      {
        async loadTrustedSession() {
          throw new Error('memory scope must be rejected before the vault');
        },
        async fetch() {
          throw new Error('memory scope must not reach the network');
        },
      },
    ),
    /cloud request memory endpoint is not allowed/,
  );
});
