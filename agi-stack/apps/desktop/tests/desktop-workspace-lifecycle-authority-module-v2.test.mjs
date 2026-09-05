import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const {
  createDesktopRendererDefinitionsV2,
  GenerationManagerV2,
  LoaderV2,
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
} = require('@agistack/plugin-runtime');
const {
  DESKTOP_WORKSPACE_LIFECYCLE_AUTHORITY_MODULE_REF_V2,
  DESKTOP_WORKSPACE_LIFECYCLE_AUTHORITY_SERVICE_V2,
  DESKTOP_WORKSPACE_LIFECYCLE_AUTHORITY_VERSION_V2,
  applyDesktopWorkspaceLifecycleAuthorityV2,
  desktopWorkspaceLifecycleAuthorityDefinitionV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopWorkspaceLifecycleAuthorityModuleV2.js');
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
  'desktopTenantPromptTemplatesAuthorityModuleV2',
  'desktopTenantSubAgentDefinitionsAuthorityModuleV2',
  'desktopTenantSkillDefinitionsAuthorityModuleV2',
  'desktopTenantProvidersAuthorityModuleV2',
  'desktopProjectMcpServersAuthorityModuleV2',
  'desktopProjectMcpAppsAuthorityModuleV2',
  'desktopBrowserIntegrationAuthorityModuleV2',
  'desktopProjectSandboxUploadAuthorityModuleV2',
  'desktopProjectSandboxSurfaceAuthorityModuleV2',
  'desktopWorkspaceAgentPolicyAuthorityModuleV2',
  'desktopTenantSkillPackagesAuthorityModuleV2',
  'desktopTenantSkillEvolutionAuthorityModuleV2',
  'desktopProjectChannelsAuthorityModuleV2',
  'desktopUserProfileAuthorityModuleV2',
  'desktopTenantAgentDefinitionsAuthorityModuleV2',
  'desktopTenantOrganizationSettingsAuthorityModuleV2',
  'desktopTenantTrustAuthorityModuleV2',
  'desktopRuntimeClustersAuthorityModuleV2',
  'desktopProjectSearchAuthorityModuleV2',
  'desktopSessionArtifactActionAuthorityModuleV2',
  'desktopSessionProjectionAuthorityModuleV2',
  'desktopSessionRunChangesAuthorityModuleV2',
  'desktopSessionRunControlAuthorityModuleV2',
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
  'desktopWorkspaceCatalogAuthorityModuleV2',
  'desktopWorkspaceContextAuthorityModuleV2',
  'desktopWorkspaceConversationCatalogAuthorityModuleV2',
  'desktopWorkspaceExecutionSnapshotAuthorityModuleV2',
  'desktopWorkspaceMemberMutationAuthorityModuleV2',
  'desktopWorkspaceMessageCatalogAuthorityModuleV2',
  'desktopWorkspaceRosterAuthorityModuleV2',
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
    desktopWorkspaceLifecycleAuthorityDefinitionV2,
  ];
}

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46971',
    apiKey: 'workspace-lifecycle-session',
    localApiToken: 'workspace-lifecycle-launch',
    mode: 'local',
    tenantId: 'tenant / one',
    projectId: 'project / one',
    workspaceId: '',
    workspaceRoot: '/workspace/project-one',
    ...overrides,
  };
}

function createInput() {
  return {
    name: 'Created workspace',
    description: 'Created through V2',
    useCase: 'conversation',
    collaborationMode: 'multi_agent_shared',
    metadata: { source: 'desktop' },
  };
}

function updateInput() {
  return {
    name: 'Updated workspace',
    description: 'Updated through V2',
    isArchived: true,
    metadata: { source: 'desktop-v2' },
  };
}

function workspace(overrides = {}) {
  return {
    id: 'workspace / one',
    tenant_id: 'tenant / one',
    project_id: 'project / one',
    name: 'Updated workspace',
    created_by: 'user-1',
    description: 'Updated through V2',
    status: 'active',
    is_archived: true,
    office_status: 'idle',
    hex_layout_config: {},
    created_at: '2026-09-02T00:00:00Z',
    updated_at: null,
    metadata: {},
    ...overrides,
  };
}

test('generated contract declares one credential-free root workspace lifecycle Provider', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const bootstrap = loadBootstrap();
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_WORKSPACE_LIFECYCLE_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_WORKSPACE_LIFECYCLE_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-workspace-lifecycle-authority',
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_WORKSPACE_LIFECYCLE_AUTHORITY_SERVICE_V2,
        version: DESKTOP_WORKSPACE_LIFECYCLE_AUTHORITY_VERSION_V2,
      },
    ],
    requires: [],
  });
  assert.deepEqual(module.contract.events, { emits: [], handles: [] });
  assert.equal(module.contract.config_schema.additionalProperties, false);
  assert.deepEqual(module.contract.config_schema.required, ['strategy']);
  assert.equal(module.contract.config_schema.properties.strategy.const, 'desktop-api-client');
  assert.equal(module.contract_digest, catalog.contract_digest);
  assert.equal(
    module.contract_digest,
    desktopWorkspaceLifecycleAuthorityDefinitionV2.contractDigest,
  );
  assert.equal(catalog.entrypoint, 'applyDesktopWorkspaceLifecycleAuthorityV2');
  assert.equal(
    catalog.artifact_source,
    'repo+typescript://agi-stack/apps/desktop/src/plugins/' +
      'desktopWorkspaceLifecycleAuthorityModuleV2.ts',
  );
  assert.equal(entry.module_ref, DESKTOP_WORKSPACE_LIFECYCLE_AUTHORITY_MODULE_REF_V2);
  assert.equal(entry.parent_entry_id, 'builtin-desktop-renderer-host');
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-client' });
  assert.deepEqual(entry.inject, {});
  assert.equal(entry.enabled, true);
  assert.match(profile, /entry_id: builtin-desktop-workspace-lifecycle-authority/u);
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(
      JSON.stringify(value),
      /apiKey|localApiToken|Authorization|workspace-lifecycle-session/iu,
    );
  }
});

test('Loader activation and Profile disable remove workspace lifecycle without fallback', async () => {
  const bootstrap = loadBootstrap();
  const loader = new LoaderV2(rendererDefinitions(), 'desktop-renderer');
  const generation = await loader.stage(bootstrap);
  const service = generation.resolve(
    DESKTOP_WORKSPACE_LIFECYCLE_AUTHORITY_SERVICE_V2,
    { kind: 'project', tenant_id: 'tenant / one', project_id: 'project / one' },
    { version: DESKTOP_WORKSPACE_LIFECYCLE_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindOperation']);
  assert.equal('config' in service, false);
  assert.equal('client' in service, false);
  assert.throws(
    () =>
      applyDesktopWorkspaceLifecycleAuthorityV2(
        { provide: () => assert.fail('invalid config must not provide') },
        { strategy: 'legacy-client' },
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_lifecycle_authority_config_invalid',
  );

  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-workspace-lifecycle-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_WORKSPACE_LIFECYCLE_AUTHORITY_SERVICE_V2,
        { kind: 'project', tenant_id: 'tenant / one', project_id: 'project / one' },
        { version: DESKTOP_WORKSPACE_LIFECYCLE_AUTHORITY_VERSION_V2 },
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service',
  );

  const manager = new GenerationManagerV2();
  await manager.publish(generation);
  const wrongDefinitionLoader = new LoaderV2(
    rendererDefinitions().map((candidate) =>
      candidate.moduleRef === DESKTOP_WORKSPACE_LIFECYCLE_AUTHORITY_MODULE_REF_V2
        ? { ...candidate, contractDigest: `sha256:${'0'.repeat(64)}` }
        : candidate,
    ),
    'desktop-renderer',
  );
  await assert.rejects(
    wrongDefinitionLoader.stage(bootstrap),
    (error) => error instanceof RuntimeV2Error && error.code === 'contract_digest_mismatch',
  );
  assert.equal(manager.current, generation);
  await disabledGeneration.dispose();
  await manager.close();
});

test('Local and vault-bound Cloud transports preserve exact scope, signals and bodies', async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const fetchCalls = [];
  const cloudCommands = [];
  const controller = new AbortController();
  globalThis.fetch = async (input, init) => {
    fetchCalls.push({ input: String(input), init });
    return new Response(
      JSON.stringify(workspace({ id: 'workspace-created', name: 'Created workspace' })),
      { status: 201, headers: { 'content-type': 'application/json' } },
    );
  };
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          cloudCommands.push({ command, args });
          return { status: 200, body: workspace() };
        },
      },
    },
  };

  try {
    let service;
    applyDesktopWorkspaceLifecycleAuthorityV2(
      { provide: (_key, provided) => (service = provided) },
      { strategy: 'desktop-api-client' },
    );
    const localConfig = runtimeConfig();
    const local = service.bindOperation(localConfig);
    localConfig.apiBaseUrl = 'http://127.0.0.1:49999';
    const created = await local.createWorkspace(createInput(), controller.signal);
    const cloud = service.bindOperation(
      runtimeConfig({
        apiBaseUrl: 'https://cloud.example.test',
        apiKey: '',
        localApiToken: '',
        mode: 'cloud',
        workspaceId: 'workspace / one',
      }),
    );
    const updated = await cloud.updateWorkspace(
      'workspace / one',
      updateInput(),
      controller.signal,
    );

    assert.equal(created.id, 'workspace-created');
    assert.equal(updated.id, 'workspace / one');
    assert.equal(Object.isFrozen(created), true);
    assert.equal(Object.isFrozen(updated), true);
    assert.equal(fetchCalls.length, 1);
    assert.equal(
      fetchCalls[0].input,
      'http://127.0.0.1:46971/api/v1/tenants/tenant%20%2F%20one/' +
        'projects/project%20%2F%20one/workspaces',
    );
    assert.equal(fetchCalls[0].init.method, 'POST');
    assert.equal(fetchCalls[0].init.signal, controller.signal);
    assert.deepEqual(JSON.parse(String(fetchCalls[0].init.body)), {
      name: 'Created workspace',
      description: 'Created through V2',
      metadata: { source: 'desktop' },
      use_case: 'conversation',
      collaboration_mode: 'multi_agent_shared',
    });
    assert.equal(cloudCommands.length, 1);
    assert.equal(cloudCommands[0].command, 'cloud_request');
    assert.equal(typeof cloudCommands[0].args.requestId, 'string');
    assert.deepEqual(cloudCommands[0].args.request, {
      path:
        '/api/v1/tenants/tenant%20%2F%20one/projects/project%20%2F%20one/' +
        'workspaces/workspace%20%2F%20one',
      method: 'PATCH',
      body: {
        name: 'Updated workspace',
        description: 'Updated through V2',
        is_archived: true,
        metadata: { source: 'desktop-v2' },
      },
    });
    assert.doesNotMatch(
      JSON.stringify(cloudCommands),
      /Authorization|workspace-lifecycle-session|workspace-lifecycle-launch/u,
    );
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});
