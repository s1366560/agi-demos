import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const { executeVaultBoundCloudRequest } = require('/tmp/agistack-desktop-test-dist/electron/main/cloudRequestPolicy.js');
const catalog = '/api/v1/plugin-marketplace/packages?include_revoked=true';
function harness(status = 200) {
  const paths = [];
  return { paths, dependencies: {
    async loadTrustedSession() { return { version: 1, api_base_url: 'https://cloud.memstack.test', runtime_mode: 'cloud', credential_kind: 'cloud_bearer', credential: 'test-only-vault-token', expires_at: null }; },
    async fetch(url) {
      const path = new URL(url).pathname;
      paths.push(path);
      return new Response(JSON.stringify(path === '/api/v1/workspace-context'
        ? { context: { tenant_id: 'tenant-1', project_id: 'project-1', revision: 1 } }
        : status === 200 ? [] : { detail: 'Forbidden' }), { status: path === '/api/v1/workspace-context' ? 200 : status, headers: { 'Content-Type': 'application/json' } });
    },
  } };
}
test('cloud marketplace catalog reaches authenticated API and preserves empty results', async () => {
  const h = harness();
  assert.deepEqual(await executeVaultBoundCloudRequest({ path: catalog, method: 'GET' }, h.dependencies), { status: 200, body: [] });
  assert.equal(h.paths.at(-1), '/api/v1/plugin-marketplace/packages');
});
test('cloud marketplace uninstall is scoped and server authorization remains authoritative', async () => {
  const h = harness(403);
  const input = { path: '/api/v1/plugin-marketplace/packages/qa-plugin/uninstall', method: 'POST', body: { tenant_id: 'tenant-1', version: '1.0.0' } };
  assert.equal((await executeVaultBoundCloudRequest(input, h.dependencies)).status, 403);
  const other = harness();
  await assert.rejects(executeVaultBoundCloudRequest({ ...input, body: { ...input.body, tenant_id: 'tenant-2' } }, other.dependencies), /tenant scope mismatch/);
  assert.deepEqual(other.paths, ['/api/v1/workspace-context']);
});
test('cloud marketplace rejects extra queries, methods, actions, and uninstall body fields', async () => {
  for (const input of [
    { path: catalog + '&include_revoked=false', method: 'GET' },
    { path: catalog + '&tenant_id=tenant-2', method: 'GET' },
    { path: catalog, method: 'POST' },
    { path: '/api/v1/plugin-marketplace/packages/qa-plugin/install', method: 'POST' },
    { path: '/api/v1/plugin-marketplace/packages/qa-plugin/uninstall', method: 'POST', body: { tenant_id: 'tenant-1', version: '1', arbitrary: true } },
  ]) {
    const h = harness();
    await assert.rejects(executeVaultBoundCloudRequest(input, h.dependencies), /endpoint is not allowed/);
    assert.deepEqual(h.paths, []);
  }
});
