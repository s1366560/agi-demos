import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const ts = require('typescript');
const cache = new Map();
function load(url) {
  if (cache.has(url.href)) return cache.get(url.href);
  const module = { exports: {} };
  cache.set(url.href, module.exports);
  const code = ts.transpileModule(readFileSync(url, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  new Function('require', 'module', 'exports', code)(
    (name) => name.startsWith('.') ? load(new URL(`${name}.ts`, url)) : require(name), module, module.exports,
  );
  return module.exports;
}
const { executeVaultBoundCloudRequest } = load(new URL('../electron/main/cloudRequestPolicy.ts', import.meta.url));
const path = '/api/v1/agent/conversations/conversation-one/mode?project_id=project-one';
function fixture() {
  const calls = [];
  let sessionReads = 0;
  return {
    calls,
    get sessionReads() { return sessionReads; },
    request(body, overrides = {}) {
      return executeVaultBoundCloudRequest({ path, method: 'PATCH', body, ...overrides }, {
        loadTrustedSession: async () => {
          sessionReads++;
          return { version: 1, api_base_url: 'https://cloud.example', runtime_mode: 'cloud', credential_kind: 'cloud_bearer', credential: 'synthetic-mode-test-token', expires_at: null };
        },
        fetch: async (url, init) => {
          const target = new URL(url);
          calls.push({ path: target.pathname + target.search, method: init.method, body: init.body });
          const payload = target.pathname === '/api/v1/workspace-context'
            ? { context: { tenant_id: 'tenant-one', project_id: 'project-one', workspace_id: 'workspace-one', revision: 1 } }
            : { id: 'conversation-one', tenant_id: 'tenant-one', project_id: 'project-one', workspace_id: body?.workspace_id ?? null };
          return new Response(JSON.stringify(payload), { status: 200, headers: { 'content-type': 'application/json' } });
        },
      });
    },
  };
}
test('native conversation mode preserves Cloud workspace binding and explicit unlink without extra preflight', async () => {
  for (const body of [{ workspace_id: 'workspace-one' }, { workspace_id: null }]) {
    const f = fixture(); assert.equal((await f.request(body)).status, 200);
    assert.deepEqual(f.calls.map((c) => c.path), ['/api/v1/workspace-context', path]);
    assert.equal(f.calls[1].method, 'PATCH');
    assert.deepEqual(JSON.parse(f.calls[1].body), body);
  }
});
test('native conversation mode retains valid Cloud collaboration and task-link fields', async () => {
  for (const mode of ['single_agent', 'multi_agent_shared', 'multi_agent_isolated', 'autonomous', null]) {
    const f = fixture();
    const body = { conversation_mode: mode, workspace_id: 'workspace-one', linked_workspace_task_id: 'task-one' };
    assert.equal((await f.request(body)).status, 200);
    assert.deepEqual(JSON.parse(f.calls[1].body), body);
  }
  for (const body of [{}, { linked_workspace_task_id: null }]) assert.equal((await fixture().request(body)).status, 200);
});
test('native conversation mode rejects unsupported fields and malformed values before reading credentials', async () => {
  for (const body of [undefined, { capability_mode: 'code' }, { workspace_id: 'workspace-one', permission_mode: 'full_access' }, { conversation_mode: 'unknown' }, { conversation_mode: false }, { workspace_id: 7 }, { workspace_id: '' }, { linked_workspace_task_id: [] }, { linked_workspace_task_id: ' task ' }]) {
    const f = fixture(); await assert.rejects(f.request(body), /endpoint is not allowed/);
    assert.equal(f.sessionReads, 0); assert.equal(f.calls.length, 0);
  }
});
test('native conversation mode rejects query project mismatch before PATCH delivery', async () => {
  const f = fixture();
  await assert.rejects(f.request({ workspace_id: 'workspace-one' }, { path: path.replace('project-one', 'project-other') }), /scope mismatch/);
  assert.deepEqual(f.calls.map((c) => c.path), ['/api/v1/workspace-context']);
});
test('native conversation mode rejects unrelated mutation or binary transport envelopes', async () => {
  for (const extra of [{ mutation: { idempotency_key: 'key' } }, { response: { kind: 'binary', max_bytes: 10 } }, { method: 'POST' }]) {
    const f = fixture(); await assert.rejects(f.request({ workspace_id: 'workspace-one' }, extra));
    assert.equal(f.calls.length, 0);
  }
});
