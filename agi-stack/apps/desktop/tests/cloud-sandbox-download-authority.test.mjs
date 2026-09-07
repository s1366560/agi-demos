import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';
const require = createRequire(import.meta.url);
const {
  executeVaultBoundCloudRequest,
} = require('/tmp/agistack-desktop-test-dist/electron/main/cloudRequestPolicy.js');
const {
  desktopApiFetch,
} = require('/tmp/agistack-desktop-test-dist/src/api/cloudRequestBroker.js');
const originalWindow = globalThis.window;
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.window = originalWindow;
  globalThis.fetch = originalFetch;
});
const path =
  '/api/v1/projects/project-one/sandbox/files/download?path=%2Fworkspace%2Finput%2Fnote.txt&max_bytes=1024';
const config = {
  apiBaseUrl: 'https://cloud.example',
  deviceAuthorizationBaseUrl: 'https://cloud.example',
  apiKey: '',
  localApiToken: '',
  tenantId: 'tenant-one',
  projectId: 'project-one',
  workspaceId: 'workspace-one',
  mode: 'cloud',
  workspaceRoot: '',
};
const authorityHeaders = {
  'x-memstack-file-contract-version': '1',
  'x-memstack-file-authority': 'sandbox',
  'x-memstack-file-isolation': 'isolated',
};
function install(headers, projectId = 'project-one') {
  const calls = [];
  globalThis.fetch = () => {
    throw new Error('renderer fallback is prohibited');
  };
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        invoke(command, input) {
          assert.equal(command, 'cloud_request');
          return executeVaultBoundCloudRequest(input.request, {
            async loadTrustedSession() {
              return {
                version: 1,
                api_base_url: config.apiBaseUrl,
                runtime_mode: 'cloud',
                credential_kind: 'cloud_bearer',
                credential: 'synthetic-vault-token',
                expires_at: '2099-01-01T00:00:00Z',
              };
            },
            async fetch(url) {
              const target = new URL(url);
              calls.push(target.pathname);
              if (target.pathname === '/api/v1/workspace-context') {
                return new Response(
                  JSON.stringify({
                    context: {
                      tenant_id: 'tenant-one',
                      project_id: projectId,
                      workspace_id: 'workspace-one',
                      revision: 1,
                    },
                  }),
                  { headers: { 'content-type': 'application/json' } },
                );
              }
              return new Response('download contents', {
                headers: {
                  'content-type': 'text/plain',
                  'content-disposition': 'attachment; filename="note.txt"',
                  ...headers,
                },
              });
            },
          });
        },
      },
    },
  };
  return calls;
}
const download = () =>
  desktopApiFetch(config, path, {}, { responseType: 'binary', maxBytes: 1024 });

test('real vault broker preserves sandbox authority headers through renderer reconstruction', async () => {
  const calls = install(authorityHeaders);
  const response = await download();
  for (const [key, value] of Object.entries(authorityHeaders))
    assert.equal(response.headers.get(key), value);
  assert.equal(await response.text(), 'download contents');
  assert.equal(response.headers.get('content-type'), 'text/plain');
  assert.equal(response.headers.get('content-disposition'), 'attachment; filename="note.txt"');
  assert.deepEqual(calls, [
    '/api/v1/workspace-context',
    '/api/v1/projects/project-one/sandbox/files/download',
  ]);
});
for (const [label, headers] of [
  ['missing', {}],
  ['wrong version', { ...authorityHeaders, 'x-memstack-file-contract-version': '2' }],
  ['native workspace', { ...authorityHeaders, 'x-memstack-file-authority': 'native_workspace' }],
  ['nonisolated', { ...authorityHeaders, 'x-memstack-file-isolation': 'not_applicable' }],
]) {
  test(`native broker rejects ${label} download authority instead of fabricating it`, async () => {
    install(headers);
    await assert.rejects(download(), /file authority is invalid/);
  });
}
test('download retains observed project authorization before fetching bytes', async () => {
  const calls = install(authorityHeaders, 'other-project');
  await assert.rejects(download(), /scope|project/);
  assert.deepEqual(calls, ['/api/v1/workspace-context']);
});
test('renderer rejects missing or forged sandbox authority and forbids it on unrelated binary responses', async () => {
  const body = {
    kind: 'binary',
    bytes_base64: 'YQ==',
    size_bytes: 1,
    mime_type: 'text/plain',
    filename: 'note.txt',
  };
  const invoke = async () => ({ status: 200, body });
  globalThis.window = { __MEMSTACK_DESKTOP__: { core: { invoke } } };
  await assert.rejects(download(), /file authority is invalid/);
  body.file_authority = {
    contract_version: 1,
    authority: 'native_workspace',
    isolation: 'not_applicable',
  };
  await assert.rejects(download(), /file authority is invalid/);
  body.file_authority = { contract_version: 1, authority: 'sandbox', isolation: 'isolated' };
  await assert.rejects(
    desktopApiFetch(
      config,
      '/api/v1/artifacts/a/content/bytes',
      {},
      { responseType: 'binary', maxBytes: 1024 },
    ),
    /binary_response_contract_invalid/,
  );
  delete body.file_authority;
  const ordinary = await desktopApiFetch(
    config,
    '/api/v1/artifacts/a/content/bytes',
    {},
    { responseType: 'binary', maxBytes: 1024 },
  );
  assert.equal(ordinary.headers.has('x-memstack-file-authority'), false);
  assert.equal(await ordinary.text(), 'a');
});
