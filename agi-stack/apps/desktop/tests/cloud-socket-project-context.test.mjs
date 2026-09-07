import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const { authorizeVaultBoundCloudSocket } = require('/tmp/agistack-desktop-test-dist/electron/main/cloudSocketPolicy.js');
const session = { version: 1, api_base_url: 'https://cloud.memstack.test', runtime_mode: 'cloud', credential_kind: 'cloud_bearer', credential: 'vault-test-secret', expires_at: '2099-01-01T00:00:00Z' };
const input = { kind: 'agent', url: 'wss://cloud.memstack.test/api/v1/agent/ws?session_id=desktop-session-1', scope: { tenant_id: 't1', project_id: 'p1', workspace_id: 'w1', conversation_id: null } };
const context = { tenant_id: 't1', project_id: 'p1', revision: 0 };
const detail = { id: 'w1', tenant_id: 't1', project_id: 'p1' };
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
function deps(workspace = detail, status = 200, observed = context) {
  const paths = [];
  return { paths, loadTrustedSession: async () => session, async fetch(url, init) {
    paths.push(new URL(url).pathname);
    assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer vault-test-secret');
    if (url.endsWith('/workspace-context')) return json({ context: observed });
    assert.equal(new URL(url).pathname, '/api/v1/tenants/t1/projects/p1/workspaces/w1');
    return json(workspace, status);
  } };
}
test('socket uses server workspace proof when context selects only a project', async () => {
  const dependencies = deps();
  const result = await authorizeVaultBoundCloudSocket(input, dependencies);
  assert.equal(result.scope.workspace_id, 'w1');
  assert.equal(dependencies.paths.length, 2);
});
for (const [name, workspace, status] of [
  ['wrong id', { ...detail, id: 'w2' }, 200], ['foreign project', { ...detail, project_id: 'p2' }, 200],
  ['foreign tenant', { ...detail, tenant_id: 't2' }, 200], ['missing scope', { id: 'w1' }, 200], ['denied', {}, 403],
]) test(`socket rejects ${name} proof`, async () => {
  await assert.rejects(authorizeVaultBoundCloudSocket(input, deps(workspace, status)), /workspace scope/);
});
test('socket does not probe an explicitly different workspace', async () => {
  const dependencies = deps(detail, 200, { ...context, workspace_id: 'w2' });
  await assert.rejects(authorizeVaultBoundCloudSocket(input, dependencies), /workspace scope mismatch/);
  assert.equal(dependencies.paths.length, 1);
});
