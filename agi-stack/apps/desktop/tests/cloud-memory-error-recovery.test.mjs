import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const root = process.env.CLOUD_MEMORY_AUTHORITY_DIST ?? '/tmp/agistack-desktop-test-dist';
const { executeVaultBoundCloudRequest } = require(`${root}/electron/main/cloudRequestPolicy.js`);
const { createDesktopCloudMemoryHttpV2 } = require(
  `${root}/src/plugins/desktopCloudMemoryHttpV2.js`,
);
const { createCloudMemoriesController } = require(
  `${root}/src/features/project-knowledge/cloudMemoriesController.js`,
);
const scope = {
  authority: 'cloud',
  tenantId: 'tenant-1',
  projectId: 'project-1',
};
const config = {
  apiBaseUrl: 'https://fixture.invalid',
  deviceAuthorizationBaseUrl: '',
  apiKey: '',
  localApiToken: '',
  tenantId: scope.tenantId,
  projectId: scope.projectId,
  workspaceId: '',
  mode: 'cloud',
  workspaceRoot: '',
};
const authority = {
  scope,
  actorId: 'actor-1',
  sessionId: 'session-1',
  contextRevision: 7,
  generationDigest: 'generation-1',
  available: true,
  allowedActions: ['list', 'view'],
};
const list = {
  scope,
  scopeRevision: 7,
  authority: 'cloud',
  availability: 'available',
  reasonCode: null,
  allowedActions: ['list', 'view'],
  memories: [],
  page: 1,
  pageSize: 50,
  total: 0,
  commandCapabilities: {
    protocolVersion: 1,
    tenantId: scope.tenantId,
    projectId: scope.projectId,
    actorId: 'actor-1',
    allowedActions: ['create'],
    objects: [],
  },
};
const row = {
  id: 'memory-1',
  project_id: scope.projectId,
  title: 'Unsaved draft',
  content: 'Draft body',
  content_type: 'text',
  version: 1,
  status: 'enabled',
  processing_status: 'pending',
  created_at: '2026-09-08',
  updated_at: null,
};
const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

async function fixture({ contextStatus = 200, response = row }, run) {
  const previous = globalThis.window;
  const commands = [];
  const requests = [];
  const dependencies = {
    loadTrustedSession: async () => ({
      version: 1,
      api_base_url: config.apiBaseUrl,
      runtime_mode: 'cloud',
      credential_kind: 'cloud_bearer',
      credential: 'synthetic-test-only',
      expires_at: null,
    }),
    fetch: async (url, init) => {
      const path = new URL(url).pathname;
      requests.push(path);
      if (path === '/api/v1/workspace-context') {
        return contextStatus === 200
          ? json({
              context: {
                tenant_id: scope.tenantId,
                project_id: scope.projectId,
                revision: 7,
              },
            })
          : json({ detail: { code: 'fixture_context_error' } }, contextStatus);
      }
      if (path === '/api/v1/auth/me') return json({ user_id: 'actor-1' });
      assert.equal(path, '/api/v1/memories/');
      assert.equal(init.method, 'POST');
      return json(commands.length === 1 ? response : row, 201);
    },
  };
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        invoke: async (name, input) => {
          if (name === 'cloud_request_cancel') return;
          assert.equal(name, 'cloud_request');
          commands.push(input.request);
          return executeVaultBoundCloudRequest(input.request, dependencies);
        },
      },
    },
  };
  const controller = createCloudMemoriesController({
    authority,
    listClient: { load: async () => list },
    client: createDesktopCloudMemoryHttpV2(config),
  });
  try {
    await controller.loadPage();
    controller.create();
    controller.setDraft({ title: 'Unsaved draft', content: 'Draft body' });
    await run({ controller, commands, requests, dependencies });
  } finally {
    controller.stop();
    if (previous === undefined) delete globalThis.window;
    else globalThis.window = previous;
  }
}

test('context 401 reaches the UI through the real main policy and HTTP client and clears identity', async () => {
  await fixture({ contextStatus: 401 }, async ({ controller, requests }) => {
    await controller.save();
    const state = controller.getSnapshot();
    assert.equal(state.error, 'contextChanged');
    assert.equal(state.list, null);
    assert.equal(state.draft, null);
    await controller.retryWrite();
    assert.deepEqual(requests, ['/api/v1/workspace-context']);
  });
});

for (const status of [401, 403, 404, 409, 500, 503]) {
  test(`context ${status} preserves its HTTP envelope for scoped and ordinary requests`, async () => {
    await fixture({ contextStatus: status }, async ({ controller, commands, dependencies }) => {
      await controller.save();
      for (const request of [commands[0], { path: '/api/v1/workspace-context', method: 'GET' }]) {
        assert.deepEqual(await executeVaultBoundCloudRequest(request, dependencies), {
          status,
          body: { detail: { code: 'fixture_context_error' } },
        });
      }
    });
  });
}

const malformed = [
  null,
  {},
  { ...row, project_id: '' },
  { ...row, project_id: 1 },
  { ...row, project_id: ' project-1 ' },
  { ...row, id: '' },
  { ...row, title: null },
  { ...row, version: -1 },
  { ...row, processing_status: '' },
];
for (const [index, response] of malformed.entries()) {
  test(`malformed successful receipt ${index} retains the original command for explicit retry`, async () => {
    await fixture({ response }, async ({ controller, commands, requests }) => {
      await controller.save();
      assert.equal(controller.getSnapshot().phase, 'uncertain');
      assert.equal(controller.getSnapshot().draft.content, 'Draft body');
      assert.notEqual(controller.getSnapshot().list, null);
      assert.equal(commands.length, 1);
      await controller.retryWrite();
      assert.equal(commands.length, 2);
      assert.deepEqual(commands[1], commands[0]);
      assert.equal(requests.filter((path) => path === '/api/v1/memories/').length, 2);
      assert.equal(controller.getSnapshot().phase, 'viewing');
      assert.equal(controller.getSnapshot().record.id, row.id);
    });
  });
}

test('canonical different project receipt still fails closed and cannot retry the old command', async () => {
  await fixture(
    { response: { ...row, project_id: 'other-project' } },
    async ({ controller, commands }) => {
      await controller.save();
      assert.equal(controller.getSnapshot().error, 'contextChanged');
      assert.equal(controller.getSnapshot().draft, null);
      assert.equal(controller.getSnapshot().list, null);
      await controller.retryWrite();
      assert.equal(commands.length, 1);
    },
  );
});
