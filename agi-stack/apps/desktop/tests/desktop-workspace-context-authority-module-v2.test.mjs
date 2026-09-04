import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { desktopArtifactContentAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopArtifactContentAuthorityModuleV2.js',
);
const { desktopAutomationAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopAutomationAuthorityModuleV2.js',
);
const { desktopNewTaskFlowAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopNewTaskFlowAuthorityModuleV2.js',
);
const { desktopNewThreadCreationAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopNewThreadCreationAuthorityModuleV2.js',
);
const { desktopProjectSearchAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopProjectSearchAuthorityModuleV2.js',
);

const { desktopRuntimePoolAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopRuntimePoolAuthorityModuleV2.js',
);
const { desktopRuntimeClustersAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopRuntimeClustersAuthorityModuleV2.js',
);

const { desktopRuntimeInstancesAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopRuntimeInstancesAuthorityModuleV2.js',
);
const { desktopRuntimeDeploymentsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopRuntimeDeploymentsAuthorityModuleV2.js',
);
const { desktopProjectPlaybooksEventsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopProjectPlaybooksEventsAuthorityModuleV2.js',
);
const { desktopSessionArtifactActionAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopSessionArtifactActionAuthorityModuleV2.js',
);
const { desktopSessionRunControlAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopSessionRunControlAuthorityModuleV2.js',
);
const {
  createDesktopRendererDefinitionsV2,
  GenerationManagerV2,
  LoaderV2,
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
} = require('@agistack/plugin-runtime');
const {
  DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_MODULE_REF_V2,
  DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_SERVICE_V2,
  DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_VERSION_V2,
  DesktopWorkspaceContextAuthorityUnavailableErrorV2,
  desktopWorkspaceContextAuthorityDefinitionV2,
  withDesktopWorkspaceContextAuthorityOperationV2,
} = require(`${COMPILED_ROOT}/src/plugins/desktopWorkspaceContextAuthorityModuleV2.js`);
const {
  desktopPluginMarketplaceCatalogDefinitionV2,
  desktopPluginMarketplaceManagementDefinitionV2,
} = require(`${COMPILED_ROOT}/src/plugins/desktopPluginMarketplaceAuthorityModulesV2.js`);
const { desktopConversationConfigAuthorityDefinitionV2 } = require(
  `${COMPILED_ROOT}/src/plugins/desktopConversationConfigAuthorityModuleV2.js`,
);
const { desktopConversationLifecycleAuthorityDefinitionV2 } = require(
  `${COMPILED_ROOT}/src/plugins/desktopConversationLifecycleAuthorityModuleV2.js`,
);
const { desktopHitlResponseAuthorityDefinitionV2 } = require(
  `${COMPILED_ROOT}/src/plugins/desktopHitlResponseAuthorityModuleV2.js`,
);
const { desktopMyWorkAuthorityDefinitionV2 } = require(
  `${COMPILED_ROOT}/src/plugins/desktopMyWorkAuthorityModuleV2.js`,
);
const { desktopSessionTimelineAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopSessionTimelineAuthorityModuleV2.js',
);
const { desktopWorkspaceAgentBindingAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceAgentBindingAuthorityModuleV2.js',
);
const { desktopWorkspaceAutonomyAttentionAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceAutonomyAttentionAuthorityModuleV2.js',
);
const { desktopWorkspaceMemberMutationAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceMemberMutationAuthorityModuleV2.js',
);
const { desktopWorkspaceConversationCatalogAuthorityDefinitionV2 } = require(
  COMPILED_ROOT +
    '/src/plugins/desktopWorkspaceConversationCatalogAuthorityModuleV2.js',
);
const { desktopWorkspaceExecutionSnapshotAuthorityDefinitionV2 } = require(
  COMPILED_ROOT +
    '/src/plugins/desktopWorkspaceExecutionSnapshotAuthorityModuleV2.js',
);
const { desktopTerminalLifecycleAuthorityDefinitionV2 } = require(
  `${COMPILED_ROOT}/src/plugins/desktopTerminalLifecycleAuthorityModuleV2.js`,
);
const { desktopSessionProjectionAuthorityDefinitionV2 } = require(
  `${COMPILED_ROOT}/src/plugins/desktopSessionProjectionAuthorityModuleV2.js`,
);
const { desktopSessionRunChangesAuthorityDefinitionV2 } = require(
  `${COMPILED_ROOT}/src/plugins/desktopSessionRunChangesAuthorityModuleV2.js`,
);
const { desktopTenantAnalyticsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantAnalyticsAuthorityModuleV2.js',
);
const { desktopTenantCatalogAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantCatalogAuthorityModuleV2.js',
);
const { desktopTenantOverviewAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantOverviewAuthorityModuleV2.js',
);
const { desktopWorkspaceCatalogAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceCatalogAuthorityModuleV2.js',
);
const { desktopWorkspaceMessageCatalogAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceMessageCatalogAuthorityModuleV2.js',
);
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

const REPOSITORY_ROOT = new URL('../../../../', import.meta.url);
const BOOTSTRAP_PATH = new URL(
  'shared/profiles/memstack-default-bootstrap.v2.json',
  REPOSITORY_ROOT,
);
const MANIFEST_PATH = new URL(
  'config/plugin-manifests-v2/memstack-renderer-target-hosts.v2.json',
  REPOSITORY_ROOT,
);
const PROFILE_PATH = new URL(
  'config/plugin-profiles/memstack-production-target-hosts.v2.yaml',
  REPOSITORY_ROOT,
);

function loadBootstrap() {
  return JSON.parse(readFileSync(BOOTSTRAP_PATH, 'utf8'));
}

function rendererDefinitions() {
  return [
    ...createDesktopRendererDefinitionsV2(),
    require(COMPILED_ROOT + '/src/plugins/desktopProjectBlackboardAuthorityModuleV2.js')
      .desktopProjectBlackboardAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopSessionRunInputAuthorityModuleV2.js')
      .desktopSessionRunInputAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectAgentDashboardAuthorityModuleV2.js')
      .desktopProjectAgentDashboardAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectAgentLogsAuthorityModuleV2.js')
      .desktopProjectAgentLogsAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectAgentPatternsAuthorityModuleV2.js')
      .desktopProjectAgentPatternsAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectEntitiesAuthorityModuleV2.js')
      .desktopProjectEntitiesAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectCommunitiesAuthorityModuleV2.js')
      .desktopProjectCommunitiesAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectMemoriesAuthorityModuleV2.js')
      .desktopProjectMemoriesAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectTeamAuthorityModuleV2.js')
      .desktopProjectTeamAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectSchemaAuthorityModuleV2.js')
      .desktopProjectSchemaAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectMaintenanceAuthorityModuleV2.js')
      .desktopProjectMaintenanceAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectSettingsAuthorityModuleV2.js')
      .desktopProjectSettingsAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopTenantCreationAuthorityModuleV2.js')
      .desktopTenantCreationAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectSupportAuthorityModuleV2.js')
      .desktopProjectSupportAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectPlaybooksReadAuthorityModuleV2.js')
      .desktopProjectPlaybooksReadAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectGraphAuthorityModuleV2.js')
      .desktopProjectGraphAuthorityDefinitionV2,
    desktopArtifactContentAuthorityDefinitionV2,
    desktopAutomationAuthorityDefinitionV2,
    desktopNewTaskFlowAuthorityDefinitionV2,
    desktopNewThreadCreationAuthorityDefinitionV2,
    desktopProjectSearchAuthorityDefinitionV2,
    desktopRuntimePoolAuthorityDefinitionV2,
    desktopRuntimeClustersAuthorityDefinitionV2,
    desktopRuntimeInstancesAuthorityDefinitionV2,
    desktopRuntimeDeploymentsAuthorityDefinitionV2,
    desktopProjectPlaybooksEventsAuthorityDefinitionV2,
    desktopSessionArtifactActionAuthorityDefinitionV2,
    desktopSessionRunControlAuthorityDefinitionV2,
    desktopWorkspaceContextAuthorityDefinitionV2,
    desktopConversationConfigAuthorityDefinitionV2,
    desktopConversationLifecycleAuthorityDefinitionV2,
    desktopHitlResponseAuthorityDefinitionV2,
    desktopMyWorkAuthorityDefinitionV2,
    desktopSessionProjectionAuthorityDefinitionV2,
    desktopSessionRunChangesAuthorityDefinitionV2,
    desktopSessionTimelineAuthorityDefinitionV2,
    desktopWorkspaceAgentBindingAuthorityDefinitionV2,
    desktopWorkspaceAutonomyAttentionAuthorityDefinitionV2,
    desktopWorkspaceMemberMutationAuthorityDefinitionV2,
    desktopWorkspaceConversationCatalogAuthorityDefinitionV2,
    desktopWorkspaceExecutionSnapshotAuthorityDefinitionV2,
    desktopTerminalLifecycleAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopTenantAgentBindingsAuthorityModuleV2.js')
      .desktopTenantAgentBindingsAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopTenantProjectsAuthorityModuleV2.js')
      .desktopTenantProjectsAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopTenantTasksAuthorityModuleV2.js')
      .desktopTenantTasksAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectOverviewAuthorityModuleV2.js')
      .desktopProjectOverviewAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopTenantAgentDashboardAuthorityModuleV2.js')
      .desktopTenantAgentDashboardAuthorityDefinitionV2,
    desktopTenantAnalyticsAuthorityDefinitionV2,
    desktopTenantCatalogAuthorityDefinitionV2,
    desktopTenantOverviewAuthorityDefinitionV2,
    desktopWorkspaceMessageCatalogAuthorityDefinitionV2,
    desktopWorkspaceCatalogAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopWorkspaceLifecycleAuthorityModuleV2.js')
      .desktopWorkspaceLifecycleAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopWorkspaceRosterAuthorityModuleV2.js')
      .desktopWorkspaceRosterAuthorityDefinitionV2,
    desktopPluginMarketplaceCatalogDefinitionV2,
    desktopPluginMarketplaceManagementDefinitionV2,
  ];
}

function marketplaceDefinitions() {
  return [
    desktopPluginMarketplaceCatalogDefinitionV2,
    desktopPluginMarketplaceManagementDefinitionV2,
  ];
}

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46101',
    apiKey: 'workspace-context-session',
    localApiToken: 'workspace-context-launch',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    ...overrides,
  };
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

test('generated manifest, catalog, profile and runtime definition share one exact contract', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const bootstrap = loadBootstrap();
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-workspace-context-authority',
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_SERVICE_V2,
        version: DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_VERSION_V2,
      },
    ],
    requires: [],
  });
  assert.deepEqual(module.contract.events, { emits: [], handles: [] });
  assert.equal(module.contract.config_schema.additionalProperties, false);
  assert.deepEqual(module.contract.config_schema.required, ['strategy']);
  assert.equal(module.contract.config_schema.properties.strategy.const, 'desktop-api-client');
  assert.equal(module.contract_digest, catalog.contract_digest);
  assert.equal(module.contract_digest, desktopWorkspaceContextAuthorityDefinitionV2.contractDigest);
  assert.equal(catalog.entrypoint, 'applyDesktopWorkspaceContextAuthorityV2');
  assert.equal(
    catalog.artifact_source,
    'repo+typescript://agi-stack/apps/desktop/src/plugins/' +
      'desktopWorkspaceContextAuthorityModuleV2.ts',
  );
  assert.equal(entry.module_ref, DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_MODULE_REF_V2);
  assert.equal(entry.plugin_ref, 'memstack-renderer-target-hosts');
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-client' });
  assert.equal(entry.enabled, true);
  assert.match(profile, /entry_id: builtin-desktop-workspace-context-authority/u);
  assert.match(profile, /module_ref: builtin:\/\/memstack\/desktop\/workspace-context-authority/u);
  assert.doesNotMatch(JSON.stringify(module), /apiKey|localApiToken|Authorization/u);
  assert.doesNotMatch(JSON.stringify(entry), /apiKey|localApiToken|Authorization/u);
});

test('Loader activates one frozen root service and fails closed on missing or wrong definitions', async () => {
  const bootstrap = loadBootstrap();
  const loader = new LoaderV2(rendererDefinitions(), 'desktop-renderer');
  const generation = await loader.stage(bootstrap);
  const service = generation.resolve(
    DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_SERVICE_V2,
    { kind: 'root' },
    { version: DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindOperation']);
  assert.equal('publish' in service, false);
  assert.equal('resolve' in service, false);
  assert.equal('client' in service, false);

  const missingDefinitionLoader = new LoaderV2(
    [
      ...createDesktopRendererDefinitionsV2(),
      desktopTerminalLifecycleAuthorityDefinitionV2,
      desktopTenantCatalogAuthorityDefinitionV2,
      desktopWorkspaceMessageCatalogAuthorityDefinitionV2,
      desktopWorkspaceCatalogAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopWorkspaceLifecycleAuthorityModuleV2.js')
      .desktopWorkspaceLifecycleAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopWorkspaceRosterAuthorityModuleV2.js')
      .desktopWorkspaceRosterAuthorityDefinitionV2,
      desktopSessionTimelineAuthorityDefinitionV2,
      desktopWorkspaceExecutionSnapshotAuthorityDefinitionV2,
      ...marketplaceDefinitions(),
    ],
    'desktop-renderer',
  );
  await assert.rejects(
    missingDefinitionLoader.stage(bootstrap),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_module_definition',
  );

  const wrongDefinitionLoader = new LoaderV2(
    [
      ...createDesktopRendererDefinitionsV2(),
      desktopTerminalLifecycleAuthorityDefinitionV2,
      desktopTenantCatalogAuthorityDefinitionV2,
      desktopWorkspaceMessageCatalogAuthorityDefinitionV2,
      desktopWorkspaceCatalogAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopWorkspaceLifecycleAuthorityModuleV2.js')
      .desktopWorkspaceLifecycleAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopWorkspaceRosterAuthorityModuleV2.js')
      .desktopWorkspaceRosterAuthorityDefinitionV2,
      desktopSessionTimelineAuthorityDefinitionV2,
      desktopWorkspaceExecutionSnapshotAuthorityDefinitionV2,
      ...marketplaceDefinitions(),
      {
        ...desktopWorkspaceContextAuthorityDefinitionV2,
        contractDigest: `sha256:${'0'.repeat(64)}`,
      },
    ],
    'desktop-renderer',
  );
  await assert.rejects(
    wrongDefinitionLoader.stage(bootstrap),
    (error) => error instanceof RuntimeV2Error && error.code === 'contract_digest_mismatch',
  );

  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-workspace-context-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_SERVICE_V2,
        { kind: 'root' },
        { version: DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_VERSION_V2 },
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service',
  );

  const manager = new GenerationManagerV2();
  await manager.publish(generation);
  await assert.rejects(wrongDefinitionLoader.stage(bootstrap));
  assert.equal(manager.current, generation);
  assert.equal(
    manager.current.resolve(
      DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_VERSION_V2 },
    ),
    service,
  );
  await manager.close();
  assert.equal(generation.disposed, true);
});

test('bound authority freezes operation config and exposes only the three HTTP methods', async () => {
  const bootstrap = loadBootstrap();
  const generation = await new LoaderV2(rendererDefinitions(), 'desktop-renderer').stage(bootstrap);
  const service = generation.resolve(
    DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_SERVICE_V2,
    { kind: 'root' },
    { version: DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_VERSION_V2 },
  );
  const config = runtimeConfig();
  const authority = service.bindOperation(config);
  config.apiBaseUrl = 'http://127.0.0.1:46999';
  config.apiKey = 'mutated-session';
  config.localApiToken = 'mutated-launch';
  config.tenantId = 'mutated-tenant';
  const calls = [];
  const originalFetch = globalThis.fetch;
  const controller = new AbortController();
  globalThis.fetch = async (input, init) => {
    const url = new URL(String(input));
    calls.push({ url, init });
    if (url.pathname === '/api/v1/projects') {
      return json({
        projects: [{ id: 'project-2', tenant_id: 'tenant-2', name: 'Project 2' }],
        page: 1,
        page_size: 100,
        total: 1,
      });
    }
    if (url.pathname === '/api/v1/workspace-context') {
      return json({
        context: {
          tenant_id: 'tenant-2',
          project_id: 'project-1',
          revision: 7,
          updated_at: '2026-09-01T00:00:00Z',
        },
        membership_role: 'owner',
      });
    }
    return json({
      context: {
        tenant_id: 'tenant-2',
        project_id: 'project-2',
        revision: 8,
        updated_at: '2026-09-01T00:00:01Z',
      },
      changed: true,
    });
  };

  try {
    const projects = await authority.listProjects('tenant-2', controller.signal);
    const context = await authority.getWorkspaceContext(controller.signal);
    const switched = await authority.switchWorkspaceContext(
      'tenant-2',
      'project-2',
      7,
      'workspace-context-idempotency',
      controller.signal,
    );

    assert.equal(Object.isFrozen(authority), true);
    assert.deepEqual(Object.keys(authority), [
      'listProjects',
      'getWorkspaceContext',
      'switchWorkspaceContext',
    ]);
    assert.equal('client' in authority, false);
    assert.equal('request' in authority, false);
    assert.equal('listTenants' in authority, false);
    assert.equal(projects[0].id, 'project-2');
    assert.equal(context.context.revision, 7);
    assert.equal(switched.context.revision, 8);
    assert.equal(calls.length, 3);
    for (const call of calls) {
      assert.equal(call.url.origin, 'http://127.0.0.1:46101');
      assert.equal(call.init.signal, controller.signal);
      const headers = new Headers(call.init.headers);
      assert.equal(headers.get('Authorization'), 'Bearer workspace-context-session');
      assert.equal(headers.get('X-Agistack-Launch'), 'workspace-context-launch');
    }
    assert.equal(calls[0].url.pathname, '/api/v1/projects');
    assert.equal(calls[0].url.searchParams.get('tenant_id'), 'tenant-2');
    assert.equal(calls[1].url.pathname, '/api/v1/workspace-context');
    assert.equal(calls[2].url.pathname, '/api/v1/workspace-context/switch');
    assert.deepEqual(JSON.parse(calls[2].init.body), {
      tenant_id: 'tenant-2',
      project_id: 'project-2',
      expected_revision: 7,
      idempotency_key: 'workspace-context-idempotency',
    });
    assert.doesNotMatch(
      JSON.stringify(service),
      /workspace-context-session|workspace-context-launch/u,
    );
    assert.doesNotMatch(
      JSON.stringify(authority),
      /workspace-context-session|workspace-context-launch/u,
    );
  } finally {
    globalThis.fetch = originalFetch;
    await generation.dispose();
  }
});

test('operation helper acquires one exact service lease and preserves the primary failure', async () => {
  const requestConfig = runtimeConfig();
  let admit;
  const admissionPending = new Promise((resolve) => {
    admit = resolve;
  });
  const requests = [];
  let releaseCount = 0;
  let boundConfig = null;
  const primary = new Error('workspace_context_primary_failure');
  const actions = {
    acquireServiceOperationLease: async (request) => {
      requests.push(request);
      return admissionPending;
    },
  };
  const pending = withDesktopWorkspaceContextAuthorityOperationV2(
    actions,
    requestConfig,
    async () => {
      throw primary;
    },
  );
  requestConfig.apiBaseUrl = 'http://127.0.0.1:46999';
  requestConfig.apiKey = 'mutated-session';
  admit({
    status: 'accepted',
    digest: 'sha256:accepted',
    useService(operation) {
      return operation({
        bindOperation(config) {
          boundConfig = config;
          return Object.freeze({});
        },
      });
    },
    async release() {
      releaseCount += 1;
      throw new Error('workspace_context_release_failure');
    },
  });

  await assert.rejects(pending, (error) => error === primary);
  assert.deepEqual(requests, [
    {
      service: DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_SERVICE_V2,
      version: DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_VERSION_V2,
      scope: { kind: 'root' },
    },
  ]);
  assert.equal(boundConfig.apiBaseUrl, 'http://127.0.0.1:46101');
  assert.equal(boundConfig.apiKey, 'workspace-context-session');
  assert.equal(Object.isFrozen(boundConfig), true);
  assert.equal(releaseCount, 1);
});

test('operation helper revokes an escaped authority before release begins', async () => {
  let escapedAuthority = null;
  let releaseStarted;
  let finishRelease;
  let transportCalls = 0;
  const releaseStartedPending = new Promise((resolve) => {
    releaseStarted = resolve;
  });
  const releasePending = new Promise((resolve) => {
    finishRelease = resolve;
  });
  const actions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:accepted',
      useService(operation) {
        return operation({
          bindOperation() {
            return Object.freeze({
              async listProjects() {
                transportCalls += 1;
                return [];
              },
              async getWorkspaceContext() {
                transportCalls += 1;
                return {};
              },
              async switchWorkspaceContext() {
                transportCalls += 1;
                return {};
              },
            });
          },
        });
      },
      async release() {
        releaseStarted();
        await releasePending;
      },
    }),
  };

  const operationPending = withDesktopWorkspaceContextAuthorityOperationV2(
    actions,
    runtimeConfig(),
    (authority) => {
      escapedAuthority = authority;
      return 'workspace-context-complete';
    },
  );
  await releaseStartedPending;

  assert.equal(Object.isFrozen(escapedAuthority), true);
  await assert.rejects(
    async () => escapedAuthority.listProjects('tenant-1', new AbortController().signal),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_context_authority_operation_released',
  );
  assert.equal(transportCalls, 0);

  finishRelease();
  assert.equal(await operationPending, 'workspace-context-complete');
});

test('operation helper rejects unavailable services without invoking a transport fallback', async () => {
  let operationCalls = 0;
  const actions = {
    acquireServiceOperationLease: async () => ({
      status: 'rejected',
      reasonCode: 'desktop_renderer_service_resolve_failed',
      runtimeCode: 'service_not_found',
    }),
  };

  await assert.rejects(
    withDesktopWorkspaceContextAuthorityOperationV2(actions, runtimeConfig(), async () => {
      operationCalls += 1;
    }),
    (error) => {
      assert.equal(error instanceof DesktopWorkspaceContextAuthorityUnavailableErrorV2, true);
      assert.equal(error.reasonCode, 'desktop_renderer_service_resolve_failed');
      assert.equal(error.runtimeCode, 'service_not_found');
      assert.doesNotMatch(error.message, /workspace-context-session|workspace-context-launch/u);
      return true;
    },
  );
  assert.equal(operationCalls, 0);
});

test('production wiring registers the Definition and removes direct workspace context clients', () => {
  const hook = readFileSync(
    new URL('agi-stack/apps/desktop/src/plugins/useDesktopPluginGenerationV2.ts', REPOSITORY_ROOT),
    'utf8',
  );
  const app = readFileSync(new URL('agi-stack/apps/desktop/src/App.tsx', REPOSITORY_ROOT), 'utf8');
  const settings = readFileSync(
    new URL('agi-stack/apps/desktop/src/features/settings/SettingsCorePages.tsx', REPOSITORY_ROOT),
    'utf8',
  );
  const module = readFileSync(
    new URL(
      'agi-stack/apps/desktop/src/plugins/desktopWorkspaceContextAuthorityModuleV2.ts',
      REPOSITORY_ROOT,
    ),
    'utf8',
  );
  const routeScopeBlock = app.match(
    /const productionRouteScopeTransaction[\s\S]+?const switchProductionRouteScope/u,
  )?.[0];
  const settingsContextBlock = app.match(
    /const applySettingsContext[\s\S]+?\n  const goBackSection/u,
  )?.[0];

  assert.ok(routeScopeBlock);
  assert.ok(settingsContextBlock);
  assert.match(hook, /desktopWorkspaceContextAuthorityDefinitionV2/u);
  assert.match(routeScopeBlock, /withDesktopWorkspaceContextAuthorityOperationV2/u);
  assert.doesNotMatch(routeScopeBlock, /new DesktopApiClient/u);
  assert.match(settingsContextBlock, /withDesktopWorkspaceContextAuthorityOperationV2/u);
  assert.doesNotMatch(settingsContextBlock, /new DesktopApiClient/u);
  assert.doesNotMatch(settings, /import \{ DesktopApiClient \}/u);
  assert.doesNotMatch(settings, /new DesktopApiClient/u);
  assert.match(settings, /withDesktopWorkspaceContextAuthorityOperationV2/u);
  assert.match(module, /context\.provide\(DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_SERVICE_V2/u);
  assert.doesNotMatch(module, /\bpublish\b|\bresolve\b|authentication-kernel/u);
});
