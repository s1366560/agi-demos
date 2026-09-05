import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const m = require(`${ROOT}/src/plugins/desktopProjectSandboxUploadAuthorityModuleV2.js`);
const p = require(`${ROOT}/src/plugins/desktopProjectSandboxUploadHttpProjectionV2.js`);
const { DesktopApiError } = require(`${ROOT}/src/api/client.js`);
const config = (mode = 'local') => ({
  apiBaseUrl: mode === 'local' ? 'http://127.0.0.1:43117' : 'https://api.test',
  deviceAuthorizationBaseUrl: 'https://api.test',
  apiKey: 'trusted-session',
  localApiToken: mode === 'local' ? 'private-launch' : '',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  mode,
  workspaceRoot: '',
});
function fixture(
  runtime = config('cloud'),
  authority = p.createDesktopProjectSandboxUploadHttpProjectionV2(runtime),
) {
  const events = [];
  const ops = m.createDesktopProjectSandboxUploadOperationsV2(() => ({
    async acquireServiceOperationLease(descriptor) {
      events.push(['acquire', descriptor]);
      return {
        status: 'accepted',
        useService: (use) =>
          use({
            bindOperation: (frozen) => {
              assert.ok(Object.isFrozen(frozen));
              return authority;
            },
          }),
        async release() {
          events.push(['release']);
        },
      };
    },
  }));
  return { client: m.createDesktopProjectSandboxUploadClientV2(ops, runtime), ops, events };
}
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  delete globalThis.window;
});
const json = (value) =>
  new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } });

const project = { id: 'project-1', tenant_id: 'tenant-1' };
const file = (extra = {}) => ({
  name: 'evidence.txt',
  type: 'text/plain',
  size: 4,
  arrayBuffer: async () => Uint8Array.from([65, 66, 67, 68]).buffer,
  ...extra,
});
const result = (extra = {}) => ({
  success: true,
  is_error: false,
  content: [
    {
      type: 'text',
      text: JSON.stringify({
        success: true,
        path: '/workspace/input/evidence.txt',
        size_bytes: 4,
        ...extra,
      }),
    },
  ],
});
test('Sandbox Upload V2 Cloud preflight precedes file read and retains import_file wire', async () => {
  const events = [];
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init, body: init.body ? JSON.parse(init.body) : null });
    events.push(init.method);
    return json(init.method === 'GET' ? project : result());
  };
  const f = fixture();
  const metadata = await f.client.uploadSandboxFile(
    file({
      arrayBuffer: async () => {
        events.push('read');
        return Uint8Array.from([65, 66, 67, 68]).buffer;
      },
    }),
  );
  assert.deepEqual(events, ['GET', 'read', 'POST']);
  assert.ok(calls[0].url.endsWith('/projects/project-1?tenant_id=tenant-1'));
  assert.deepEqual(calls[1].body, {
    tool_name: 'import_file',
    arguments: {
      filename: 'evidence.txt',
      content_base64: 'QUJDRA==',
      destination: '/workspace/input',
      overwrite: true,
    },
    timeout: 60,
  });
  assert.deepEqual(metadata, {
    filename: 'evidence.txt',
    sandbox_path: '/workspace/input/evidence.txt',
    mime_type: 'text/plain',
    size_bytes: 4,
  });
  assert.deepEqual(f.events[0][1].scope, {
    kind: 'project',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
  });
  assert.equal(f.events.at(-1)[0], 'release');
});
test('Sandbox Upload V2 disabled and blank scope perform no file read or HTTP', async () => {
  let reads = 0;
  let fetches = 0;
  const value = file({
    arrayBuffer: async () => {
      reads++;
      return new ArrayBuffer(4);
    },
  });
  globalThis.fetch = async () => {
    fetches++;
    return json({});
  };
  const ops = m.createDesktopProjectSandboxUploadOperationsV2(() => ({
    async acquireServiceOperationLease() {
      return { status: 'rejected', reasonCode: 'missing_service' };
    },
  }));
  await assert.rejects(
    m.createDesktopProjectSandboxUploadClientV2(ops, config('cloud')).uploadSandboxFile(value),
    /missing_service/u,
  );
  const f = fixture({ ...config('cloud'), tenantId: '', projectId: '' });
  await assert.rejects(f.client.uploadSandboxFile(value), /scope/u);
  assert.equal(f.events.length, 0);
  assert.equal(reads, 0);
  assert.equal(fetches, 0);
});
test('Sandbox Upload V2 Local unavailability is loaded then rejects before reading file', async () => {
  let reads = 0;
  let fetches = 0;
  globalThis.fetch = async () => {
    fetches++;
    return json({});
  };
  const f = fixture(config('local'));
  await assert.rejects(
    f.client.uploadSandboxFile(
      file({
        arrayBuffer: async () => {
          reads++;
          return new ArrayBuffer(4);
        },
      }),
    ),
    (error) =>
      error.status === 501 && error.payload.reason_code === 'local_sandbox_upload_unavailable',
  );
  assert.equal(reads, 0);
  assert.equal(fetches, 0);
  assert.deepEqual(
    f.events.map((x) => x[0]),
    ['acquire', 'release'],
  );
});
test('Sandbox Upload V2 Cloud scope mismatch rejects before file read or POST', async () => {
  let reads = 0;
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return json({ ...project, tenant_id: 'other' });
  };
  await assert.rejects(
    fixture().client.uploadSandboxFile(
      file({
        arrayBuffer: async () => {
          reads++;
          return new ArrayBuffer(4);
        },
      }),
    ),
    /project_mismatch/u,
  );
  assert.equal(reads, 0);
  assert.equal(calls, 1);
});
test('Sandbox Upload V2 freezes metadata and bound read receiver before admission', async () => {
  let proceed;
  const pending = new Promise((resolve) => {
    proceed = resolve;
  });
  let captured;
  const ops = m.createDesktopProjectSandboxUploadOperationsV2(() => ({
    async acquireServiceOperationLease() {
      await pending;
      return {
        status: 'accepted',
        useService: (use) =>
          use({
            bindOperation: () => ({
              async uploadSandboxFile(input) {
                captured = input;
                await input.file.arrayBuffer();
                return result();
              },
            }),
          }),
        async release() {},
      };
    },
  }));
  const source = file({
    arrayBuffer: async function () {
      assert.equal(this, source);
      return new ArrayBuffer(4);
    },
  });
  const client = m.createDesktopProjectSandboxUploadClientV2(ops, config('cloud'));
  const job = client.uploadSandboxFile(source);
  source.name = 'changed';
  source.size = 8;
  source.arrayBuffer = async () => {
    throw new Error('replaced reader');
  };
  proceed();
  assert.equal((await job).filename, 'evidence.txt');
  assert.equal(captured.file.size, 4);
  assert.ok(Object.isFrozen(captured.file));
});
test('Sandbox Upload V2 validates actual bytes and safe response path without raw content errors', async () => {
  let calls = 0;
  globalThis.fetch = async (url, init) => {
    calls++;
    return json(init.method === 'GET' ? project : result());
  };
  await assert.rejects(fixture().client.uploadSandboxFile(file({ size: 5 })), /size_mismatch/u);
  assert.equal(calls, 1);
  for (const path of [
    '/etc/evidence.txt',
    '/workspace/input/../evidence.txt',
    '/workspace/input/other.txt',
    '/workspace/input/evidence.txt\u0000',
  ]) {
    globalThis.fetch = async (url, init) =>
      json(
        init.method === 'GET'
          ? project
          : result({ path, content_base64: 'test-only-file-content' }),
      );
    await assert.rejects(
      fixture().client.uploadSandboxFile(file()),
      (error) =>
        error.status === 502 && !JSON.stringify(error.payload).includes('test-only-file-content'),
    );
  }
});
test('Sandbox Upload V2 rejects path-bearing filenames before admission', async () => {
  for (const name of ['../x', 'a/b', 'a\\b', '.', '..', 'x\u0000']) {
    const f = fixture();
    await assert.rejects(f.client.uploadSandboxFile(file({ name })), /filename/u);
    assert.equal(f.events.length, 0);
  }
});
test('Sandbox Upload V2 abort during file read releases promptly and late bytes never POST', async () => {
  let finish;
  let started;
  const reading = new Promise((resolve) => {
    started = resolve;
  });
  const bytes = new Promise((resolve) => {
    finish = resolve;
  });
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return json(project);
  };
  const controller = new AbortController();
  const f = fixture();
  const job = f.client.uploadSandboxFile(
    file({
      arrayBuffer: () => {
        started();
        return bytes;
      },
    }),
    controller.signal,
  );
  await reading;
  controller.abort();
  await assert.rejects(job, { name: 'AbortError' });
  assert.equal(f.events.at(-1)[0], 'release');
  finish(new ArrayBuffer(4));
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(calls, 1);
});
test('Sandbox Upload V2 abort during acquire and escaped callback cannot read or rebind', async () => {
  let proceed;
  const pending = new Promise((resolve) => {
    proceed = resolve;
  });
  let callback;
  let binds = 0;
  let releases = 0;
  const service = {
    bindOperation() {
      binds++;
      return {
        async uploadSandboxFile() {
          return result();
        },
      };
    },
  };
  const ops = m.createDesktopProjectSandboxUploadOperationsV2(() => ({
    async acquireServiceOperationLease() {
      await pending;
      return {
        status: 'accepted',
        useService: (use) => {
          callback = use;
          return use(service);
        },
        async release() {
          releases++;
        },
      };
    },
  }));
  const controller = new AbortController();
  const job = m
    .createDesktopProjectSandboxUploadClientV2(ops, config('cloud'))
    .uploadSandboxFile(file(), controller.signal);
  controller.abort();
  proceed();
  await assert.rejects(job, { name: 'AbortError' });
  assert.equal(binds, 0);
  assert.equal(releases, 1);
  await assert.rejects(callback(service), /released/u);
});
test('Sandbox Upload V2 retains primary error when release also fails', async () => {
  const failure = new DesktopApiError('request failure', 409, {});
  const ops = m.createDesktopProjectSandboxUploadOperationsV2(() => ({
    async acquireServiceOperationLease() {
      return {
        status: 'accepted',
        useService: (use) =>
          use({
            bindOperation: () => ({
              async uploadSandboxFile() {
                throw failure;
              },
            }),
          }),
        async release() {
          throw new Error('secondary');
        },
      };
    },
  }));
  await assert.rejects(
    m.createDesktopProjectSandboxUploadClientV2(ops, config('cloud')).uploadSandboxFile(file()),
    (error) => error === failure,
  );
});
test('Sandbox Upload V2 abort after HTTP rejects uploaded metadata and error payload never echoes content', async () => {
  const controller = new AbortController();
  globalThis.fetch = async (url, init) => {
    if (init.method === 'GET') return json(project);
    controller.abort();
    return json(result());
  };
  const f = fixture();
  await assert.rejects(f.client.uploadSandboxFile(file(), controller.signal), {
    name: 'AbortError',
  });
  globalThis.fetch = async (url, init) =>
    init.method === 'GET'
      ? json(project)
      : new Response(
          JSON.stringify({
            detail: 'test-only-file-content',
            arguments: { content_base64: 'test-only-file-content' },
          }),
          { status: 500, headers: { 'Content-Type': 'application/json' } },
        );
  await assert.rejects(
    fixture().client.uploadSandboxFile(file()),
    (error) =>
      error.status === 500 && !JSON.stringify(error.payload).includes('test-only-file-content'),
  );
});
test('Sandbox Upload V2 native vault broker authorizes preflight and upload without renderer token', async () => {
  const { executeVaultBoundCloudRequest } = require(`${ROOT}/electron/main/cloudRequestPolicy.js`);
  let direct = 0;
  const paths = [];
  globalThis.fetch = async () => {
    direct++;
    throw new Error('renderer fallback');
  };
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          assert.equal(command, 'cloud_request');
          return executeVaultBoundCloudRequest(args.request, {
            async loadTrustedSession() {
              return {
                version: 1,
                api_base_url: 'https://api.test',
                runtime_mode: 'cloud',
                credential_kind: 'cloud_bearer',
                credential: 'vault-only-token',
                expires_at: null,
              };
            },
            async fetch(url, init) {
              const path = new URL(url).pathname;
              paths.push(path);
              assert.equal(
                new Headers(init.headers).get('Authorization'),
                'Bearer vault-only-token',
              );
              if (path === '/api/v1/workspace-context')
                return json({
                  context: {
                    tenant_id: 'tenant-1',
                    project_id: 'project-1',
                    workspace_id: 'workspace-1',
                  },
                });
              return json(init.method === 'GET' ? project : result());
            },
          });
        },
      },
    },
  };
  const uploaded = await fixture({ ...config('cloud'), apiKey: '' }).client.uploadSandboxFile(
    file(),
  );
  assert.equal(uploaded.size_bytes, 4);
  assert.equal(direct, 0);
  assert.deepEqual(paths, [
    '/api/v1/workspace-context',
    '/api/v1/projects/project-1',
    '/api/v1/workspace-context',
    '/api/v1/projects/project-1/sandbox/execute',
  ]);
});
test('Sandbox Upload V2 real Loader publishes project-resolvable service and disabled next generation removes it', async () => {
  const runtime = require('@agistack/plugin-runtime');
  const authorities = readdirSync(`${ROOT}/src/plugins`)
    .filter((name) => /AuthorityModules?V2\.js$/u.test(name))
    .flatMap((name) =>
      Object.values(require(`${ROOT}/src/plugins/${name}`)).filter(
        (value) => value?.moduleRef && typeof value.apply === 'function',
      ),
    );
  const profile = JSON.parse(
    readFileSync(
      new URL('../../../../shared/profiles/memstack-default-bootstrap.v2.json', import.meta.url),
      'utf8',
    ),
  );
  const loader = new runtime.LoaderV2(
    [...runtime.createDesktopRendererDefinitionsV2(), ...authorities],
    'desktop-renderer',
  );
  const generation = await loader.stage(profile);
  const scope = { kind: 'project', tenant_id: 'tenant-1', project_id: 'project-1' };
  try {
    const service = generation.resolve(
      m.DESKTOP_PROJECT_SANDBOX_UPLOAD_AUTHORITY_SERVICE_V2,
      scope,
      {
        version: '1.0.0',
      },
    );
    assert.equal(typeof service.bindOperation(config()).uploadSandboxFile, 'function');
    const disabled = structuredClone(profile);
    disabled.entries.find(
      (entry) => entry.entry_id === 'builtin-desktop-project-sandbox-upload-authority',
    ).enabled = false;
    const next = await loader.stage(disabled);
    try {
      assert.throws(
        () =>
          next.resolve(m.DESKTOP_PROJECT_SANDBOX_UPLOAD_AUTHORITY_SERVICE_V2, scope, {
            version: '1.0.0',
          }),
        (error) => error.code === 'missing_service',
      );
      assert.equal(typeof service.bindOperation(config()).uploadSandboxFile, 'function');
    } finally {
      await next.dispose();
    }
  } finally {
    await generation.dispose();
  }
});

test('Sandbox Upload V2 native broker supports bounded import larger than the ordinary request budget', async () => {
  const { executeVaultBoundCloudRequest } = require(`${ROOT}/electron/main/cloudRequestPolicy.js`);
  let direct = 0;
  let posts = 0;
  globalThis.fetch = async () => {
    direct++;
    throw new Error('renderer fallback');
  };
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          assert.equal(command, 'cloud_request');
          return executeVaultBoundCloudRequest(args.request, {
            async loadTrustedSession() {
              return {
                version: 1,
                api_base_url: 'https://api.test',
                runtime_mode: 'cloud',
                credential_kind: 'cloud_bearer',
                credential: 'vault-only-token',
                expires_at: null,
              };
            },
            async fetch(url, init) {
              if (init.method === 'POST') {
                posts++;
                return json(result({ size_bytes: 400000 }));
              }
              return json(
                new URL(url).pathname === '/api/v1/workspace-context'
                  ? {
                      context: {
                        tenant_id: 'tenant-1',
                        project_id: 'project-1',
                        workspace_id: 'workspace-1',
                      },
                    }
                  : project,
              );
            },
          });
        },
      },
    },
  };
  const uploaded = await fixture({ ...config('cloud'), apiKey: '' }).client.uploadSandboxFile(
    file({ size: 400000, arrayBuffer: async () => new ArrayBuffer(400000) }),
  );
  assert.equal(uploaded.size_bytes, 400000);
  assert.equal(direct, 0);
  assert.equal(posts, 1);
});
test('Sandbox Upload V2 rejects more than 16 MiB before admission and file reading', async () => {
  let reads = 0;
  let fetches = 0;
  globalThis.fetch = async () => {
    fetches++;
    return json(project);
  };
  const f = fixture();
  await assert.rejects(
    f.client.uploadSandboxFile(
      file({
        size: 16 * 1048576 + 1,
        arrayBuffer: async () => {
          reads++;
          return new ArrayBuffer(0);
        },
      }),
    ),
    (error) => error.status === 413,
  );
  assert.equal(reads, 0);
  assert.equal(fetches, 0);
  assert.equal(f.events.length, 0);
});
