import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { memory, nativeScope, projectScope } from './nativeKnowledgeFixtures.mjs';
const require = createRequire(import.meta.url);
const root = '/tmp/agistack-desktop-test-dist/src';
const {
  createDesktopProjectMemoriesOperationsV2,
  createDesktopNativeKnowledgeClientV2,
  withDesktopProjectMemoriesAuthorityOperationV2,
} = require(root + '/plugins/desktopProjectMemoriesAuthorityModuleV2.js');
const { createDesktopProjectMemoriesHttpAuthorityV2 } = require(
  root + '/plugins/desktopProjectMemoriesHttpProjectionV2.js',
);
const { createNativeMemoriesController } = require(
  root + '/features/project-knowledge/nativeMemoriesController.js',
);
const config = {
  apiBaseUrl: 'http://127.0.0.1:43117',
  deviceAuthorizationBaseUrl: 'https://cloud.test',
  apiKey: 'identity',
  localApiToken: 'launch',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: '',
  workspaceRoot: '',
  mode: 'local',
};
const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
function fixture(digest = nativeScope.digest) {
  const leases = [];
  const actions = {
    async acquireServiceOperationLease() {
      leases.push('acquire');
      return {
        status: 'accepted',
        digest,
        useService: (fn) => fn({ bindOperation: createDesktopProjectMemoriesHttpAuthorityV2 }),
        async release() {
          leases.push('release');
        },
      };
    },
  };
  const client = createDesktopNativeKnowledgeClientV2(
    createDesktopProjectMemoriesOperationsV2(() => actions),
    config,
  );
  return { actions, client, leases };
}
function transport(handler = () => undefined) {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    const path = new URL(String(url)).pathname;
    const body = init.body ? JSON.parse(init.body) : null;
    const command = body ? (body.mutation ?? body.query) : null;
    calls.push({ path, command });
    assert.equal(new Headers(init.headers).get('X-Agistack-Launch'), 'launch');
    const override = handler({ path, command, calls });
    if (override) return override;
    if (path.endsWith('/auth/me')) return json({ user_id: memory.author_id, is_active: true });
    if (path.endsWith('/context')) return json({ contract_version: '1.0.0', scope: nativeScope });
    if (command.operation === 'sync_status')
      return json({ error: { code: 'knowledge_sync_unavailable' } }, 503);
    const result =
      command.operation === 'get'
        ? { memory }
        : {
            receipt: {
              sequence: 1,
              memory: {
                ...(command.memory ?? memory),
                embedding: command.memory?.embedding ?? null,
                version: command.operation === 'create' ? 1 : command.expected_revision + 1,
              },
              deleted: command.operation === 'delete',
            },
            replayed: false,
            processing_status: 'accepted',
          };
    return json({ contract_version: '1.0.0', scope: nativeScope, result });
  };
  return calls;
}
const originalFetch = globalThis.fetch;
test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test('local acceptance CRUD discovers scope through the real client and HTTP authority without sync permission', async () => {
  const calls = transport();
  const { client, leases } = fixture();
  let serial = 0;
  const controller = createNativeMemoriesController({
    client,
    authority: {
      scope: projectScope,
      userId: memory.author_id,
      sessionId: 'session-1',
      contextRevision: nativeScope.context_revision,
      generationDigest: nativeScope.digest,
      available: true,
      allowedActions: ['view', 'list', 'create', 'update', 'delete'],
    },
    newId: () => `created-${++serial}`,
    now: () => 123,
  });
  await controller.create();
  assert.equal(controller.getSnapshot().phase, 'creating');
  assert.deepEqual(
    calls.map((c) => c.path),
    [
      '/api/v1/auth/me',
      '/api/v1/knowledge/context',
      '/api/v1/auth/me',
      '/api/v1/knowledge/context',
    ],
  );
  controller.setDraft({ title: 'Created', content: 'Body' });
  await controller.save();
  assert.equal(controller.getSnapshot().notice, 'accepted');
  await controller.open(memory.id, 'edit');
  assert.equal(controller.getSnapshot().phase, 'editing');
  controller.setDraft({ content: 'Edited' });
  await controller.save();
  assert.equal(controller.getSnapshot().notice, 'accepted');
  await controller.open(memory.id, 'delete');
  assert.equal(controller.getSnapshot().phase, 'confirming_delete');
  await controller.confirmDelete();
  assert.equal(controller.getSnapshot().notice, 'accepted');
  assert.deepEqual(
    calls.filter((c) => c.command).map((c) => c.command.operation),
    ['create', 'get', 'update', 'get', 'delete'],
  );
  assert.equal(
    leases.filter((x) => x === 'acquire').length,
    leases.filter((x) => x === 'release').length,
  );
});

for (const step of [1, 2, 3, 4])
  test(`scope observation abort after HTTP step ${step} never continues`, async () => {
    const abort = new AbortController();
    const calls = transport(({ calls }) => {
      if (calls.length === step) abort.abort();
    });
    await assert.rejects(
      fixture().client.observeScope(projectScope, {
        expectedActorId: memory.author_id,
        signal: abort.signal,
      }),
      { name: 'AbortError' },
    );
    assert.equal(calls.length, step);
  });
for (const step of [1, 3])
  test(`actor drift at authentication step ${step} fails closed`, async () => {
    const calls = transport(({ calls }) =>
      calls.length === step ? json({ user_id: 'other-actor', is_active: true }) : undefined,
    );
    await assert.rejects(
      fixture().client.observeScope(projectScope, { expectedActorId: memory.author_id }),
      (e) => e.status === 409,
    );
    assert.equal(calls.length, step);
  });
for (const [field, value] of Object.entries({
  tenant_id: 'other',
  project_id: 'other',
  context_revision: 8,
  profile_id: 'other',
  generation: 5,
  digest: 'other',
}))
  test(`observed ${field} drift fails closed`, async () => {
    transport(({ calls }) =>
      calls.length === 4
        ? json({ contract_version: '1.0.0', scope: { ...nativeScope, [field]: value } })
        : undefined,
    );
    await assert.rejects(
      fixture().client.observeScope(projectScope, { expectedActorId: memory.author_id }),
      (e) => e.status === 409,
    );
  });
test('observed generation must match the admitted generation lease', async () => {
  transport();
  await assert.rejects(
    fixture('stale-digest').client.observeScope(projectScope, {
      expectedActorId: memory.author_id,
    }),
    (e) => e.status === 409,
  );
});
test('retained authority observation is revoked after operation closure before any HTTP', async () => {
  const calls = transport();
  const { actions } = fixture();
  let retained;
  await withDesktopProjectMemoriesAuthorityOperationV2(
    actions,
    { kind: 'observe-scope', config, scope: projectScope, expectedActorId: memory.author_id },
    async (authority) => {
      retained = authority;
    },
  );
  await assert.rejects(retained.observeScope({ expectedActorId: memory.author_id }));
  assert.equal(calls.length, 0);
});
test('invalid actor and extra observation fields reject before acquiring a lease', async () => {
  const { client, leases } = fixture();
  for (const options of [
    { expectedActorId: '' },
    { expectedActorId: memory.author_id, extra: true },
  ])
    await assert.rejects(async () => client.observeScope(projectScope, options));
  assert.equal(leases.length, 0);
});

test('cloud observation rejects before leasing or issuing HTTP', async () => {
  const calls = transport();
  const { actions, leases } = fixture();
  const client = createDesktopNativeKnowledgeClientV2(
    createDesktopProjectMemoriesOperationsV2(() => actions),
    { ...config, mode: 'cloud', apiBaseUrl: 'https://cloud.test' },
  );
  await assert.rejects(async () =>
    client.observeScope(
      { ...projectScope, authority: 'cloud' },
      { expectedActorId: memory.author_id },
    ),
  );
  assert.equal(leases.length, 0);
  assert.equal(calls.length, 0);
});
