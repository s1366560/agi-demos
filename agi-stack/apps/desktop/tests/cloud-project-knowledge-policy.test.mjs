import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { executeVaultBoundCloudRequest } = require(
  '/tmp/agistack-desktop-test-dist/electron/main/cloudRequestPolicy.js',
);

const memoryPath = '/api/v1/memories/?project_id=project-1&page=1&page_size=50';
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
    async fetch(url, init) {
      const target = new URL(url);
      requests.push(target.pathname + target.search);
      assert.equal(
        new Headers(init.headers).get('Authorization'),
        `Bearer ${trustedSession.credential}`,
      );
      return new Response(JSON.stringify(target.pathname === '/api/v1/workspace-context'
        ? { context: { tenant_id: 'tenant-1', project_id: 'project-1', revision: 7 } }
        : { memories: [], total: 0, page: 1, page_size: 50 }), {
        headers: { 'Content-Type': 'application/json' },
      });
    },
  };
}

test('Cloud memories list observes trusted project scope before its exact request', async () => {
  const requests = [];
  const result = await executeVaultBoundCloudRequest(
    { method: 'GET', path: memoryPath }, dependencies(requests),
  );
  assert.equal(result.status, 200);
  assert.deepEqual(requests, ['/api/v1/workspace-context', memoryPath]);
  assert.equal(JSON.stringify(result).includes(trustedSession.credential), false);
});

test('Cloud memories rejects another project before requesting memory data', async () => {
  const requests = [];
  await assert.rejects(
    () => executeVaultBoundCloudRequest(
      { method: 'GET', path: memoryPath.replace('project-1', 'project-2') },
      dependencies(requests),
    ),
    /cloud request project scope mismatch/u,
  );
  assert.deepEqual(requests, ['/api/v1/workspace-context']);
});

for (const [name, input] of [
  ['wrong method', { method: 'POST', path: memoryPath }],
  ['missing slash', { method: 'GET', path: memoryPath.replace('/?', '?') }],
  ['extra tenant scope', { method: 'GET', path: `${memoryPath}&tenant_id=tenant-2` }],
  ['duplicate project', { method: 'GET', path: `${memoryPath}&project_id=project-2` }],
  ['extra parameter', { method: 'GET', path: `${memoryPath}&include_private=true` }],
  ['different page', { method: 'GET', path: memoryPath.replace('page=1', 'page=2') }],
  ['different page size', { method: 'GET', path: memoryPath.replace('page_size=50', 'page_size=100') }],
  ['empty project', { method: 'GET', path: memoryPath.replace('project-1', '') }],
  ['read body', { method: 'GET', path: memoryPath, body: { project_id: 'project-2' } }],
]) {
  test(`Cloud memories rejects ${name} without network access`, async () => {
    const requests = [];
    await assert.rejects(
      () => executeVaultBoundCloudRequest(input, dependencies(requests)),
    );
    assert.deepEqual(requests, []);
  });
}

for (const path of [
  '/api/v1/graph/entities/?tenant_id=tenant-1&project_id=project-1&limit=50&offset=0',
  '/api/v1/graph/entities/types?tenant_id=tenant-1&project_id=project-1',
  '/api/v1/graph/communities/?tenant_id=tenant-1&project_id=project-1&limit=50&offset=0',
  '/api/v1/graph/memory/graph?tenant_id=tenant-1&project_id=project-1&limit=1000',
]) {
  test(`Cloud knowledge preserves the current scoped client request ${path}`, async () => {
    const requests = [];
    await executeVaultBoundCloudRequest({ method: 'GET', path }, dependencies(requests));
    assert.deepEqual(requests, ['/api/v1/workspace-context', path]);
    for (const invalid of [path.replace('tenant-1', 'tenant-2'), path.replace('project-1', 'project-2')]) {
      const rejectedRequests = [];
      await assert.rejects(
        () => executeVaultBoundCloudRequest({ method: 'GET', path: invalid }, dependencies(rejectedRequests)),
        /cloud request (tenant|project) scope mismatch/u,
      );
      assert.deepEqual(rejectedRequests, ['/api/v1/workspace-context']);
    }
  });
}

for (const path of [
  '/api/v1/projects/project-1/stats',
  memoryPath.replace('page_size=50', 'page_size=5'),
]) {
  test(`Cloud overview permits exact scoped read ${path}`, async () => {
    const requests = [];
    await executeVaultBoundCloudRequest({ method: 'GET', path }, dependencies(requests));
    assert.deepEqual(requests, ['/api/v1/workspace-context', path]);
    const crossScope = [];
    await assert.rejects(() => executeVaultBoundCloudRequest(
      { method: 'GET', path: path.replace('project-1', 'project-2') }, dependencies(crossScope),
    ), /cloud request project scope mismatch/u);
    assert.deepEqual(crossScope, ['/api/v1/workspace-context']);
  });
}
for (const input of [
  { method: 'GET', path: '/api/v1/projects/project-1/stats?tenant_id=tenant-1' },
  { method: 'GET', path: '/api/v1/projects/project-1/stats/' },
  { method: 'GET', path: '/api/v1/projects/project-1/stats', body: {} },
  { method: 'POST', path: '/api/v1/projects/project-1/stats' },
  { method: 'GET', path: memoryPath.replace('page_size=50', 'page_size=05') },
]) {
  test(`Cloud overview rejects non-contract read ${JSON.stringify(input)}`, async () => {
    const requests = [];
    await assert.rejects(() => executeVaultBoundCloudRequest(input, dependencies(requests)));
    assert.deepEqual(requests, []);
  });
}
