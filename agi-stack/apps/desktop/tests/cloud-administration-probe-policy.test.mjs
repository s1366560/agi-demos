import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const { executeVaultBoundCloudRequest } = require('/tmp/agistack-desktop-test-dist/electron/main/cloudRequestPolicy.js');
function dependencies(projectTenant = 'tenant-1') {
  const calls = [];
  return {
    calls,
    loadTrustedSession: async () => ({ version: 1, api_base_url: 'https://cloud.test', runtime_mode: 'cloud', credential_kind: 'cloud_bearer', credential: 'test-only', expires_at: '2099-09-14T00:00:00Z' }),
    fetch: async (url) => {
      const target = new URL(url); calls.push(target.pathname + target.search);
      const body = target.pathname === '/api/v1/workspace-context'
        ? { context: { tenant_id: 'tenant-1', project_id: 'project-1', revision: 1 } }
        : target.pathname === '/api/v1/projects/project-2'
          ? { id: 'project-2', tenant_id: projectTenant }
          : { items: [] };
      return new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } });
    },
  };
}
const reads = [
  '/api/v1/agent/definitions?tenant_id=tenant-1&scope=tenant&enabled_only=true&limit=100',
  ...['entities', 'edges', 'mappings'].map((part) => `/api/v1/projects/project-1/schema/${part}`),
  ...['maintenance/status', 'data/stats', 'maintenance/embeddings/status'].map((part) => `/api/v1/${part}?tenant_id=tenant-1&project_id=project-1`),
];
for (const path of reads) test(`legacy administration HTTP is not a full-desktop bypass: ${path}`, async () => {
  const deps = dependencies();
  await assert.rejects(
    executeVaultBoundCloudRequest({ path, method: 'GET' }, deps),
    /cloud request endpoint is not allowed/,
  );
  assert.deepEqual(deps.calls, []);
});
test('tenant catalog membership observes authoritative project ownership before another project read', async () => {
  const path = '/api/v1/projects/project-2/members?tenant_id=tenant-1';
  const deps = dependencies();
  assert.equal((await executeVaultBoundCloudRequest({ path, method: 'GET' }, deps)).status, 200);
  assert.deepEqual(deps.calls, ['/api/v1/workspace-context', '/api/v1/projects/project-2?tenant_id=tenant-1', path]);
  const foreign = dependencies('foreign');
  await assert.rejects(executeVaultBoundCloudRequest({ path, method: 'GET' }, foreign), /catalog project scope observation failed/);
  assert.equal(foreign.calls.includes(path), false);
  const visible = dependencies();
  assert.equal((await executeVaultBoundCloudRequest({ path: '/api/v1/projects/project-2/members', method: 'GET' }, visible)).status, 200);
  assert.ok(visible.calls.includes('/api/v1/projects/project-2?tenant_id=tenant-1'));
});

test('host project catalog stays available while legacy knowledge probes stay closed', async () => {
  const deps = dependencies();
  assert.equal((await executeVaultBoundCloudRequest({
    path: '/api/v1/projects/?tenant_id=tenant-1&page=1&page_size=100',
    method: 'GET',
  }, deps)).status, 200);
  for (const path of reads.slice(1)) {
    await assert.rejects(
      executeVaultBoundCloudRequest({ path, method: 'GET' }, dependencies()),
      /cloud request endpoint is not allowed/,
    );
  }
});
