import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const m = require(`${ROOT}/src/plugins/desktopProjectSandboxSurfaceAuthorityModuleV2.js`);
const p = require(`${ROOT}/src/plugins/desktopProjectSandboxSurfaceHttpProjectionV2.js`);
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
  authority = p.createDesktopProjectSandboxSurfaceHttpProjectionV2(runtime),
) {
  const events = [];
  const ops = m.createDesktopProjectSandboxSurfaceOperationsV2(() => ({
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
  return { client: m.createDesktopProjectSandboxSurfaceClientV2(ops, runtime), ops, events };
}
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  delete globalThis.window;
});
const json = (value) =>
  new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } });

const project = { id: 'project-1', tenant_id: 'tenant-1' };
const available = (version = 1) => ({
  availability: 'available',
  contract_version: version,
  reason_code: null,
});
const caps = (mode = 'cloud') => ({
  service_version: '0.1.0',
  contract_version: 2,
  terminal_interactive: available(),
  terminal_resume: available(2),
  files: available(),
  kasm_vnc:
    mode === 'cloud'
      ? available()
      : {
          availability: 'not_applicable',
          contract_version: 1,
          reason_code: 'local_kasm_vnc_not_applicable',
        },
});
const authority = (mode = 'cloud') =>
  mode === 'cloud'
    ? { authority: 'sandbox', isolation: 'isolated' }
    : { authority: 'native_workspace', isolation: 'not_applicable' };
const listing = (mode = 'cloud', extra = {}) => ({
  contract_version: 1,
  ...authority(mode),
  root: mode === 'cloud' ? '/' : '/workspace',
  path: '/workspace',
  entries: [],
  cursor: null,
  revision: 'a'.repeat(64),
  ...extra,
});
const content = (mode = 'cloud') => ({
  contract_version: 1,
  ...authority(mode),
  path: '/workspace/file.txt',
  encoding: 'utf-8',
  content: 'hello',
  mime_type: 'text/plain',
  size_bytes: 5,
  revision: 'a'.repeat(64),
  truncated: false,
});
const descriptor = {
  contract_version: 1,
  project_id: 'project-1',
  protocol: 'kasmvnc-1',
  proxy_url: '/api/v1/projects/project-1/sandbox/desktop/proxy/vnc.html',
  auth_mode: 'scoped_http_only_cookie',
};
function responseFor(url, mode = 'cloud') {
  const path = new URL(url).pathname;
  if (path.endsWith('/capabilities')) return json(caps(mode));
  if (path.endsWith('/desktop/session')) return json(descriptor);
  if (path.endsWith('/files')) return json(listing(mode));
  if (path.endsWith('/files/content')) return json(content(mode));
  if (path.endsWith('/files/download'))
    return new Response('hello', {
      headers: {
        'Content-Type': 'text/plain',
        'Content-Disposition': 'attachment; filename="file.txt"',
        'X-MemStack-File-Contract-Version': '1',
        'X-MemStack-File-Authority': authority(mode).authority,
        'X-MemStack-File-Isolation': authority(mode).isolation,
      },
    });
  return json(project);
}
test('Sandbox Surface V2 five Cloud operations use project preflight and preserve contracts', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ path: new URL(url).pathname, method: init.method });
    return responseFor(url);
  };
  const f = fixture();
  assert.equal(Object.keys(f.ops).length, 5);
  assert.equal((await f.client.loadCapabilities()).files.availability, 'available');
  assert.deepEqual(
    (await f.client.listFiles(caps(), { path: '/workspace', limit: 2 })).value,
    listing(),
  );
  assert.equal(
    (await f.client.readFile(caps(), { path: '/workspace/file.txt' })).value.content,
    'hello',
  );
  assert.equal(
    await (await f.client.downloadFile(caps(), { path: '/workspace/file.txt' })).value.bytes.text(),
    'hello',
  );
  const remote = await f.client.openRemoteDesktop(caps(), { resolution: '1920x1080' });
  assert.equal(remote.value.descriptor.project_id, 'project-1');
  assert.equal(f.events.filter((x) => x[0] === 'release').length, 4);
  await remote.value.release();
  await remote.value.release();
  assert.equal(f.events.filter((x) => x[0] === 'release').length, 5);
  assert.equal(calls.filter((x) => x.path === '/api/v1/projects/project-1').length, 5);
  assert.deepEqual(f.events[0][1].scope, {
    kind: 'project',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
  });
});
test('Sandbox Surface V2 Local retains native workspace authority and desktop unavailable after lease', async () => {
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(String(url));
    return responseFor(url, 'local');
  };
  const f = fixture(config('local'));
  assert.equal((await f.client.loadCapabilities()).kasm_vnc.availability, 'not_applicable');
  assert.equal(
    (await f.client.listFiles(caps('local'), { path: '/workspace' })).value.authority,
    'native_workspace',
  );
  assert.equal(
    (await f.client.readFile(caps('local'), { path: '/workspace/file.txt' })).value.isolation,
    'not_applicable',
  );
  assert.equal(
    (await f.client.downloadFile(caps('local'), { path: '/workspace/file.txt' })).value.authority,
    'native_workspace',
  );
  const count = calls.length;
  assert.equal(
    (await f.client.openRemoteDesktop(caps('local'), { resolution: '1920x1080' })).status,
    'unavailable',
  );
  assert.equal(calls.length, count);
  assert.equal(f.events.filter((x) => x[0] === 'release').length, 5);
});
test('Sandbox Surface V2 blank scope and disabled admission cause zero HTTP', async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return json(project);
  };
  const blank = fixture({ ...config('cloud'), tenantId: '', projectId: '' });
  await assert.rejects(blank.client.loadCapabilities(), /identifier/u);
  assert.equal(blank.events.length, 0);
  const ops = m.createDesktopProjectSandboxSurfaceOperationsV2(() => ({
    async acquireServiceOperationLease() {
      return { status: 'rejected', reasonCode: 'missing_service' };
    },
  }));
  await assert.rejects(
    m.createDesktopProjectSandboxSurfaceClientV2(ops, config('cloud')).loadCapabilities(),
    /missing_service/u,
  );
  assert.equal(calls, 0);
});
test('Sandbox Surface V2 capability unavailable is handled by loaded authority without probing files', async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return json(project);
  };
  const f = fixture();
  const snapshot = caps();
  snapshot.files = {
    availability: 'unavailable',
    contract_version: 1,
    reason_code: 'files_disabled',
  };
  assert.deepEqual(await f.client.listFiles(snapshot, { path: '/workspace' }), {
    status: 'unavailable',
    reason_code: 'files_disabled',
  });
  assert.equal(calls, 0);
  assert.deepEqual(
    f.events.map((x) => x[0]),
    ['acquire', 'release'],
  );
});
test('Sandbox Surface V2 Cloud project mismatch prevents operations and error detail is not echoed', async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return json({ ...project, tenant_id: 'other' });
  };
  const f = fixture();
  await assert.rejects(
    f.client.readFile(caps(), { path: '/workspace/file.txt' }),
    /project_mismatch/u,
  );
  assert.equal(calls, 1);
});
test('Sandbox Surface V2 rejects paths, nonnumeric limits and oversized listing responses', async () => {
  const f = fixture();
  await assert.rejects(f.client.listFiles(caps(), { path: '/workspace/../etc' }), /path/u);
  await assert.rejects(
    f.client.listFiles(caps(), { path: '/workspace', limit: '2' }),
    /request_invalid/u,
  );
  assert.equal(f.events.length, 0);
  const entry = {
    path: '/workspace/a',
    name: 'a',
    kind: 'file',
    size_bytes: 1,
    mime_type: 'text/plain',
  };
  globalThis.fetch = async (url) =>
    new URL(url).pathname.endsWith('/files')
      ? json(listing('cloud', { entries: [entry, { ...entry, path: '/workspace/b', name: 'b' }] }))
      : json(project);
  await assert.rejects(
    f.client.listFiles(caps(), { path: '/workspace', limit: 1 }),
    /response_invalid/u,
  );
});
test('Sandbox Surface V2 binary download rejects missing authority headers and oversized bytes', async () => {
  const f = fixture();
  globalThis.fetch = async (url) =>
    new URL(url).pathname.endsWith('/download')
      ? new Response('hello', { headers: { 'Content-Type': 'text/plain' } })
      : json(project);
  await assert.rejects(
    f.client.downloadFile(caps(), { path: '/workspace/file.txt' }),
    /authority/u,
  );
  globalThis.fetch = async (url) => responseFor(url);
  await assert.rejects(
    f.client.downloadFile(caps(), { path: '/workspace/file.txt', max_bytes: 2 }),
    /download_too_large/u,
  );
});
test('Sandbox Surface V2 remote desktop holds lease until abort or explicit release', async () => {
  globalThis.fetch = async (url) => responseFor(url);
  const controller = new AbortController();
  const f = fixture();
  const remote = await f.client.openRemoteDesktop(
    caps(),
    { resolution: '1280x720' },
    controller.signal,
  );
  assert.equal(f.events.filter((x) => x[0] === 'release').length, 0);
  controller.abort();
  await remote.value.release();
  assert.equal(f.events.filter((x) => x[0] === 'release').length, 1);
});
test('Sandbox Surface V2 abort during acquire prevents binding and rejects escaped callback', async () => {
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
        async execute() {
          return caps();
        },
      };
    },
  };
  const ops = m.createDesktopProjectSandboxSurfaceOperationsV2(() => ({
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
    .createDesktopProjectSandboxSurfaceClientV2(ops, config('cloud'))
    .loadCapabilities(controller.signal);
  controller.abort();
  proceed();
  await assert.rejects(job, { name: 'AbortError' });
  assert.equal(binds, 0);
  assert.equal(releases, 1);
  await assert.rejects(callback(service), /released/u);
});
test('Sandbox Surface V2 preserves primary failure when lease release fails', async () => {
  const failure = new DesktopApiError('conflict', 409, {});
  const ops = m.createDesktopProjectSandboxSurfaceOperationsV2(() => ({
    async acquireServiceOperationLease() {
      return {
        status: 'accepted',
        useService: (use) =>
          use({
            bindOperation: () => ({
              async execute() {
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
    m.createDesktopProjectSandboxSurfaceClientV2(ops, config('cloud')).loadCapabilities(),
    (error) => error === failure,
  );
});
test('Sandbox Surface V2 actual vault binary broker preserves sandbox authority metadata', async () => {
  const { executeVaultBoundCloudRequest } = require(`${ROOT}/electron/main/cloudRequestPolicy.js`);
  let fallback = 0;
  globalThis.fetch = async () => {
    fallback++;
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
            async fetch(url) {
              return new URL(url).pathname === '/api/v1/workspace-context'
                ? json({
                    context: {
                      tenant_id: 'tenant-1',
                      project_id: 'project-1',
                      workspace_id: 'workspace-1',
                    },
                  })
                : responseFor(url);
            },
          });
        },
      },
    },
  };
  const value = (
    await fixture({ ...config('cloud'), apiKey: '' }).client.downloadFile(caps(), {
      path: '/workspace/file.txt',
    })
  ).value;
  assert.equal(value.authority, 'sandbox');
  assert.equal(value.isolation, 'isolated');
  assert.equal(await value.bytes.text(), 'hello');
  assert.equal(fallback, 0);
});
test('Sandbox Surface V2 real Loader publishes project-resolvable service and disabled next generation removes it', async () => {
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
      m.DESKTOP_PROJECT_SANDBOX_SURFACE_AUTHORITY_SERVICE_V2,
      scope,
      {
        version: '1.0.0',
      },
    );
    assert.equal(typeof service.bindOperation(config()).execute, 'function');
    const disabled = structuredClone(profile);
    disabled.entries.find(
      (entry) => entry.entry_id === 'builtin-desktop-project-sandbox-surface-authority',
    ).enabled = false;
    const next = await loader.stage(disabled);
    try {
      assert.throws(
        () =>
          next.resolve(m.DESKTOP_PROJECT_SANDBOX_SURFACE_AUTHORITY_SERVICE_V2, scope, {
            version: '1.0.0',
          }),
        (error) => error.code === 'missing_service',
      );
      assert.equal(typeof service.bindOperation(config()).execute, 'function');
    } finally {
      await next.dispose();
    }
  } finally {
    await generation.dispose();
  }
});

test('Sandbox Surface V2 actual Local listing omits root while Cloud root stays mandatory', async () => {
  const localListing = listing('local');
  delete localListing.root;
  globalThis.fetch = async () => json(localListing);
  const value = (
    await fixture(config('local')).client.listFiles(caps('local'), { path: '/workspace' })
  ).value;
  assert.equal(value.root, '/workspace');
  assert.equal(value.authority, 'native_workspace');
  const cloudListing = listing();
  delete cloudListing.root;
  globalThis.fetch = async (url) =>
    new URL(url).pathname.endsWith('/files') ? json(cloudListing) : json(project);
  await assert.rejects(
    fixture().client.listFiles(caps(), { path: '/workspace' }),
    /listing contract/u,
  );
});
