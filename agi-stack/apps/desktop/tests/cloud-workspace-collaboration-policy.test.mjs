import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { authorizeCloudProductEndpoint } = require('/tmp/agistack-desktop-test-dist/electron/main/cloudProductEndpointPolicy.js');
const { executeVaultBoundCloudRequest } = require('/tmp/agistack-desktop-test-dist/electron/main/cloudRequestPolicy.js');
const base = '/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1';
const paths = [
  `${base}/objectives`, `${base}/agents`, `${base}/members`, `${base}/genes`,
  `${base}/blackboard/posts`, `${base}/blackboard/posts/post-1/replies`,
  `${base}/blackboard/execution-diagnostics`, `${base}/blackboard/files?parent_path=%2F`,
  '/api/v1/workspaces/workspace-1/topology/nodes',
  '/api/v1/workspaces/workspace-1/topology/edges',
];
for (const path of paths) {
  test(`authorizes only the collaboration read contract: ${path}`, () => {
    const target = new URL(path, 'https://cloud.memstack.test');
    const allowed = authorizeCloudProductEndpoint({ method: 'GET' }, target);
    assert.equal(allowed?.kind, 'workspace');
    assert.equal(allowed.workspaceId, 'workspace-1');
    assert.equal(authorizeCloudProductEndpoint({ method: 'GET', body: {} }, target), null);
    for (const method of ['PUT', 'PATCH']) {
      assert.equal(authorizeCloudProductEndpoint({ method }, target), null);
    }
    target.searchParams.set('unexpected', '1');
    assert.equal(authorizeCloudProductEndpoint({ method: 'GET' }, target), null);
  });
}
test('full desktop does not transport legacy collaboration HTTP', async () => {
  const calls = [];
  const dependencies = {
    loadTrustedSession: async () => ({
      version: 1, api_base_url: 'https://cloud.memstack.test', runtime_mode: 'cloud',
      credential_kind: 'cloud_bearer', credential: 'test-only', expires_at: '2099-08-10T00:00:00Z',
    }),
    async fetch(url) {
      calls.push(new URL(url).pathname);
      return new Response('{}', { headers: { 'content-type': 'application/json' } });
    },
  };
  await assert.rejects(
    executeVaultBoundCloudRequest({ method: 'GET', path: `${base}/objectives` }, dependencies),
    /cloud request endpoint is not allowed/,
  );
  assert.deepEqual(calls, []);
});

const canonicalMutation = {
  method: 'POST',
  body: {
    contract_version: '2.0.0', surface: 'goals', action: 'create_objective',
    expected_revision: 8, idempotency_key: 'qa-mutation-0001', payload: { title: 'QA objective' },
  },
  mutation: { expected_revision: 8, idempotency_key: 'qa-mutation-0001' },
};
const mutationTarget = new URL(`${base}/collaboration/mutations`, 'https://cloud.memstack.test');
test('accepts the canonical collaboration mutation envelope', () => {
  assert.equal(authorizeCloudProductEndpoint(canonicalMutation, mutationTarget)?.workspaceId, 'workspace-1');
});
for (const [name, change] of [
  ['wrong method', { method: 'PATCH' }],
  ['missing mutation proof', { mutation: undefined }],
  ['mismatched revision', { mutation: { ...canonicalMutation.mutation, expected_revision: 9 } }],
  ['mismatched idempotency', { mutation: { ...canonicalMutation.mutation, idempotency_key: 'other-key' } }],
  ['extra envelope field', { body: { ...canonicalMutation.body, tenant_id: 'tenant-2' } }],
  ['wrong version', { body: { ...canonicalMutation.body, contract_version: '1.0.0' } }],
  ['unknown action', { body: { ...canonicalMutation.body, action: 'erase_workspace' } }],
  ['wrong surface action', { body: { ...canonicalMutation.body, surface: 'members' } }],
  ['negative revision', { body: { ...canonicalMutation.body, expected_revision: -1 } }],
  ['array payload', { body: { ...canonicalMutation.body, payload: [] } }],
  ['payload scope override', { body: { ...canonicalMutation.body, payload: { project_id: 'project-2' } } }],
]) {
  test(`canonical mutation rejects ${name}`, () => {
    assert.equal(authorizeCloudProductEndpoint({ ...canonicalMutation, ...change }, mutationTarget), null);
  });
}
test('canonical mutation rejects extra query or path segments', () => {
  for (const suffix of ['?force=true', '/extra']) {
    assert.equal(authorizeCloudProductEndpoint(canonicalMutation, new URL(mutationTarget.href + suffix)), null);
  }
});
test('full desktop does not forward legacy collaboration mutations', async () => {
  await assert.rejects(
    executeVaultBoundCloudRequest({ ...canonicalMutation, path: mutationTarget.pathname }, {
      async loadTrustedSession() {
        throw new Error('collaboration HTTP must be rejected before the vault');
      },
      async fetch() {
        throw new Error('collaboration HTTP must not reach the network');
      },
    }),
    /cloud request endpoint is not allowed/,
  );
});
