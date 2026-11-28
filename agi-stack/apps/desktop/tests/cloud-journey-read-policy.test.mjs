import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { executeVaultBoundCloudRequest } = require(
  '/tmp/agistack-desktop-test-dist/electron/main/cloudRequestPolicy.js',
);

const paths = [
  '/api/v1/system/features',
  '/api/v1/artifacts?project_id=project-1&limit=100',
  '/api/v1/attachments?conversation_id=conversation-1',
];

test('full desktop does not transport legacy journey reads', async () => {
  const dependencies = {
    async loadTrustedSession() {
      return {
        version: 1,
        api_base_url: 'https://cloud.test',
        runtime_mode: 'cloud',
        credential_kind: 'cloud_bearer',
        credential: 'test-only',
        expires_at: '2099-09-14T00:00:00Z',
      };
    },
    async fetch() {
      throw new Error('legacy journey HTTP must not reach the network');
    },
  };
  for (const path of paths) {
    await assert.rejects(
      executeVaultBoundCloudRequest({ path, method: 'GET' }, dependencies),
      /cloud request endpoint is not allowed/,
    );
  }
});
