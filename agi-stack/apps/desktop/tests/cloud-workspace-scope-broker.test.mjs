import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { executeVaultBoundCloudRequest } = require(
  '/tmp/agistack-desktop-test-dist/electron/main/cloudRequestPolicy.js',
);
const session = Object.freeze({
  version: 1, api_base_url: 'https://cloud.memstack.test', runtime_mode: 'cloud',
  credential_kind: 'cloud_bearer', credential: 'vault-only-test-secret',
  expires_at: '2099-08-10T00:00:00Z',
});
const workspacePath = '/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1';
const context = { tenant_id: 'tenant-1', project_id: 'project-1', revision: 0 };
const workspace = { id: 'workspace-1', tenant_id: 'tenant-1', project_id: 'project-1' };
const response = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
});
function dependencies(observed = context, detail = workspace, status = 200) {
  const paths = [];
  return {
    paths,
    loadTrustedSession: async () => session,
    async fetch(url, init) {
      const path = new URL(url).pathname;
      paths.push(path);
      assert.equal(new Headers(init.headers).get('authorization'), 'Bearer vault-only-test-secret');
      if (path === '/api/v1/workspace-context') return response({ context: observed });
      if (path === workspacePath) return response(detail, status);
      assert.equal(path, workspacePath + '/members');
      return response([]);
    },
  };
}
test('project-only cloud context authorizes the requested workspace through server detail', async () => {
  const deps = dependencies();
  const result = await executeVaultBoundCloudRequest({
    method: 'GET', path: workspacePath + '/members?limit=50&offset=0',
  }, deps);
  assert.deepEqual(result, { status: 200, body: [] });
  assert.deepEqual(deps.paths, ['/api/v1/workspace-context', workspacePath, workspacePath + '/members']);
});
for (const [name, detail, status] of [
  ['foreign project', { ...workspace, project_id: 'project-2' }, 200],
  ['foreign tenant', { ...workspace, tenant_id: 'tenant-2' }, 200],
  ['forged workspace', { ...workspace, id: 'workspace-2' }, 200],
  ['missing fields', { id: 'workspace-1' }, 200],
  ['forbidden', {}, 403],
]) {
  test(`workspace proof fails closed for ${name}`, async () => {
    const deps = dependencies(context, detail, status);
    await assert.rejects(executeVaultBoundCloudRequest({
      method: 'GET', path: workspacePath + '/members?limit=50&offset=0',
    }, deps), /workspace scope/);
    assert.deepEqual(deps.paths, ['/api/v1/workspace-context', workspacePath]);
  });
}
test('explicit workspace mismatch remains rejected without probing another workspace', async () => {
  const deps = dependencies({ ...context, workspace_id: 'workspace-2' });
  await assert.rejects(executeVaultBoundCloudRequest({
    method: 'GET', path: workspacePath + '/members?limit=50&offset=0',
  }, deps), /workspace scope mismatch/);
  assert.deepEqual(deps.paths, ['/api/v1/workspace-context']);
});
test('cross-project workspace path is rejected before probing', async () => {
  const deps = dependencies();
  await assert.rejects(executeVaultBoundCloudRequest({
    method: 'GET', path: workspacePath.replace('project-1', 'project-2') + '/members?limit=50&offset=0',
  }, deps), /project scope mismatch/);
  assert.deepEqual(deps.paths, ['/api/v1/workspace-context']);
});
