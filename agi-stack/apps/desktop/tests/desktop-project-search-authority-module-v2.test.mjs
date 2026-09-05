import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const {
  createDesktopRendererDefinitionsV2,
  LoaderV2,
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
} = require('@agistack/plugin-runtime');
const {
  DESKTOP_PROJECT_SEARCH_AUTHORITY_MODULE_REF_V2,
  DESKTOP_PROJECT_SEARCH_AUTHORITY_SERVICE_V2,
  DESKTOP_PROJECT_SEARCH_AUTHORITY_VERSION_V2,
  applyDesktopProjectSearchAuthorityV2,
  desktopProjectSearchAuthorityDefinitionV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopProjectSearchAuthorityModuleV2.js');
const authorityModules = [
  'desktopArtifactContentAuthorityModuleV2',
  'desktopProjectSchemaAuthorityModuleV2',
  'desktopProjectMaintenanceAuthorityModuleV2',
  'desktopProjectSettingsAuthorityModuleV2',
  'desktopTenantCreationAuthorityModuleV2',
  'desktopProjectSupportAuthorityModuleV2',
  'desktopProjectPlaybooksReadAuthorityModuleV2',
  'desktopAutomationAuthorityModuleV2',
  'desktopConversationConfigAuthorityModuleV2',
  'desktopConversationLifecycleAuthorityModuleV2',
  'desktopHitlResponseAuthorityModuleV2',
  'desktopMyWorkAuthorityModuleV2',
  'desktopNewTaskFlowAuthorityModuleV2',
  'desktopNewThreadCreationAuthorityModuleV2',
  'desktopProjectOverviewAuthorityModuleV2',
  'desktopProjectAgentDashboardAuthorityModuleV2',
  'desktopProjectAgentLogsAuthorityModuleV2',
  'desktopProjectAgentPatternsAuthorityModuleV2',
  'desktopProjectEntitiesAuthorityModuleV2',
  'desktopProjectCommunitiesAuthorityModuleV2',
  'desktopProjectMemoriesAuthorityModuleV2',
  'desktopProjectTeamAuthorityModuleV2',
  'desktopProjectGraphAuthorityModuleV2',
  'desktopRuntimePoolAuthorityModuleV2',
  'desktopRuntimeInstancesAuthorityModuleV2',
  'desktopRuntimeDeploymentsAuthorityModuleV2',
  'desktopProjectPlaybooksEventsAuthorityModuleV2',
  'desktopBackendStoresAuthorityModuleV2',
  'desktopDeadLetterQueueAuthorityModuleV2',
 'desktopInstanceTemplatesAuthorityModuleV2',
  'desktopUnifiedRuntimesAuthorityModuleV2',
  'desktopTenantEventsAuthorityModuleV2',
  'desktopTenantPatternsAuthorityModuleV2',
  'desktopTenantDecisionRecordsAuthorityModuleV2',
  'desktopTenantSettingsAuthorityModuleV2',
  'desktopTenantWebhooksAuthorityModuleV2',
  'desktopTenantBillingAuthorityModuleV2',
  'desktopTenantAuditAuthorityModuleV2',
      'desktopTenantGovernanceAuthorityModuleV2',
      'desktopTenantAcpAuthorityModuleV2',
  'desktopTenantEvolutionAuthorityModuleV2',
  'desktopTenantGenesAuthorityModuleV2',
  'desktopTenantTemplatesAuthorityModuleV2',
  'desktopProjectChannelsAuthorityModuleV2',
  'desktopUserProfileAuthorityModuleV2',
  'desktopTenantAgentDefinitionsAuthorityModuleV2',
  'desktopTenantOrganizationSettingsAuthorityModuleV2',
  'desktopTenantTrustAuthorityModuleV2',
  'desktopRuntimeClustersAuthorityModuleV2',
  'desktopSessionArtifactActionAuthorityModuleV2',
  'desktopSessionProjectionAuthorityModuleV2',
  'desktopSessionRunControlAuthorityModuleV2',
  'desktopSessionRunChangesAuthorityModuleV2',
  'desktopSessionTimelineAuthorityModuleV2',
  'desktopTenantAgentBindingsAuthorityModuleV2',
  'desktopTenantProjectsAuthorityModuleV2',
  'desktopTenantTasksAuthorityModuleV2',
  'desktopTenantAgentDashboardAuthorityModuleV2',
  'desktopTenantAnalyticsAuthorityModuleV2',
  'desktopTenantCatalogAuthorityModuleV2',
  'desktopTenantOverviewAuthorityModuleV2',
  'desktopTerminalLifecycleAuthorityModuleV2',
  'desktopWorkspaceAgentBindingAuthorityModuleV2',
  'desktopWorkspaceAutonomyAttentionAuthorityModuleV2',
  'desktopWorkspaceMemberMutationAuthorityModuleV2',
  'desktopWorkspaceCatalogAuthorityModuleV2',
  'desktopWorkspaceLifecycleAuthorityModuleV2',
  'desktopWorkspaceRosterAuthorityModuleV2',
  'desktopWorkspaceContextAuthorityModuleV2',
  'desktopWorkspaceConversationCatalogAuthorityModuleV2',
  'desktopWorkspaceExecutionSnapshotAuthorityModuleV2',
  'desktopWorkspaceMessageCatalogAuthorityModuleV2',
].flatMap((moduleName) =>
  Object.values(require(`${COMPILED_ROOT}/src/plugins/${moduleName}.js`)).filter(
    (value) => value?.moduleRef && typeof value?.apply === 'function',
  ),
);
const marketplace = require(
  COMPILED_ROOT + '/src/plugins/desktopPluginMarketplaceAuthorityModulesV2.js',
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
    ...authorityModules,
    marketplace.desktopPluginMarketplaceCatalogDefinitionV2,
    marketplace.desktopPluginMarketplaceManagementDefinitionV2,
    desktopProjectSearchAuthorityDefinitionV2,
  ];
}

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46851',
    apiKey: 'project-search-session',
    localApiToken: 'project-search-launch',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: '',
    workspaceRoot: '',
    ...overrides,
  };
}

function semanticRequest() {
  return {
    mode: 'semantic',
    query: 'architecture',
    strategy: 'hybrid',
    focalNodeUuid: null,
    reranker: null,
    limit: 20,
  };
}

function response(overrides = {}) {
  return {
    results: [
      {
        id: 'memory-1',
        title: 'Architecture',
        content: 'Generation-bound search',
        score: 0.9,
        source: 'memory',
        type: 'Memory',
        createdAt: '2026-09-02T00:00:00Z',
        tags: ['v2'],
      },
    ],
    total: 1,
    searchType: 'advanced',
    limit: 20,
    offset: null,
    facets: null,
    ...overrides,
  };
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function wireResponse() {
  return {
    results: [
      {
        uuid: 'memory-1',
        title: 'Architecture',
        content: 'Generation-bound search',
        score: 0.9,
        source: 'memory',
        type: 'Memory',
        created_at: '2026-09-02T00:00:00Z',
        tags: ['v2'],
      },
    ],
    total: 1,
    search_type: 'advanced',
    limit: 20,
    offset: null,
    facets: null,
  };
}

test('generated contract declares one credential-free root Project Search Provider', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const bootstrap = loadBootstrap();
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_PROJECT_SEARCH_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_PROJECT_SEARCH_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-project-search-authority',
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_PROJECT_SEARCH_AUTHORITY_SERVICE_V2,
        version: DESKTOP_PROJECT_SEARCH_AUTHORITY_VERSION_V2,
      },
    ],
    requires: [],
  });
  assert.deepEqual(module.contract.events, { emits: [], handles: [] });
  assert.equal(module.contract.config_schema.additionalProperties, false);
  assert.deepEqual(module.contract.config_schema.required, ['strategy']);
  assert.equal(module.contract.config_schema.properties.strategy.const, 'desktop-api-client');
  assert.equal(module.contract_digest, catalog.contract_digest);
  assert.equal(module.contract_digest, desktopProjectSearchAuthorityDefinitionV2.contractDigest);
  assert.equal(catalog.entrypoint, 'applyDesktopProjectSearchAuthorityV2');
  assert.equal(
    catalog.artifact_source,
    'repo+typescript://agi-stack/apps/desktop/src/plugins/' +
      'desktopProjectSearchAuthorityModuleV2.ts',
  );
  assert.equal(entry.module_ref, DESKTOP_PROJECT_SEARCH_AUTHORITY_MODULE_REF_V2);
  assert.equal(entry.parent_entry_id, 'builtin-desktop-renderer-host');
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-client' });
  assert.deepEqual(entry.inject, {});
  assert.equal(entry.enabled, true);
  assert.match(profile, /entry_id: builtin-desktop-project-search-authority/u);
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(JSON.stringify(value), /apiKey|localApiToken|Authorization/iu);
  }
});

test('Loader activation and Profile disable remove search without fallback', async () => {
  const bootstrap = loadBootstrap();
  const loader = new LoaderV2(rendererDefinitions(), 'desktop-renderer');
  const generation = await loader.stage(bootstrap);
  const service = generation.resolve(
    DESKTOP_PROJECT_SEARCH_AUTHORITY_SERVICE_V2,
    { kind: 'root' },
    { version: DESKTOP_PROJECT_SEARCH_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindOperation']);
  assert.throws(
    () =>
      applyDesktopProjectSearchAuthorityV2(
        { provide: () => assert.fail('invalid config must not provide') },
        { strategy: 'legacy-client' },
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_project_search_authority_config_invalid',
  );

  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-project-search-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_PROJECT_SEARCH_AUTHORITY_SERVICE_V2,
        {
          kind: 'project',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
        },
        { version: DESKTOP_PROJECT_SEARCH_AUTHORITY_VERSION_V2 },
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service',
  );
  await disabledGeneration.dispose();
  await generation.dispose();
});

test('Local and Cloud service transports preserve search contract and vault secrecy', async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const localCalls = [];
  globalThis.fetch = async (input, init) => {
    localCalls.push({ input, init });
    return json(wireResponse());
  };

  try {
    const generation = await new LoaderV2(rendererDefinitions(), 'desktop-renderer').stage(
      loadBootstrap(),
    );
    const service = generation.resolve(
      DESKTOP_PROJECT_SEARCH_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: DESKTOP_PROJECT_SEARCH_AUTHORITY_VERSION_V2 },
    );
    const localResult = await service
      .bindOperation(runtimeConfig())
      .searchProject(semanticRequest(), {
        tenantId: 'tenant-1',
        projectId: 'project-1',
      });
    assert.deepEqual(localResult, response());
    assert.equal(new URL(String(localCalls[0].input)).pathname, '/api/v1/search-enhanced/advanced');
    assert.equal(
      new Headers(localCalls[0].init.headers).get('Authorization'),
      'Bearer project-search-session',
    );

    const cloudCalls = [];
    globalThis.window = {
      __MEMSTACK_DESKTOP__: {
        core: {
          async invoke(command, args) {
            cloudCalls.push({ command, args });
            return { status: 200, body: wireResponse() };
          },
        },
      },
    };
    await service
      .bindOperation(runtimeConfig({ mode: 'cloud', apiKey: '', localApiToken: '' }))
      .searchProject(semanticRequest(), {
        tenantId: 'tenant-1',
        projectId: 'project-1',
      });
    assert.equal(cloudCalls[0].command, 'cloud_request');
    assert.equal(cloudCalls[0].args.request.path, '/api/v1/search-enhanced/advanced');
    assert.equal(JSON.stringify(cloudCalls).includes('project-search-session'), false);
    assert.equal(JSON.stringify(cloudCalls).includes('project-search-launch'), false);
    await generation.dispose();
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});
