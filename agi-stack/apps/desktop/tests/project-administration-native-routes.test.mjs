import assert from 'node:assert/strict';
import Module, { createRequire } from 'node:module';
import { test } from 'node:test';

process.env.NODE_PATH = new URL('../node_modules', import.meta.url).pathname;
Module._initPaths();

const require = createRequire(import.meta.url);
const distRoot =
  process.env.AGISTACK_PROJECT_ADMIN_TEST_DIST ??
  '/tmp/agistack-project-administration-test-dist';
const compiled = `${distRoot}/src/features/project-administration`;
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require(`${distRoot}/src/i18n.js`);
const { DesktopApiError } = require(`${distRoot}/src/api/client.js`);
const { createProjectSchemaClient } = require(`${compiled}/projectSchemaClient.js`);
const {
  createProjectMaintenanceClient,
} = require(`${compiled}/projectMaintenanceClient.js`);
const { createProjectSettingsClient } = require(`${compiled}/projectSettingsClient.js`);
const {
  createProjectSchemaController,
} = require(`${compiled}/projectSchemaController.js`);
const {
  createProjectMaintenanceController,
} = require(`${compiled}/projectMaintenanceController.js`);
const {
  createProjectSettingsController,
} = require(`${compiled}/projectSettingsController.js`);
const {
  buildProjectSchemaPresentation,
} = require(`${compiled}/projectSchemaPresentationModel.js`);
const {
  buildProjectMaintenancePresentation,
} = require(`${compiled}/projectMaintenancePresentationModel.js`);
const {
  buildProjectSettingsPresentation,
} = require(`${compiled}/projectSettingsPresentationModel.js`);
const {
  createProjectSchemaRouteModuleLoader,
} = require(`${compiled}/projectSchemaRouteModule.js`);
const {
  createProjectMaintenanceRouteModuleLoader,
} = require(`${compiled}/projectMaintenanceRouteModule.js`);
const {
  createProjectSettingsRouteModuleLoader,
} = require(`${compiled}/projectSettingsRouteModule.js`);
const {
  PROJECT_ADMINISTRATION_CAPABILITY_IDS,
  createProjectAdministrationCapabilityClients,
  loadProjectAdministrationCapabilities,
} = require(`${compiled}/projectAdministrationCapabilityAuthority.js`);

const cloudConfig = Object.freeze({
  apiBaseUrl: 'https://cloud.memstack.test',
  deviceAuthorizationBaseUrl: 'https://cloud.memstack.test',
  apiKey: 'trusted-session',
  localApiToken: 'must-not-cross-cloud',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  mode: 'cloud',
  workspaceRoot: '/workspace',
});
const localConfig = Object.freeze({
  ...cloudConfig,
  apiBaseUrl: 'http://127.0.0.1:43117',
  apiKey: 'local-session',
  localApiToken: 'private-launch',
  mode: 'local',
});
const cloudScope = Object.freeze({
  authority: 'cloud',
  tenantId: 'tenant-1',
  projectId: 'project-1',
});
const localScope = Object.freeze({ ...cloudScope, authority: 'local' });

test('three project administration clients use trusted-session authority and role-scoped actions', async () => {
  const requests = [];
  await withFetch(
    async (url, init = {}) => {
      requests.push({ url: String(url), init });
      return authorityResponse(String(url), init);
    },
    async () => {
      const [schema, maintenance, settings] = await Promise.all([
        createProjectSchemaClient(cloudConfig).load(cloudScope),
        createProjectMaintenanceClient(cloudConfig).load(cloudScope),
        createProjectSettingsClient(cloudConfig).load(cloudScope),
      ]);
      assert.equal(schema.scopeRevision, 11);
      assert.equal(schema.membershipRole, 'owner');
      assert.equal(schema.availability, 'degraded');
      assert.equal(schema.reasonCode, 'project_schema_export_file_ipc_unavailable');
      assert.equal(schema.allowedActions.includes('create-entity-type'), true);
      assert.equal(schema.allowedActions.includes('export'), false);
      assert.equal(schema.entityTypes[0].name, 'Person');
      assert.equal(schema.edgeTypes[0].name, 'KNOWS');
      assert.equal(schema.mappings[0].sourceType, 'Person');

      assert.equal(maintenance.scopeRevision, 11);
      assert.equal(maintenance.availability, 'degraded');
      assert.equal(
        maintenance.reasonCode,
        'project_maintenance_export_file_ipc_unavailable',
      );
      assert.equal(maintenance.allowedActions.includes('deduplicate'), true);
      assert.equal(maintenance.allowedActions.includes('export'), false);
      assert.equal(maintenance.stats.entityCount, 3);
      assert.equal(maintenance.embeddingStatus.currentDimension, 1536);

      assert.equal(settings.scopeRevision, 11);
      assert.equal(settings.availability, 'available');
      assert.equal(settings.reasonCode, null);
      assert.equal(settings.allowedActions.includes('delete'), true);
      assert.equal(settings.project.name, 'Project One');
      assert.equal(settings.sandbox?.status, 'running');
      assert.equal(settings.sandboxStats?.memoryUsage, 128);
      assert.equal(JSON.stringify(settings).includes('/private/secret-workspace'), false);
    },
  );

  assert.equal(requests.length > 0, true);
  for (const request of requests) {
    const headers = new Headers(request.init.headers);
    assert.equal(headers.get('Authorization'), 'Bearer trusted-session');
    assert.equal(headers.has('X-Agistack-Launch'), false);
    assert.equal(request.init.credentials, 'omit');
  }
});

test('project administration rejects the legacy id-only auth identity contract', async () => {
  await withFetch(
    async (url, init = {}) => {
      if (new URL(String(url)).pathname === '/api/v1/auth/me') {
        return json({ id: 'user-1', email: 'owner@example.test', name: 'Owner' });
      }
      return authorityResponse(String(url), init);
    },
    async () => {
      for (const client of [
        createProjectSchemaClient(cloudConfig),
        createProjectMaintenanceClient(cloudConfig),
        createProjectSettingsClient(cloudConfig),
      ]) {
        await assert.rejects(client.load(cloudScope), (error) => {
          assert.equal(error instanceof DesktopApiError, true);
          assert.equal(reasonCode(error), 'project_administration_scope_contract_invalid');
          return true;
        });
      }
    },
  );
});

test('three Local project administration clients fail closed before network access', async () => {
  let fetchCalls = 0;
  await withFetch(
    async () => {
      fetchCalls += 1;
      throw new Error('Local authority must fail before Cloud fetch');
    },
    async () => {
      const cases = [
        [
          createProjectSchemaClient(localConfig),
          'local_project_schema_authority_unavailable',
        ],
        [
          createProjectMaintenanceClient(localConfig),
          'local_project_maintenance_authority_unavailable',
        ],
        [
          createProjectSettingsClient(localConfig),
          'local_project_settings_authority_unavailable',
        ],
      ];
      for (const [client, expectedReason] of cases) {
        await assert.rejects(client.load(localScope), (error) => {
          assert.equal(error instanceof DesktopApiError, true);
          assert.equal(error.status, 501);
          assert.equal(reasonCode(error), expectedReason);
          return true;
        });
      }
    },
  );
  assert.equal(fetchCalls, 0);
});

test('Project Administration capability authority observes scoped Cloud clients', async () => {
  const factoryClients = createProjectAdministrationCapabilityClients(cloudConfig);
  assert.deepEqual(
    Object.keys(factoryClients).sort(),
    [...PROJECT_ADMINISTRATION_CAPABILITY_IDS].sort(),
  );

  const projection = await loadProjectAdministrationCapabilities(
    projectAdministrationCapabilityClients(),
    cloudConfig,
  );
  assert.equal(projection['project-project-schema'].availability, 'degraded');
  assert.equal(
    projection['project-project-schema'].reason_code,
    'project_schema_export_file_ipc_unavailable',
  );
  assert.equal(projection['project-project-maintenance'].availability, 'degraded');
  assert.equal(projection['project-project-settings'].availability, 'available');
  for (const capabilityId of PROJECT_ADMINISTRATION_CAPABILITY_IDS) {
    assert.equal(projection[capabilityId].authority_revision, 11, capabilityId);
    assert.equal(projection[capabilityId].contract_version, '4.0.0', capabilityId);
    assert.deepEqual(projection[capabilityId].scope, {
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      workspace_id: null,
      instance_id: null,
    });
  }
});

test('Project Administration capability authority declares stable Local unavailability', async () => {
  let calls = 0;
  const clients = Object.fromEntries(
    PROJECT_ADMINISTRATION_CAPABILITY_IDS.map((capabilityId) => [
      capabilityId,
      {
        async load() {
          calls += 1;
          throw new Error('Local authority must fail before network access');
        },
      },
    ]),
  );
  const projection = await loadProjectAdministrationCapabilities(clients, localConfig);
  assert.equal(calls, 0);
  assert.equal(
    projection['project-project-schema'].reason_code,
    'local_project_schema_authority_unavailable',
  );
  assert.equal(
    projection['project-project-maintenance'].reason_code,
    'local_project_maintenance_authority_unavailable',
  );
  assert.equal(
    projection['project-project-settings'].reason_code,
    'local_project_settings_authority_unavailable',
  );
  for (const capabilityId of PROJECT_ADMINISTRATION_CAPABILITY_IDS) {
    assert.equal(projection[capabilityId].availability, 'unavailable', capabilityId);
    assert.equal(projection[capabilityId].authority_revision, 0, capabilityId);
    assert.deepEqual(projection[capabilityId].allowed_actions, [], capabilityId);
  }
});

test('Project Administration capability authority rejects mismatched Cloud observations', async () => {
  const clients = projectAdministrationCapabilityClients();
  clients['project-project-settings'] = {
    async load() {
      return settingsSnapshot({ ...cloudScope, projectId: 'other-project' });
    },
  };
  const projection = await loadProjectAdministrationCapabilities(clients, cloudConfig);
  assert.equal(
    projection['project-project-settings'].reason_code,
    'project_settings_authority_contract_invalid',
  );
  assert.equal(projection['project-project-settings'].availability, 'unavailable');
});

test('project administration controllers preserve stale data and classify forbidden conflict retry', async () => {
  const schemaDeferred = Promise.withResolvers();
  let schemaCalls = 0;
  const schema = createProjectSchemaController({
    client: {
      load: async () => {
        schemaCalls += 1;
        if (schemaCalls === 1) return schemaSnapshot();
        return schemaDeferred.promise;
      },
      createEntityType: async () => {},
      updateEntityType: async () => {},
      deleteEntityType: async () => {},
      createEdgeType: async () => {},
      updateEdgeType: async () => {},
      deleteEdgeType: async () => {},
      createMapping: async () => {},
      deleteMapping: async () => {},
    },
    initialScope: cloudScope,
  });
  await schema.load(cloudScope);
  const schemaReload = schema.load(cloudScope);
  assert.equal(schema.getSnapshot().state, 'stale');
  assert.equal(schema.getSnapshot().entityTypes[0].name, 'Person');
  schemaDeferred.resolve(schemaSnapshot());
  await schemaReload;
  assert.equal(schema.getSnapshot().state, 'degraded');

  const maintenance = createProjectMaintenanceController({
    client: maintenanceClientRejecting(new DesktopApiError('forbidden', 403, {})),
    initialScope: cloudScope,
  });
  await maintenance.load(cloudScope);
  assert.equal(maintenance.getSnapshot().state, 'forbidden');
  assert.equal(maintenance.getSnapshot().retryVisible, false);

  const settings = createProjectSettingsController({
    client: settingsClientRejecting(
      new DesktopApiError('conflict', 409, { reason_code: 'project_settings_conflict' }),
    ),
    initialScope: cloudScope,
  });
  await settings.load(cloudScope);
  assert.equal(settings.getSnapshot().state, 'conflict');
  assert.equal(settings.getSnapshot().reasonCode, 'project_settings_conflict');
  assert.equal(settings.getSnapshot().retryVisible, true);

  const retryable = createProjectMaintenanceController({
    client: maintenanceClientRejecting(
      new DesktopApiError('temporarily unavailable', 503, {
        reason_code: 'project_maintenance_temporarily_unavailable',
      }),
    ),
    initialScope: cloudScope,
  });
  await retryable.load(cloudScope);
  assert.equal(retryable.getSnapshot().state, 'error');
  assert.equal(retryable.getSnapshot().retryVisible, true);
});

test('three project administration route modules publish native deep-link surfaces and close bad scope', async () => {
  const cases = [
    [
      createProjectSchemaRouteModuleLoader,
      'project-project-schema',
      schemaSnapshot(),
      buildProjectSchemaPresentation,
    ],
    [
      createProjectMaintenanceRouteModuleLoader,
      'project-project-maintenance',
      maintenanceSnapshot(),
      buildProjectMaintenancePresentation,
    ],
    [
      createProjectSettingsRouteModuleLoader,
      'project-project-settings',
      settingsSnapshot(),
      buildProjectSettingsPresentation,
    ],
  ];
  for (const [factory, routeId, snapshot, buildPresentation] of cases) {
    let bindingCalls = 0;
    const module = await factory({
      createBinding(context) {
        bindingCalls += 1;
        const scope = Object.freeze({
          authority: 'cloud',
          tenantId: context.tenantId,
          projectId: context.projectId,
        });
        return { controller: readyController(buildPresentation, snapshot, scope), scope };
      },
    })();
    assert.deepEqual(
      {
        routeId: module.routeId,
        capability: module.capability,
        localPolicy: module.localPolicy,
        disposition: module.disposition,
        availability: module.availability,
        reasonCode: module.reasonCode,
        contentPolicy: module.contentPolicy,
      },
      {
        routeId,
        capability: routeId,
        localPolicy: 'native_equivalent',
        disposition: 'implemented',
        availability: 'available',
        reasonCode: null,
        contentPolicy: 'route_content',
      },
    );
    const markup = render(module, { tenantId: 'tenant-1', projectId: 'project-1' });
    assert.equal(bindingCalls, 1);
    assert.match(markup, new RegExp(routeId));
    assert.doesNotMatch(markup, /iframe|webview|open in browser/iu);

    const unavailable = render(module, { tenantId: 'tenant-1' });
    assert.equal(bindingCalls, 1);
    assert.match(unavailable, /route_context_unavailable/);
  }
});

function authorityResponse(url, init = {}) {
  const parsed = new URL(url);
  const path = parsed.pathname;
  if (path === '/api/v1/workspace-context') {
    return json({
      context: {
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        revision: 11,
        updated_at: '2026-08-05T00:00:00Z',
      },
      membership_role: 'member',
    });
  }
  if (path === '/api/v1/auth/me') {
    return json({ user_id: 'user-1', email: 'owner@example.test', name: 'Owner' });
  }
  if (path === '/api/v1/projects/project-1/members') {
    return json({ members: [memberPayload()], total: 1 });
  }
  if (path === '/api/v1/projects/project-1/schema/entities') {
    return json([schemaTypePayload('entity-1', 'Person')]);
  }
  if (path === '/api/v1/projects/project-1/schema/edges') {
    return json([schemaTypePayload('edge-1', 'KNOWS')]);
  }
  if (path === '/api/v1/projects/project-1/schema/mappings') {
    return json([mappingPayload()]);
  }
  if (path === '/api/v1/maintenance/status') return json(maintenanceStatusPayload());
  if (path === '/api/v1/data/stats') {
    return json({ entity_count: 3, episodic_count: 4, community_count: 1, edge_count: 2 });
  }
  if (path === '/api/v1/maintenance/embeddings/status') {
    return json(embeddingPayload());
  }
  if (path === '/api/v1/projects/project-1') return json(projectPayload());
  if (path === '/api/v1/projects/project-1/sandbox') return json(sandboxPayload());
  if (path === '/api/v1/projects/project-1/sandbox/stats') return json(sandboxStatsPayload());
  throw new Error(`unexpected request ${init.method ?? 'GET'} ${path}`);
}

function memberPayload(overrides = {}) {
  return {
    user_id: 'user-1',
    email: 'owner@example.test',
    name: 'Owner',
    role: 'owner',
    permissions: { admin: true },
    created_at: '2026-08-05T00:00:00Z',
    ...overrides,
  };
}

function schemaTypePayload(id, name) {
  return {
    id,
    project_id: 'project-1',
    name,
    description: null,
    schema: {},
    status: 'ENABLED',
    source: 'user',
    created_at: '2026-08-05T00:00:00Z',
    updated_at: null,
  };
}

function mappingPayload() {
  return {
    id: 'mapping-1',
    project_id: 'project-1',
    source_type: 'Person',
    target_type: 'Person',
    edge_type: 'KNOWS',
    status: 'ENABLED',
    source: 'user',
    created_at: '2026-08-05T00:00:00Z',
  };
}

function maintenanceStatusPayload() {
  return {
    stats: { entities: 3, episodes: 4, communities: 1, old_episodes: 0 },
    recommendations: [],
    last_checked: '2026-08-05T00:00:00Z',
  };
}

function embeddingPayload() {
  return {
    current_provider: 'OpenAI',
    current_dimension: 1536,
    existing_dimension: 1536,
    is_compatible: true,
    missing_embeddings: 0,
  };
}

function projectPayload() {
  return {
    id: 'project-1',
    tenant_id: 'tenant-1',
    name: 'Project One',
    description: null,
    owner_id: 'user-1',
    member_ids: ['user-1'],
    memory_rules: {
      max_episodes: 1000,
      retention_days: 30,
      auto_refresh: true,
      refresh_interval: 24,
    },
    graph_config: {
      layout_algorithm: 'force-directed',
      node_size: 20,
      edge_width: 2,
      colors: {},
      animations: true,
      max_nodes: 1000,
      max_edges: 10000,
      similarity_threshold: 0.7,
      community_detection: true,
    },
    sandbox_config: {
      sandbox_type: 'local',
      local_config: { workspace_path: '/private/secret-workspace' },
    },
    is_public: false,
    agent_conversation_mode: 'single_agent',
    created_at: '2026-08-05T00:00:00Z',
    updated_at: null,
  };
}

function sandboxPayload() {
  return {
    sandbox_id: 'sandbox-1',
    project_id: 'project-1',
    tenant_id: 'tenant-1',
    status: 'running',
    is_healthy: true,
    endpoint: 'wss://sandbox.memstack.test/private',
    desktop_url: 'https://sandbox.memstack.test/desktop',
    terminal_url: 'https://sandbox.memstack.test/terminal',
    created_at: '2026-08-05T00:00:00Z',
  };
}

function sandboxStatsPayload() {
  return {
    project_id: 'project-1',
    sandbox_id: 'sandbox-1',
    status: 'running',
    cpu_percent: 2,
    memory_usage: 128,
    memory_limit: 1024,
    memory_percent: 12.5,
    pids: 3,
    collected_at: '2026-08-05T00:00:00Z',
  };
}

function snapshotBase(data, overrides = {}) {
  return {
    scope: cloudScope,
    scopeRevision: 11,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    contractVersion: '4.0.0',
    allowedActions: ['view'],
    membershipRole: 'owner',
    data,
    ...data,
    ...overrides,
  };
}

function schemaSnapshot(scope = cloudScope) {
  const data = {
    membershipRole: 'owner',
    entityTypes: [schemaTypeModel('entity-1', 'Person')],
    edgeTypes: [schemaTypeModel('edge-1', 'KNOWS')],
    mappings: [
      {
        id: 'mapping-1',
        projectId: scope.projectId,
        sourceType: 'Person',
        targetType: 'Person',
        edgeType: 'KNOWS',
        status: 'ENABLED',
        source: 'user',
        createdAt: '2026-08-05T00:00:00Z',
      },
    ],
  };
  return snapshotBase(data, {
    scope,
    availability: 'degraded',
    reasonCode: 'project_schema_export_file_ipc_unavailable',
    allowedActions: ['view', 'list-entity-types'],
  });
}

function schemaTypeModel(id, name) {
  return {
    id,
    projectId: 'project-1',
    name,
    description: null,
    schema: {},
    status: 'ENABLED',
    source: 'user',
    createdAt: '2026-08-05T00:00:00Z',
    updatedAt: null,
  };
}

function maintenanceSnapshot(scope = cloudScope) {
  const data = {
    membershipRole: 'owner',
    stats: { entityCount: 3, episodeCount: 4, communityCount: 1, edgeCount: 2 },
    maintenanceStatus: {
      entities: 3,
      episodes: 4,
      communities: 1,
      oldEpisodes: 0,
      recommendations: [],
      lastChecked: '2026-08-05T00:00:00Z',
    },
    embeddingStatus: {
      currentProvider: 'OpenAI',
      currentDimension: 1536,
      existingDimension: 1536,
      compatible: true,
      missingEmbeddings: 0,
    },
  };
  return snapshotBase(data, {
    scope,
    availability: 'degraded',
    reasonCode: 'project_maintenance_export_file_ipc_unavailable',
    allowedActions: ['view', 'deduplicate'],
  });
}

function settingsSnapshot(scope = cloudScope) {
  const data = {
    membershipRole: 'owner',
    project: {
      id: scope.projectId,
      tenantId: scope.tenantId,
      name: 'Project One',
      description: null,
      ownerId: 'user-1',
      isPublic: false,
      memoryRules: {
        maxEpisodes: 1000,
        retentionDays: 30,
        autoRefresh: true,
        refreshInterval: 24,
      },
      graphConfig: {
        maxNodes: 1000,
        maxEdges: 10000,
        similarityThreshold: 0.7,
        communityDetection: true,
      },
      sandboxType: 'cloud',
      conversationMode: 'single_agent',
      createdAt: '2026-08-05T00:00:00Z',
      updatedAt: null,
    },
    sandbox: null,
    sandboxStats: null,
  };
  return snapshotBase(data, { scope, allowedActions: ['view', 'update', 'delete'] });
}

function projectAdministrationCapabilityClients() {
  return {
    'project-project-schema': { load: async () => schemaSnapshot() },
    'project-project-maintenance': { load: async () => maintenanceSnapshot() },
    'project-project-settings': { load: async () => settingsSnapshot() },
  };
}

function maintenanceClientRejecting(error) {
  return {
    load: async () => {
      throw error;
    },
    incrementalRefresh: async () => {},
    deduplicate: async () => {},
    invalidateEdges: async () => {},
    rebuildCommunities: async () => {},
    rebuildEmbeddings: async () => {},
  };
}

function settingsClientRejecting(error) {
  return {
    load: async () => {
      throw error;
    },
    update: async () => {},
    deleteProject: async () => {},
    restartSandbox: async () => {},
    terminateSandbox: async () => {},
  };
}

function readyController(buildPresentation, snapshot, scope) {
  const scopedSnapshot = { ...snapshot, scope };
  const model = buildPresentation({
    state: snapshot.availability === 'degraded' ? 'degraded' : 'ready',
    scope,
    snapshot: scopedSnapshot,
    reasonCode: snapshot.reasonCode,
    retryVisible: false,
    busyAction: null,
  });
  return {
    subscribe() {
      return () => {};
    },
    getSnapshot() {
      return model;
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

function reasonCode(error) {
  return error?.payload?.reason_code ?? error?.message;
}

async function withFetch(implementation, action) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = implementation;
  try {
    await action();
  } finally {
    globalThis.fetch = originalFetch;
  }
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
