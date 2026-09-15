import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const { DesktopApiClient } = require('/tmp/agistack-desktop-test-dist/src/api/client.js');
const { executeVaultBoundCloudRequest } = require('/tmp/agistack-desktop-test-dist/electron/main/cloudRequestPolicy.js');
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('cloud identity catalogs reach canonical slash routes through the vault policy', async () => {
  const original = globalThis.window;
  const requested = [];
  const deps = {
    loadTrustedSession: async () => ({ version: 1, api_base_url: 'https://cloud.test', runtime_mode: 'cloud', credential_kind: 'cloud_bearer', credential: 'test-only', expires_at: '2099-09-14T00:00:00Z' }),
    async fetch(input) {
      const url = new URL(input);
      if (url.pathname === '/api/v1/workspace-context') return new Response(JSON.stringify({ context: { tenant_id: 'tenant-1', project_id: 'project-1', revision: 1 } }), { headers: { 'content-type': 'application/json' } });
      requested.push(url.pathname);
      const key = url.pathname === '/api/v1/tenants/' ? 'tenants' : url.pathname === '/api/v1/projects/' ? 'projects' : null;
      if (!key) return new Response(JSON.stringify({detail: 'Not found'}), { status: 404, headers: { 'content-type': 'application/json' } });
      return new Response(JSON.stringify({ [key]: key === 'tenants' ? [{ id: 'tenant-1', name: 'Tenant' }] : [{ id: 'project-1', tenant_id: 'tenant-1', name: 'Project' }], page: 1, page_size: 100, total: 1 }), { headers: { 'content-type': 'application/json' } });
    },
  };
  globalThis.window = { __MEMSTACK_DESKTOP__: { core: { async invoke(command, input) { assert.equal(command, 'cloud_request'); return executeVaultBoundCloudRequest(input.request, deps); } } } };
  try {
    const client = new DesktopApiClient({ ...DEFAULT_CONFIG, mode: 'cloud', apiKey: '', apiBaseUrl: 'https://cloud.test', tenantId: 'tenant-1', projectId: 'project-1' });
    assert.equal((await client.listTenants())[0].id, 'tenant-1');
    assert.equal((await client.listProjects('tenant-1'))[0].id, 'project-1');
    assert.deepEqual(requested, ['/api/v1/tenants/', '/api/v1/projects/']);
    await assert.rejects(client.listProjects('tenant-foreign'), /tenant scope mismatch/);
    assert.equal(requested.length, 2);
    await assert.rejects(executeVaultBoundCloudRequest({ path: '/api/v1/projects/?tenant_id=tenant-1&page=1&page_size=100&include_secrets=true', method: 'GET' }, deps), /endpoint is not allowed/);
  } finally { globalThis.window = original; }
});
