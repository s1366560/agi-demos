import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const runtime = require('@agistack/plugin-runtime');
const {
  createDesktopStructuredImagePreviewClientV2: createClient,
  desktopStructuredImagePreviewAuthorityDefinitionV2: definition,
} = require(`${ROOT}/src/plugins/desktopStructuredImagePreviewAuthorityModuleV2.js`);
const { loadStructuredImagePreviewHttpV2: loadHttp } = require(
  `${ROOT}/src/plugins/desktopStructuredImagePreviewHttpProjectionV2.js`,
);
const { STRUCTURED_IMAGE_PREVIEW_MAX_BYTES_V2: MAX } = require(
  `${ROOT}/src/plugins/desktopStructuredImagePreviewContractV2.js`,
);
const { acquireDesktopRendererServiceOperationLeaseV2: admit } = require(
  `${ROOT}/src/plugins/desktopRendererServiceOperationLeaseV2.js`,
);
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});
const config = () => ({
  mode: 'cloud',
  apiBaseUrl: 'https://api.example.invalid',
  apiKey: '',
  localApiToken: '',
  deviceAuthorizationBaseUrl: '',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  workspaceRoot: '',
});
const owner = (kind = 'conversation') => ({
  kind,
  tenantId: 'tenant-1',
  projectId: 'project-1',
  id: kind === 'conversation' ? 'conversation-1' : 'workspace-1',
});
const carrier = (extra = {}) => ({
  id: 'artifact-event',
  type: 'artifact_ready',
  payload: {
    source_path: '/workspace/output/chart.png',
    mime_type: 'image/png',
    preview_url: 'https://images.example.invalid/chart.png',
    ...extra,
  },
});
const input = (extra = {}) => ({
  source: '/workspace/output/chart.png',
  carriers: [carrier()],
  signal: new AbortController().signal,
  ...extra,
});
const imageResponse = () =>
  new Response(new Uint8Array([137, 80, 78, 71]), { headers: { 'content-type': 'image/png' } });
function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
function fixture(service = { loadImage: loadHttp }, boundConfig = config(), boundOwner = owner()) {
  const state = { acquire: 0, release: 0, calls: 0 };
  const lease = {
    status: 'accepted',
    digest: 'sha256:fixture',
    useService: (callback) => callback(service),
    release: async () => {
      state.release++;
    },
  };
  const actions = {
    acquireOperationLease() {
      throw new Error('fallback');
    },
    acquireServiceOperationLease: async (request) => {
      state.acquire++;
      state.request = request;
      return lease;
    },
  };
  return { state, lease, actions, client: createClient(() => actions, boundConfig, boundOwner) };
}

test('structured image preserves immutable owner and exact session or project lease without credentials', async () => {
  for (const kind of ['conversation', 'workspace']) {
    const boundOwner = owner(kind);
    const boundConfig = config();
    const f = fixture(undefined, boundConfig, boundOwner);
    let wire;
    globalThis.fetch = async (url, init) => {
      wire = { url, init };
      return imageResponse();
    };
    boundOwner.id = 'changed';
    boundConfig.tenantId = 'changed';
    const request = input();
    const blob = await f.client.loadImage(request);
    assert.equal(blob.type, 'image/png');
    assert.equal(blob.size, 4);
    assert.ok(Object.isFrozen(f.client.owner));
    assert.equal(f.client.owner.id, owner(kind).id);
    assert.equal(f.state.release, 1);
    assert.deepEqual(
      f.state.request.scope,
      kind === 'conversation'
        ? {
            kind: 'session',
            tenant_id: 'tenant-1',
            project_id: 'project-1',
            session_id: 'conversation-1',
          }
        : { kind: 'project', tenant_id: 'tenant-1', project_id: 'project-1' },
    );
    assert.equal(wire.init.credentials, 'omit');
    assert.equal(wire.init.referrerPolicy, 'no-referrer');
    assert.equal(wire.init.signal, request.signal);
    assert.equal(wire.init.headers, undefined);
  }
});

test('blank client construction is inert and scope mismatch rejects before acquiring', async () => {
  const f = fixture(undefined, { ...config(), tenantId: '' }, { ...owner(), tenantId: '' });
  await assert.rejects(
    f.client.loadImage(input()),
    (error) => error.code === 'desktop_structured_image_preview_scope_mismatch',
  );
  assert.equal(f.state.acquire, 0);
  const wrongWorkspace = fixture(undefined, config(), { ...owner('workspace'), id: 'other' });
  await assert.rejects(wrongWorkspace.client.loadImage(input()));
  assert.equal(wrongWorkspace.state.acquire, 0);
});

test('explicit carrier owner drift fails before lease while ownerless genuine artifact metadata remains legal', async () => {
  for (const extra of [
    { tenant_id: 'other' },
    { projectId: 'other' },
    { conversation_id: 'other' },
  ]) {
    const f = fixture();
    await assert.rejects(
      f.client.loadImage(input({ carriers: [carrier(extra)] })),
      (error) => error.code === 'desktop_structured_image_preview_carrier_scope_mismatch',
    );
    assert.equal(f.state.acquire, 0);
  }
  const f = fixture();
  globalThis.fetch = async () => imageResponse();
  assert.equal((await f.client.loadImage(input())).size, 4);
});

test('input carriers freeze before delayed admission and URL matching stays inside loaded service', async () => {
  const gate = deferred();
  const f = fixture();
  const request = input();
  let fetched;
  f.actions.acquireServiceOperationLease = async () => {
    await gate.promise;
    return f.lease;
  };
  globalThis.fetch = async (url) => {
    fetched = url;
    return imageResponse();
  };
  const pending = f.client.loadImage(request);
  request.carriers[0].payload.preview_url = 'https://other.example.invalid/changed';
  gate.resolve();
  await pending;
  assert.equal(fetched, 'https://images.example.invalid/chart.png');
});

test('ambiguous structured references and unrelated external markdown images make zero HTTP', async () => {
  let requests = 0;
  globalThis.fetch = async () => {
    requests++;
    return imageResponse();
  };
  for (const request of [
    input({ carriers: [] }),
    input({ source: 'https://unrelated.example.invalid/image.png' }),
    input({
      carriers: [carrier(), carrier({ preview_url: 'https://images.example.invalid/other.png' })],
    }),
    input({
      carriers: [
        carrier({ preview_url: 'https://user:password@images.example.invalid/image.png' }),
      ],
    }),
  ]) {
    const f = fixture();
    await assert.rejects(f.client.loadImage(request));
    assert.equal(f.state.release, 1);
  }
  assert.equal(requests, 0);
});

test('actual MIME and both declared and streamed byte limits are enforced with reader cancellation', async () => {
  let cancelled = 0;
  for (const mode of ['mime', 'declared', 'stream']) {
    globalThis.fetch = async () =>
      new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(new Uint8Array(mode === 'stream' ? MAX + 1 : 1));
          },
          cancel() {
            cancelled++;
          },
        }),
        {
          headers: {
            'content-type': mode === 'mime' ? 'text/html' : 'image/png',
            ...(mode === 'declared' ? { 'content-length': String(MAX + 1) } : {}),
          },
        },
      );
    await assert.rejects(fixture().client.loadImage(input()));
  }
  assert.equal(cancelled, 3);
  globalThis.fetch = async () =>
    new Response(new Uint8Array(MAX), { headers: { 'content-type': 'image/png' } });
  assert.equal((await fixture().client.loadImage(input())).size, MAX);
});

test('abort while acquiring releases the late lease without reading the URL', async () => {
  const f = fixture();
  const gate = deferred();
  const controller = new AbortController();
  let fetches = 0;
  f.actions.acquireServiceOperationLease = async () => {
    await gate.promise;
    return f.lease;
  };
  globalThis.fetch = async () => {
    fetches++;
    return imageResponse();
  };
  const pending = f.client.loadImage(input({ signal: controller.signal }));
  controller.abort();
  gate.resolve();
  await assert.rejects(pending, { name: 'AbortError' });
  assert.equal(f.state.release, 1);
  assert.equal(fetches, 0);
});

test('abort during response streaming cancels the reader and rejects a late result', async () => {
  const entered = deferred();
  let cancelled = 0;
  const controller = new AbortController();
  const f = fixture();
  globalThis.fetch = async () =>
    new Response(
      new ReadableStream({
        start() {
          entered.resolve();
        },
        cancel() {
          cancelled++;
        },
      }),
      { headers: { 'content-type': 'image/png' } },
    );
  const pending = f.client.loadImage(input({ signal: controller.signal }));
  await entered.promise;
  await Promise.resolve();
  controller.abort();
  await assert.rejects(pending, { name: 'AbortError' });
  assert.equal(cancelled, 1);
  assert.equal(f.state.release, 1);
});

test('service callback is single consumption and cannot execute after release', async () => {
  let calls = 0;
  const service = {
    loadImage: async () => {
      calls++;
      return new Blob(['image'], { type: 'image/png' });
    },
  };
  const f = fixture(service);
  let captured;
  f.lease.useService = async (callback) => {
    captured = callback;
    const first = callback(service);
    assert.throws(() => callback(service), (error) => error.code === 'desktop_structured_image_preview_operation_released');
    return first;
  };
  await f.client.loadImage(input());
  assert.throws(() => captured(service), (error) => error.code === 'desktop_structured_image_preview_operation_released');
  assert.equal(calls, 1);
});

test('primary service failure is preserved and unsafe network details are not exposed', async () => {
  const primary = new Error('primary');
  const f = fixture({
    loadImage: async () => {
      throw primary;
    },
  });
  f.lease.release = async () => {
    throw new Error('release');
  };
  await assert.rejects(f.client.loadImage(input()), (error) => error === primary);
  globalThis.fetch = async () => {
    throw new TypeError('https://images.example.invalid/image?signature=private');
  };
  await assert.rejects(
    fixture().client.loadImage(input()),
    (error) =>
      error.code === 'desktop_structured_image_preview_transport_failed' &&
      !String(error).includes('signature'),
  );
});

test('custom provider result must still be a bounded image Blob', async () => {
  for (const result of [
    { type: 'image/png', size: 1 },
    new Blob(['text'], { type: 'text/plain' }),
  ]) {
    const f = fixture({ loadImage: async () => result });
    await assert.rejects(f.client.loadImage(input()));
    assert.equal(f.state.release, 1);
  }
});
function definitions() {
  return [
    ...runtime.createDesktopRendererDefinitionsV2(),
    ...readdirSync(`${ROOT}/src/plugins`)
      .filter((name) => /AuthorityModules?V2\.js$/u.test(name))
      .flatMap((name) =>
        Object.values(require(`${ROOT}/src/plugins/${name}`)).filter(
          (value) => value?.moduleRef && typeof value.apply === 'function',
        ),
      ),
  ];
}
function profile() {
  return JSON.parse(
    readFileSync(
      new URL('../../../../shared/profiles/memstack-default-bootstrap.v2.json', import.meta.url),
      'utf8',
    ),
  );
}

test('real Loader disabled module makes zero HTTP and HMR preserves only the admitted old operation', async () => {
  const manager = new runtime.GenerationManagerV2();
  const loader = new runtime.LoaderV2(definitions(), 'desktop-renderer');
  const gate = deferred();
  const entered = deferred();
  let fetches = 0;
  globalThis.fetch = async () => {
    fetches++;
    entered.resolve();
    await gate.promise;
    return imageResponse();
  };
  try {
    const old = await loader.stage(profile());
    await manager.publish(old);
    const client = createClient(
      () => ({
        acquireOperationLease() {
          throw new Error('fallback');
        },
        acquireServiceOperationLease: (request) =>
          admit(manager.current, request, (g) => manager.acquire(g)),
      }),
      config(),
      owner(),
    );
    const pending = client.loadImage(input());
    await entered.promise;
    const disabled = profile();
    disabled.entries.find((item) => item.module_ref === definition.moduleRef).enabled = false;
    await manager.publish(await loader.stage(disabled));
    assert.equal(old.disposed, false);
    await assert.rejects(client.loadImage(input()));
    assert.equal(fetches, 1);
    gate.resolve();
    assert.equal((await pending).size, 4);
    assert.equal(old.disposed, true);
    assert.equal(manager.current.leaseCount, 0);
  } finally {
    await manager.close();
  }
});

test('empty response bodies never become successful image previews', async () => {
  for (const body of [null, new Uint8Array()]) {
    globalThis.fetch = async () => new Response(body, { headers: { 'content-type': 'image/png' } });
    const f = fixture();
    await assert.rejects(
      f.client.loadImage(input()),
      (error) => error.code === 'desktop_structured_image_preview_content_invalid',
    );
    assert.equal(f.state.release, 1);
  }
});

test('an adapter dropping its started service promise cannot release the image lease early', async () => {
  const gate = deferred();
  const entered = deferred();
  const service = {
    loadImage: async () => {
      entered.resolve();
      await gate.promise;
      return new Blob(['image'], { type: 'image/png' });
    },
  };
  const f = fixture(service);
  f.lease.useService = (callback) => {
    void callback(service);
    return undefined;
  };
  const pending = f.client.loadImage(input());
  await entered.promise;
  await Promise.resolve();
  assert.equal(f.state.release, 0);
  gate.resolve();
  assert.equal((await pending).size, 5);
  assert.equal(f.state.release, 1);
});

test('successful image reads still surface a failed lease release', async () => {
  const secondary = new Error('release failed');
  const f = fixture({ loadImage: async () => new Blob(['image'], { type: 'image/png' }) });
  f.lease.release = async () => {
    throw secondary;
  };
  await assert.rejects(f.client.loadImage(input()), (error) => error === secondary);
});
