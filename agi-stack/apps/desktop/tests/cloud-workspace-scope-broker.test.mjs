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
test('full desktop does not admit legacy workspace HTTP just because the shell is full', async () => {
  const deps = dependencies();
  await assert.rejects(executeVaultBoundCloudRequest({
    method: 'GET', path: workspacePath + '/members?limit=50&offset=0',
  }, deps), /cloud request endpoint is not allowed/);
  assert.deepEqual(deps.paths, []);
  const foreign = dependencies();
  await assert.rejects(executeVaultBoundCloudRequest({
    method: 'GET',
    path: workspacePath.replace('project-1', 'project-2') + '/members?limit=50&offset=0',
  }, foreign), /cloud request endpoint is not allowed/);
  assert.deepEqual(foreign.paths, []);
});

test('a signed-in account selects its first project or another tenant through its membership catalog', async () => {
  for (const observed of [null, context]) {
    for (const visible of [false, true]) {
      const switched = [];
      const deps = {
        loadTrustedSession: async () => session,
        async fetch(url) {
          const path = new URL(url).pathname;
          if (path === '/api/v1/workspace-context')
            return observed ? response({ context: observed }) :
              response({ detail: { code: 'workspace_context_unavailable' } }, 404);
          if (path === '/api/v1/project-packages/projects/')
            return response(visible ? [{ tenant_id: 'tenant-2', project_id: 'project-2' }] : []);
          switched.push(path);
          return response({ changed: true });
        },
      };
      const path = '/api/v1/workspace-context/switch';
      const change = executeVaultBoundCloudRequest({method:'POST',path,body:{
        tenant_id:'tenant-2', project_id:'project-2', expected_revision:0,idempotency_key:'reviewed-switch',
      }}, deps);
      if (visible) assert.equal((await change).status, 200);
      else await assert.rejects(change,/scope mismatch/);
      assert.deepEqual(switched, visible ? [path] : []);
    }
  }
});
