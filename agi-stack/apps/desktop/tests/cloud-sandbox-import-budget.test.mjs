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
    fileName: url.pathname,
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText;
  new Function('require', 'module', 'exports', code)(
    (name) => (name.startsWith('.') ? load(new URL(`${name}.ts`, url)) : require(name)),
    module,
    module.exports,
  );
  return module.exports;
}
const { executeVaultBoundCloudRequest } = load(
  new URL('../electron/main/cloudRequestPolicy.ts', import.meta.url),
);
const request = (size) => ({
  path: '/api/v1/projects/project-one/sandbox/execute',
  method: 'POST',
  body: {
    tool_name: 'import_file',
    arguments: {
      filename: 'upload.txt',
      content_base64: Buffer.alloc(size, 65).toString('base64'),
      destination: '/workspace/input',
      overwrite: true,
    },
    timeout: 60,
  },
});
function dependencies(projectId = 'project-one') {
  const calls = [];
  let sessions = 0;
  return {
    calls,
    get sessions() {
      return sessions;
    },
    async loadTrustedSession() {
      sessions++;
      return {
        version: 1,
        api_base_url: 'https://cloud.example',
        runtime_mode: 'cloud',
        credential_kind: 'cloud_bearer',
        credential: 'synthetic-vault-token',
        expires_at: '2099-01-01T00:00:00Z',
      };
    },
    async fetch(url, init) {
      calls.push({ path: new URL(url).pathname, init });
      return new Response(
        JSON.stringify(
          new URL(url).pathname === '/api/v1/workspace-context'
            ? {
                context: {
                  tenant_id: 'tenant-one',
                  project_id: projectId,
                  workspace_id: 'workspace-one',
                  revision: 1,
                },
              }
            : { success: true },
        ),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    },
  };
}
for (const size of [400000, 16 * 1024 * 1024]) {
  test(`native broker accepts exact import_file payload of ${size} decoded bytes`, async () => {
    const deps = dependencies();
    const input = request(size);
    const result = await executeVaultBoundCloudRequest(input, deps);
    assert.equal(result.status, 200);
    assert.equal(deps.sessions, 1);
    assert.equal(deps.calls.length, 2);
    assert.equal(deps.calls[0].path, '/api/v1/workspace-context');
    assert.equal(deps.calls[1].path, input.path);
    const body = JSON.parse(deps.calls[1].init.body);
    assert.equal(Buffer.from(body.arguments.content_base64, 'base64').length, size);
    assert.equal(body.arguments.filename, 'upload.txt');
  });
}
test('oversized decoded file is rejected before session or network access', async () => {
  const deps = dependencies();
  await assert.rejects(
    executeVaultBoundCloudRequest(request(16 * 1024 * 1024 + 1), deps),
    /body is too large/,
  );
  assert.equal(deps.sessions, 0);
  assert.equal(deps.calls.length, 0);
});
for (const [label, change] of [
  [
    'another tool',
    (v) => {
      v.body.tool_name = 'execute_command';
    },
  ],
  [
    'another route',
    (v) => {
      v.path = '/api/v1/projects/project-one/sandbox/other';
    },
  ],
  [
    'query',
    (v) => {
      v.path += '?unexpected=1';
    },
  ],
  [
    'another destination',
    (v) => {
      v.body.arguments.destination = '/workspace';
    },
  ],
  [
    'overwrite false',
    (v) => {
      v.body.arguments.overwrite = false;
    },
  ],
  [
    'traversal filename',
    (v) => {
      v.body.arguments.filename = '../escape';
    },
  ],
  [
    'extra argument',
    (v) => {
      v.body.arguments.command = 'unexpected';
    },
  ],
  [
    'extra body field',
    (v) => {
      v.body.extra = true;
    },
  ],
  [
    'low timeout',
    (v) => {
      v.body.timeout = 59;
    },
  ],
  [
    'high timeout',
    (v) => {
      v.body.timeout = 301;
    },
  ],
  [
    'noncanonical base64',
    (v) => {
      v.body.arguments.content_base64 = v.body.arguments.content_base64.slice(0, -4) + 'YR==';
    },
  ],
  [
    'base64 whitespace',
    (v) => {
      v.body.arguments.content_base64 += '\n';
    },
  ],
]) {
  test(`the large-body exception rejects ${label}`, async () => {
    const input = request(400000);
    change(input);
    const deps = dependencies();
    await assert.rejects(executeVaultBoundCloudRequest(input, deps), /body is too large/);
    assert.equal(deps.sessions, 0);
    assert.equal(deps.calls.length, 0);
  });
}
test('large valid upload still obeys the observed project scope', async () => {
  const deps = dependencies('project-other');
  await assert.rejects(executeVaultBoundCloudRequest(request(400000), deps), /scope/);
  assert.equal(deps.calls.length, 1);
});
test('ordinary sandbox requests retain the 512 KiB budget', async () => {
  const input = request(1);
  input.body = {
    tool_name: 'execute_command',
    arguments: { text: 'x'.repeat(512 * 1024) },
    timeout: 60,
  };
  const deps = dependencies();
  await assert.rejects(executeVaultBoundCloudRequest(input, deps), /body is too large/);
  assert.equal(deps.sessions, 0);
});
