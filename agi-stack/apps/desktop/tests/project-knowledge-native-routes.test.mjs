import assert from 'node:assert/strict';
import Module, { createRequire } from 'node:module';
import { test } from 'node:test';

process.env.NODE_PATH = new URL('../node_modules', import.meta.url).pathname;
Module._initPaths();

const require = createRequire(import.meta.url);
const compiled =
  '/tmp/agistack-project-knowledge-test-dist/src/features/project-knowledge';
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const {
  I18nProvider,
} = require('/tmp/agistack-project-knowledge-test-dist/src/i18n.js');

const { createProjectTeamClient } = require(`${compiled}/projectTeamClient.js`);
const { createProjectMemoriesClient } = require(
  `${compiled}/projectMemoriesClient.js`,
);
const { createProjectEntitiesClient } = require(
  `${compiled}/projectEntitiesClient.js`,
);
const { createProjectCommunitiesClient } = require(
  `${compiled}/projectCommunitiesClient.js`,
);
const { createProjectGraphClient } = require(
  `${compiled}/projectGraphClient.js`,
);
const {
  createProjectKnowledgeCapabilityClients,
  loadProjectKnowledgeCapabilities,
} = require(`${compiled}/projectKnowledgeCapabilityAuthority.js`);
const { createProjectMemoriesController } = require(
  `${compiled}/projectMemoriesController.js`,
);
const { buildProjectMemoriesPresentation } = require(
  `${compiled}/projectMemoriesPresentationModel.js`,
);
const { createProjectTeamRouteModuleLoader } = require(
  `${compiled}/projectTeamRouteModule.js`,
);
const { createProjectMemoriesRouteModuleLoader } = require(
  `${compiled}/projectMemoriesRouteModule.js`,
);
const { createProjectEntitiesRouteModuleLoader } = require(
  `${compiled}/projectEntitiesRouteModule.js`,
);
const { createProjectCommunitiesRouteModuleLoader } = require(
  `${compiled}/projectCommunitiesRouteModule.js`,
);
const { createProjectGraphRouteModuleLoader } = require(
  `${compiled}/projectGraphRouteModule.js`,
);

const cloudConfig = Object.freeze({
  apiBaseUrl: 'https://cloud.memstack.test',
  deviceAuthorizationBaseUrl: 'https://cloud.memstack.test',
  apiKey: 'trusted-session',
  localApiToken: '',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: '',
  mode: 'cloud',
  workspaceRoot: '',
});
const localConfig = Object.freeze({
  ...cloudConfig,
  apiBaseUrl: 'http://127.0.0.1:43117',
  deviceAuthorizationBaseUrl: 'http://127.0.0.1:43117',
  localApiToken: 'private-launch',
  mode: 'local',
});
const cloudScope = Object.freeze({
  authority: 'cloud',
  tenantId: 'tenant-1',
  projectId: 'project-1',
});
const localScope = Object.freeze({ ...cloudScope, authority: 'local' });

test('project knowledge cloud clients use trusted-session transport and validate observed scope', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, init = {}) => {
    requests.push({ url: String(url), init });
    const path = new URL(String(url)).pathname;
    if (path === '/api/v1/workspace-context') {
      return jsonResponse({
        context: {
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          revision: 7,
          updated_at: '2026-08-05T00:00:00Z',
        },
        membership_role: 'member',
      });
    }
    if (path === '/api/v1/auth/me') {
      return jsonResponse({
        id: 'user-1',
        email: 'owner@example.test',
        name: 'Owner',
      });
    }
    if (path === '/api/v1/projects/project-1/members') {
      return jsonResponse({
        members: [
          {
            user_id: 'user-1',
            email: 'owner@example.test',
            name: 'Owner',
            role: 'owner',
            permissions: { read: true, write: true },
            created_at: '2026-08-05T00:00:00Z',
          },
        ],
        total: 1,
      });
    }
    if (path === '/api/v1/agent/definitions') {
      return jsonResponse({ items: [], total: 0 });
    }
    if (path === '/api/v1/memories/') {
      return jsonResponse({ memories: [], total: 0, page: 1, page_size: 50 });
    }
    if (path === '/api/v1/graph/entities/') {
      return jsonResponse({ entities: [], total: 0, limit: 50, offset: 0 });
    }
    if (path === '/api/v1/graph/entities/types') {
      return jsonResponse({ entity_types: [], total: 0 });
    }
    if (path === '/api/v1/graph/communities/') {
      return jsonResponse({ communities: [], total: 0, limit: 50, offset: 0 });
    }
    if (path === '/api/v1/graph/memory/graph') {
      return jsonResponse({ elements: { nodes: [], edges: [] } });
    }
    throw new Error(`unexpected request: ${String(url)}`);
  };
  try {
    const snapshots = await Promise.all([
      createProjectTeamClient(cloudConfig).load(cloudScope),
      createProjectMemoriesClient(cloudConfig).load(cloudScope),
      createProjectEntitiesClient(cloudConfig).load(cloudScope),
      createProjectCommunitiesClient(cloudConfig).load(cloudScope),
      createProjectGraphClient(cloudConfig).load(cloudScope),
    ]);
    assert.deepEqual(
      snapshots.map((snapshot) => snapshot.scopeRevision),
      [7, 7, 7, 7, 7],
    );
    assert.equal(snapshots[0].allowedActions.includes('update-role'), true);
    assert.equal(snapshots[1].availability, 'degraded');
    assert.equal(snapshots[2].availability, 'available');
    assert.equal(snapshots[3].availability, 'degraded');
    assert.equal(snapshots[4].availability, 'degraded');
  } finally {
    globalThis.fetch = originalFetch;
  }
  for (const request of requests) {
    const headers = new Headers(request.init.headers);
    assert.equal(headers.get('Authorization'), 'Bearer trusted-session');
    assert.equal(headers.get('X-Agistack-Launch'), null);
    assert.equal(request.init.credentials, 'omit');
  }
});

test('project knowledge local clients fail closed with stable reason codes before network access', async () => {
  const originalFetch = globalThis.fetch;
  let fetchCalls = 0;
  globalThis.fetch = async () => {
    fetchCalls += 1;
    throw new Error('local authority must fail before fetch');
  };
  try {
    const cases = [
      [
        createProjectTeamClient(localConfig),
        'local_project_team_authority_unavailable',
      ],
      [
        createProjectMemoriesClient(localConfig),
        'local_project_memories_authority_unavailable',
      ],
      [
        createProjectEntitiesClient(localConfig),
        'local_project_entities_authority_unavailable',
      ],
      [
        createProjectCommunitiesClient(localConfig),
        'local_project_communities_authority_unavailable',
      ],
      [
        createProjectGraphClient(localConfig),
        'local_project_graph_authority_unavailable',
      ],
    ];
    for (const [client, reasonCode] of cases) {
      await assert.rejects(client.load(localScope), (error) => {
        assert.equal(error.status, 501);
        assert.equal(error.payload.reason_code, reasonCode);
        return true;
      });
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(fetchCalls, 0);
});

test('project knowledge capability authority observes Cloud and never probes static clients in Local', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, init = {}) => {
    requests.push({ url: String(url), init });
    const path = new URL(String(url)).pathname;
    if (path === '/api/v1/workspace-context') {
      return jsonResponse({
        context: {
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          revision: 11,
          updated_at: '2026-08-05T00:00:00Z',
        },
        membership_role: 'owner',
      });
    }
    if (path === '/api/v1/auth/me') {
      return jsonResponse({
        id: 'user-1',
        email: 'owner@example.test',
        name: 'Owner',
      });
    }
    if (path === '/api/v1/projects/project-1/members') {
      return jsonResponse({
        members: [
          {
            user_id: 'user-1',
            email: 'owner@example.test',
            name: 'Owner',
            role: 'owner',
            permissions: { read: true, write: true },
            created_at: '2026-08-05T00:00:00Z',
          },
        ],
        total: 1,
      });
    }
    if (path === '/api/v1/agent/definitions')
      return jsonResponse({ items: [], total: 0 });
    if (path === '/api/v1/memories/') {
      return jsonResponse({ memories: [], total: 0, page: 1, page_size: 50 });
    }
    if (path === '/api/v1/graph/entities/') {
      return jsonResponse({ entities: [], total: 0, limit: 50, offset: 0 });
    }
    if (path === '/api/v1/graph/entities/types') {
      return jsonResponse({ entity_types: [], total: 0 });
    }
    if (path === '/api/v1/graph/communities/') {
      return jsonResponse({ communities: [], total: 0, limit: 50, offset: 0 });
    }
    if (path === '/api/v1/graph/memory/graph') {
      return jsonResponse({ elements: { nodes: [], edges: [] } });
    }
    throw new Error(`unexpected request: ${String(url)}`);
  };
  try {
    const cloud = await loadProjectKnowledgeCapabilities(
      createProjectKnowledgeCapabilityClients(cloudConfig),
      cloudConfig,
    );
    assert.equal(cloud['project-project-team'].availability, 'available');
    assert.equal(cloud['project-project-memories'].availability, 'degraded');
    assert.equal(cloud['project-project-graph'].authority_revision, 11);

    let localLoadCalls = 0;
    const local = await loadProjectKnowledgeCapabilities(
      Object.fromEntries(
        [
          'project-project-team',
          'project-project-memories',
          'project-project-entities',
          'project-project-communities',
          'project-project-graph',
        ].map((routeId) => [
          routeId,
          {
            async load() {
              localLoadCalls += 1;
              throw new Error('Local static authority must not be probed');
            },
          },
        ]),
      ),
      localConfig,
    );
    assert.equal(localLoadCalls, 0);
    assert.equal(
      local['project-project-team'].reason_code,
      'local_project_team_authority_unavailable',
    );
    assert.equal(
      local['project-project-graph'].reason_code,
      'local_project_graph_authority_unavailable',
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.ok(requests.length > 0);
});

test('project knowledge clients reject stale observed scope and accept only structured reason codes', async () => {
  const originalFetch = globalThis.fetch;
  let responseIndex = 0;
  globalThis.fetch = async () => {
    responseIndex += 1;
    if (responseIndex === 1) {
      return jsonResponse({
        context: {
          tenant_id: 'tenant-1',
          project_id: 'project-stale',
          revision: 8,
          updated_at: '2026-08-05T00:00:00Z',
        },
        membership_role: 'member',
      });
    }
    return jsonResponse(
      { detail: { code: 'project_memories_forbidden' } },
      403,
    );
  };
  try {
    await assert.rejects(
      createProjectMemoriesClient(cloudConfig).load(cloudScope),
      (error) =>
        error.payload.reason_code === 'project_knowledge_scope_conflict',
    );
    responseIndex = 0;
    globalThis.fetch = async (url) => {
      const path = new URL(String(url)).pathname;
      if (path === '/api/v1/workspace-context') {
        return jsonResponse({
          context: {
            tenant_id: 'tenant-1',
            project_id: 'project-1',
            revision: 9,
            updated_at: '2026-08-05T00:00:00Z',
          },
          membership_role: 'member',
        });
      }
      return jsonResponse(
        { detail: { code: 'project_memories_forbidden' } },
        403,
      );
    };
    await assert.rejects(
      createProjectMemoriesClient(cloudConfig).load(cloudScope),
      (error) => error.message === 'project_memories_forbidden',
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('project memories controller ignores stale completions and maps forbidden state', async () => {
  const deferredFirst = deferred();
  const deferredSecond = deferred();
  let call = 0;
  const controller = createProjectMemoriesController({
    authority: 'cloud',
    client: {
      load() {
        call += 1;
        return call === 1 ? deferredFirst.promise : deferredSecond.promise;
      },
    },
    initialScope: cloudScope,
  });
  const scopeTwo = Object.freeze({ ...cloudScope, projectId: 'project-2' });
  const firstLoad = controller.load(cloudScope);
  const secondLoad = controller.load(scopeTwo);
  deferredSecond.resolve(memorySnapshot(scopeTwo, 'second'));
  await secondLoad;
  deferredFirst.resolve(memorySnapshot(cloudScope, 'first'));
  await firstLoad;
  assert.equal(controller.getSnapshot().scope.projectId, 'project-2');
  assert.equal(controller.getSnapshot().items[0].title, 'second');

  const forbidden = createProjectMemoriesController({
    authority: 'cloud',
    client: {
      async load() {
        const error = new Error('project_memories_forbidden');
        error.status = 403;
        error.payload = { reason_code: 'project_memories_forbidden' };
        throw error;
      },
    },
    initialScope: cloudScope,
  });
  await forbidden.load(cloudScope);
  assert.equal(forbidden.getSnapshot().state, 'forbidden');
  assert.equal(
    forbidden.getSnapshot().reasonCode,
    'project_memories_forbidden',
  );
});

test('five project knowledge route modules render native surfaces and fail closed on bad scope', async () => {
  const cases = [
    [createProjectTeamRouteModuleLoader, 'project-project-team'],
    [createProjectMemoriesRouteModuleLoader, 'project-project-memories'],
    [createProjectEntitiesRouteModuleLoader, 'project-project-entities'],
    [createProjectCommunitiesRouteModuleLoader, 'project-project-communities'],
    [createProjectGraphRouteModuleLoader, 'project-project-graph'],
  ];
  for (const [factory, routeId] of cases) {
    let bindingCalls = 0;
    const module = await factory({
      createBinding(context) {
        bindingCalls += 1;
        const scope = Object.freeze({
          authority: 'cloud',
          tenantId: context.tenantId,
          projectId: context.projectId,
        });
        return { controller: readyController(scope, routeId), scope };
      },
    })();
    assert.equal(module.routeId, routeId);
    const markup = render(module, {
      tenantId: 'tenant-1',
      projectId: 'project-1',
    });
    assert.equal(bindingCalls, 1);
    assert.match(markup, new RegExp(routeId));
    assert.doesNotMatch(markup, /iframe|webview|open in browser/iu);
    const unavailable = render(module, { tenantId: 'tenant-1' });
    assert.equal(bindingCalls, 1);
    assert.match(unavailable, /route_context_unavailable/);
  }
});

function memorySnapshot(scope, title) {
  return {
    scope,
    scopeRevision: 1,
    authority: 'cloud',
    availability: 'degraded',
    reasonCode: 'project_memories_export_file_ipc_unavailable',
    allowedActions: ['view', 'list', 'create', 'update', 'delete', 'reprocess'],
    memories: [
      {
        id: `memory-${title}`,
        projectId: scope.projectId,
        title,
        content: '',
        contentType: 'text',
        version: 1,
        status: 'ENABLED',
        processingStatus: 'COMPLETED',
        createdAt: '2026-08-05T00:00:00Z',
        updatedAt: null,
      },
    ],
    total: 1,
  };
}

function readyController(scope, routeId) {
  const model = buildProjectMemoriesPresentation({
    kind: 'snapshot',
    snapshot: memorySnapshot(scope, routeId),
  });
  return {
    subscribe() {
      return () => {};
    },
    getSnapshot() {
      return { ...model, routeId };
    },
    async load() {},
    async retry() {},
    cancel() {},
    stop() {},
  };
}

function render(module, context) {
  return renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(module.Surface, { context, module }),
    ),
  );
}

function deferred() {
  let resolve;
  const promise = new Promise((resolver) => {
    resolve = resolver;
  });
  return { promise, resolve };
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
