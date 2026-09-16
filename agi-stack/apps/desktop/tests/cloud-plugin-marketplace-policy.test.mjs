import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const { executeVaultBoundCloudRequest } = require('/tmp/agistack-desktop-test-dist/electron/main/cloudRequestPolicy.js');
const catalog = '/api/v1/plugin-marketplace/packages?include_revoked=true';
const installBody = {
  plugin_id: 'qa-plugin',
  version: '1.0.0',
  publisher: 'qa',
  tenant_id: 'tenant-1',
  artifact: { registry: 'https://registry.qa.test', repository: 'qa/plugin', manifest_sha256: 'a'.repeat(64) },
  artifact_sha256: 'b'.repeat(64),
  manifest: { schema_version: 2 },
  signature: { algorithm: 'Ed25519', public_key_pem: 'pem', signature_base64: 'sig' },
  provenance: { predicate_type: 'https://slsa.dev/provenance/v1', builder_id: 'builder', subject_name: 'subject' },
  approved_permissions: ['tools.execute'],
  tenant_admin_approved: true,
  security_scan_passed: true,
};
function harness(status = 200, responseBody) {
  const paths = [];
  return { paths, dependencies: {
    async loadTrustedSession() { return { version: 1, api_base_url: 'https://cloud.memstack.test', runtime_mode: 'cloud', credential_kind: 'cloud_bearer', credential: 'test-only-vault-token', expires_at: null }; },
    async fetch(url) {
      const path = new URL(url).pathname;
      paths.push(path);
      return new Response(JSON.stringify(path === '/api/v1/workspace-context'
        ? { context: { tenant_id: 'tenant-1', project_id: 'project-1', revision: 1 } }
        : status === 200 || status === 202 ? (responseBody ?? []) : { detail: 'Forbidden' }), { status: path === '/api/v1/workspace-context' ? 200 : status, headers: { 'Content-Type': 'application/json' } });
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
test('cloud marketplace install forwards the exact signed V2 request', async () => {
  const h = harness(202, { plugin_id: 'qa-plugin', version: '1.0.0', status: 'approved', reason: 'protocol v2 Bundle verified and desired' });
  const result = await executeVaultBoundCloudRequest(
    { path: '/api/v1/plugin-marketplace/packages/qa-plugin/install', method: 'POST', body: installBody },
    h.dependencies,
  );
  assert.equal(result.status, 202);
  assert.equal(result.body.status, 'approved');
  assert.deepEqual(h.paths, [
    '/api/v1/workspace-context',
    '/api/v1/plugin-marketplace/packages/qa-plugin/install',
  ]);
});
test('cloud marketplace install rejects scope drift, extra fields, and malformed bodies', async () => {
  for (const body of [
    { ...installBody, tenant_id: 'tenant-2' },
    { ...installBody, plugin_id: 'other-plugin' },
    { ...installBody, arbitrary: true },
    { ...installBody, approved_permissions: 'tools.execute' },
    { ...installBody, tenant_admin_approved: 'yes' },
    { ...installBody, manifest: null },
  ]) {
    const h = harness(202, {});
    await assert.rejects(
      executeVaultBoundCloudRequest(
        { path: '/api/v1/plugin-marketplace/packages/qa-plugin/install', method: 'POST', body },
        h.dependencies,
      ),
      /not allowed|scope mismatch/,
    );
  }
});
test('cloud marketplace approve and revoke stay scoped and exact', async () => {
  const approve = harness(200, { plugin_id: 'qa-plugin', version: '1.0.0', status: 'approved', granted_permissions: ['tools.execute'] });
  const approveResult = await executeVaultBoundCloudRequest(
    { path: '/api/v1/plugin-marketplace/packages/qa-plugin/approve', method: 'POST', body: { version: '1.0.0', tenant_id: 'tenant-1', approved_permissions: ['tools.execute'] } },
    approve.dependencies,
  );
  assert.equal(approveResult.status, 200);
  assert.deepEqual(approveResult.body.granted_permissions, ['tools.execute']);

  const revoke = harness(200, { plugin_id: 'qa-plugin', revoked_versions: ['1.0.0'], revoked_permissions: 1 });
  const revokeResult = await executeVaultBoundCloudRequest(
    { path: '/api/v1/plugin-marketplace/packages/qa-plugin/revoke', method: 'POST', body: { reason: 'publisher compromised' } },
    revoke.dependencies,
  );
  assert.equal(revokeResult.status, 200);
  assert.deepEqual(revokeResult.body.revoked_versions, ['1.0.0']);

  const badApprove = harness();
  await assert.rejects(
    executeVaultBoundCloudRequest(
      { path: '/api/v1/plugin-marketplace/packages/qa-plugin/approve', method: 'POST', body: { version: '1.0.0', tenant_id: 'tenant-2', approved_permissions: [] } },
      badApprove.dependencies,
    ),
    /tenant scope mismatch/,
  );
  const badRevoke = harness();
  await assert.rejects(
    executeVaultBoundCloudRequest(
      { path: '/api/v1/plugin-marketplace/packages/qa-plugin/revoke', method: 'POST', body: { reason: '' } },
      badRevoke.dependencies,
    ),
    /endpoint is not allowed/,
  );
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
