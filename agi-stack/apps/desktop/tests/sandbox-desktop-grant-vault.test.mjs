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
    (name) => (name.startsWith('.') ? load(new URL(`${name}.ts`, url)) : require(name)),
    module,
    module.exports,
  );
  return module.exports;
}
const { authorizeVaultBoundSandboxDesktopGrant } = load(
  new URL('../electron/main/cloudRequestPolicy.ts', import.meta.url),
);
const scope = { tenantId: 'tenant-one', projectId: 'project-one' };
const credential = 'synthetic-kasm-test-credential';
function fixture(
  context = { tenant_id: 'tenant-one', project_id: 'project-one', workspace_id: null },
) {
  const calls = [];
  let reads = 0;
  return {
    calls,
    get reads() {
      return reads;
    },
    dependencies: {
      loadTrustedSession: async () => {
        reads++;
        return {
          version: 1,
          api_base_url: 'https://cloud.example',
          runtime_mode: 'cloud',
          credential_kind: 'cloud_bearer',
          credential,
          expires_at: null,
        };
      },
      fetch: async (url, init) => {
        calls.push({ url, init });
        return new Response(JSON.stringify({ context }), {
          headers: { 'content-type': 'application/json' },
        });
      },
    },
  };
}
test('Kasm main-only authorization uses vault origin and observed scope with omitted cookies', async () => {
  const f = fixture();
  const result = await authorizeVaultBoundSandboxDesktopGrant(scope, f.dependencies);
  assert.deepEqual(result, { apiBaseUrl: 'https://cloud.example', credential, expiresAt: null });
  assert.equal(f.calls.length, 1);
  assert.equal(f.calls[0].url, 'https://cloud.example/api/v1/workspace-context');
  assert.equal(f.calls[0].init.credentials, 'omit');
  assert.equal(new Headers(f.calls[0].init.headers).get('authorization'), `Bearer ${credential}`);
});
test('Kasm authorization rejects cross-tenant and cross-project grants after live observation', async () => {
  for (const context of [
    { tenant_id: 'other', project_id: 'project-one', workspace_id: null },
    { tenant_id: 'tenant-one', project_id: 'other', workspace_id: null },
  ]) {
    const f = fixture(context);
    await assert.rejects(
      authorizeVaultBoundSandboxDesktopGrant(scope, f.dependencies),
      /scope mismatch/,
    );
    assert.equal(f.calls.length, 1);
  }
});
test('Kasm authorization validates scope before vault access and discards cancelled observations', async () => {
  const f = fixture();
  await assert.rejects(
    authorizeVaultBoundSandboxDesktopGrant({ ...scope, projectId: '' }, f.dependencies),
  );
  assert.equal(f.reads, 0);
  const abort = new AbortController();
  const f2 = fixture();
  const pending = authorizeVaultBoundSandboxDesktopGrant(scope, {
    ...f2.dependencies,
    signal: abort.signal,
    fetch: async () => {
      abort.abort();
      return new Response(
        JSON.stringify({
          context: { tenant_id: 'tenant-one', project_id: 'project-one', workspace_id: null },
        }),
      );
    },
  });
  await assert.rejects(pending, { name: 'AbortError' });
});
