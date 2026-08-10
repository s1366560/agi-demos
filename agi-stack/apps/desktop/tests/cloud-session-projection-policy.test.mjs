import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { projectVaultBoundCloudSession } = require(
  '/tmp/agistack-desktop-test-dist/electron/main/cloudRequestPolicy.js',
);

const mainSource = readFileSync(new URL('../electron/main/index.ts', import.meta.url), 'utf8');
const preloadSource = readFileSync(new URL('../electron/preload/index.ts', import.meta.url), 'utf8');

const trustedSession = Object.freeze({
  version: 1,
  api_base_url: 'https://cloud.memstack.test',
  runtime_mode: 'cloud',
  credential_kind: 'cloud_bearer',
  credential: 'vault-only-session-secret',
  expires_at: '2099-08-10T00:00:00Z',
});

test('vault-bound Cloud session projection returns identity and scope without the bearer', async () => {
  const requests = [];
  const projection = await projectVaultBoundCloudSession({
    async loadTrustedSession() {
      return trustedSession;
    },
    async fetch(url, init) {
      requests.push({ url, init });
      const path = new URL(url).pathname;
      if (path === '/api/v1/workspace-context') {
        return jsonResponse({
          context: {
            tenant_id: 'tenant-1',
            project_id: 'project-1',
            workspace_id: 'workspace-1',
            revision: 7,
          },
        });
      }
      if (path === '/api/v1/auth/me') {
        return jsonResponse({ user_id: 'user-1', email: 'user@example.test', roles: [] });
      }
      if (path === '/api/v1/tenants') {
        assert.equal(new URL(url).search, '?page=1&page_size=100');
        return jsonResponse({
          tenants: [{ id: 'tenant-1', name: 'Tenant One' }],
          total: 1,
          page: 1,
          page_size: 100,
        });
      }
      assert.equal(path, '/api/v1/projects');
      assert.equal(new URL(url).search, '?page=1&page_size=100&tenant_id=tenant-1');
      return jsonResponse({
        projects: [{ id: 'project-1', tenant_id: 'tenant-1', name: 'Project One' }],
        total: 1,
        page: 1,
        page_size: 100,
      });
    },
  });

  assert.deepEqual(projection, {
    status: 'authenticated',
    api_base_url: 'https://cloud.memstack.test',
    expires_at: '2099-08-10T00:00:00Z',
    user: { user_id: 'user-1', email: 'user@example.test', roles: [] },
    workspace_context: {
      context: {
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        workspace_id: 'workspace-1',
        revision: 7,
      },
    },
    tenants: [{ id: 'tenant-1', name: 'Tenant One' }],
    projects: [{ id: 'project-1', tenant_id: 'tenant-1', name: 'Project One' }],
  });
  assert.equal(requests.length, 4);
  assert.equal(
    requests.every(
      ({ init }) =>
        new Headers(init.headers).get('Authorization') ===
        `Bearer ${trustedSession.credential}`,
    ),
    true,
  );
  assert.equal(JSON.stringify(projection).includes(trustedSession.credential), false);
});

test('vault-bound Cloud session projection returns null without touching the network when signed out', async () => {
  const projection = await projectVaultBoundCloudSession({
    async loadTrustedSession() {
      return null;
    },
    async fetch() {
      throw new Error('signed-out projection must not use the network');
    },
  });
  assert.equal(projection, null);
});

test('Electron exposes the sanitized projection as a main-owned cancellable command', () => {
  assert.match(preloadSource, /'cloud_session_projection'/u);
  assert.match(mainSource, /case 'cloud_session_projection':/u);
  assert.match(mainSource, /projectVaultBoundCloudSession/u);
  assert.match(mainSource, /cloudRequestExecutions\.begin\(ownerId, args\?\.requestId\)/u);
});

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
