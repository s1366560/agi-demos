import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const { authorizeCloudProductEndpoint } = require('/tmp/agistack-desktop-test-dist/electron/main/cloudProductEndpointPolicy.js');
const root = 'https://desktop.invalid/api/v1/workspaces/w1/autonomy/attentions';
const mutation = { expected_revision: 2, idempotency_key: 'attention-resolve-test-key' };
for (const [method, suffix, metadata] of [['GET', '', {}], ['POST', '/a1/retry', {}], ['POST', '/a1/resolve', { mutation }]]) {
  test(`allows exact attention ${method} ${suffix}`, () => {
    assert.deepEqual(authorizeCloudProductEndpoint({ method, ...metadata }, new URL(root + suffix)), {
      kind: 'workspace', tenantId: null, projectId: null, workspaceId: 'w1',
    });
  });
}
for (const [method, suffix, metadata] of [['POST', '', {}], ['GET', '/a1/retry', {}], ['POST', '/a1/resolve', {}], ['POST', '/a1/resolve', { mutation: { kind: 'idempotency-only', idempotency_key: 'key' } }], ['GET', '?tenant_id=other', {}], ['POST', '/a1/delete', {}], ['GET', '', { body: { arbitrary: true } }]]) {
  test(`rejects unsupported attention request ${method} ${suffix} ${JSON.stringify(metadata)}`, () => {
    assert.equal(authorizeCloudProductEndpoint({ method, ...metadata }, new URL(root + suffix)), null);
  });
}

for (const metadata of [{ form: [{ kind: 'text', name: 'arbitrary', value: 'x' }] }, { response: { kind: 'binary', max_bytes: 1024 } }]) {
  test(`rejects attention transport metadata ${JSON.stringify(metadata)}`, () => {
    assert.equal(authorizeCloudProductEndpoint({ method: 'GET', ...metadata }, new URL(root)), null);
  });
}
