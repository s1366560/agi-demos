import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { executeVaultBoundCloudRequest } = require(
  '/tmp/agistack-desktop-test-dist/electron/main/cloudRequestPolicy.js',
);

const trustedSession = Object.freeze({
  version: 1,
  api_base_url: 'https://cloud.memstack.test',
  runtime_mode: 'cloud',
  credential_kind: 'cloud_bearer',
  credential: 'vault-only-test-credential',
  expires_at: '2099-08-10T00:00:00Z',
});

function dependencies(requests) {
  return {
    async loadTrustedSession() {
      return trustedSession;
    },
    async fetch(url) {
      requests.push(new URL(url).pathname);
      return new Response(JSON.stringify({ context: { tenant_id: 'tenant-1', project_id: 'project-1', revision: 7 } }), {
        headers: { 'Content-Type': 'application/json' },
      });
    },
  };
}

const legacyPaths = [
  '/api/v1/memories/?project_id=project-1&page=1&page_size=50',
  '/api/v1/graph/entities/?tenant_id=tenant-1&project_id=project-1&limit=50&offset=0',
  '/api/v1/graph/entities/types?tenant_id=tenant-1&project_id=project-1',
  '/api/v1/graph/communities/?tenant_id=tenant-1&project_id=project-1&limit=50&offset=0',
  '/api/v1/graph/memory/graph?tenant_id=tenant-1&project_id=project-1&limit=1000',
  '/api/v1/projects/project-1/stats',
];

test('full desktop does not transport legacy knowledge HTTP', async () => {
  for (const path of legacyPaths) {
    const requests = [];
    await assert.rejects(
      executeVaultBoundCloudRequest({ method: 'GET', path }, dependencies(requests)),
      /cloud request endpoint is not allowed/,
    );
    assert.deepEqual(requests, []);
  }
});
