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
  DESKTOP_WORKSPACE_CONVERSATION_CATALOG_AUTHORITY_MODULE_REF_V2,
  DESKTOP_WORKSPACE_CONVERSATION_CATALOG_AUTHORITY_SERVICE_V2,
  DESKTOP_WORKSPACE_CONVERSATION_CATALOG_AUTHORITY_VERSION_V2,
  applyDesktopWorkspaceConversationCatalogAuthorityV2,
  desktopWorkspaceConversationCatalogAuthorityDefinitionV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopWorkspaceConversationCatalogAuthorityModuleV2.js');
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
  'desktopProjectActivityReadStateAuthorityModuleV2',
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
  'desktopWorkspaceMemberMutationAuthorityModuleV2',
  'desktopWorkspaceCatalogAuthorityModuleV2',
  'desktopWorkspaceLifecycleAuthorityModuleV2',
  'desktopWorkspaceRosterAuthorityModuleV2',
  'desktopWorkspaceContextAuthorityModuleV2',
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
  const profile = JSON.parse(readFileSync(BOOTSTRAP_PATH, 'utf8'));
  // This focused Loader fixture does not exercise the coordinating snapshot module.
  profile.entries = profile.entries.filter(
    (entry) => entry.module_ref !== 'builtin://memstack/desktop/workbench-snapshot-authority' &&
      entry.module_ref !== 'builtin://memstack/desktop/conversation-messaging-authority',
  );
  return profile;
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
    desktopWorkspaceConversationCatalogAuthorityDefinitionV2,
  ];
}

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46931',
    apiKey: 'workspace-conversation-session',
    localApiToken: 'workspace-conversation-launch',
    mode: 'local',
    tenantId: 'tenant / one',
    projectId: 'project / one',
    workspaceId: 'workspace / one',
    workspaceRoot: '/workspace/project-one',
    ...overrides,
  };
}

function conversation(id, workspaceId) {
  return {
    id,
    tenant_id: 'tenant / one',
    project_id: 'project / one',
    user_id: 'user-1',
    title: `Conversation ${id}`,
    status: 'active',
    message_count: 2,
    created_at: '2026-09-02T00:00:00Z',
    workspace_id: workspaceId,
  };
}

function page(item) {
  return {
    items: [item],
    total: 1,
    has_more: false,
    offset: 0,
    limit: 500,
    next_offset: null,
  };
}

function json(payload) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

test('generated contract declares one credential-free root conversation catalog Provider', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const bootstrap = loadBootstrap();
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_WORKSPACE_CONVERSATION_CATALOG_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_WORKSPACE_CONVERSATION_CATALOG_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap.entries.find(
    ({ entry_id: entryId }) =>
      entryId === 'builtin-desktop-workspace-conversation-catalog-authority',
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_WORKSPACE_CONVERSATION_CATALOG_AUTHORITY_SERVICE_V2,
        version: DESKTOP_WORKSPACE_CONVERSATION_CATALOG_AUTHORITY_VERSION_V2,
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
    desktopWorkspaceConversationCatalogAuthorityDefinitionV2.contractDigest,
  );
  assert.equal(catalog.entrypoint, 'applyDesktopWorkspaceConversationCatalogAuthorityV2');
  assert.equal(
    catalog.artifact_source,
    'repo+typescript://agi-stack/apps/desktop/src/plugins/' +
      'desktopWorkspaceConversationCatalogAuthorityModuleV2.ts',
  );
  assert.equal(entry.module_ref, DESKTOP_WORKSPACE_CONVERSATION_CATALOG_AUTHORITY_MODULE_REF_V2);
  assert.equal(entry.parent_entry_id, 'builtin-desktop-renderer-host');
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-client' });
  assert.deepEqual(entry.inject, {});
  assert.equal(entry.enabled, true);
  assert.match(profile, /entry_id: builtin-desktop-workspace-conversation-catalog-authority/u);
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(
      JSON.stringify(value),
      /apiKey|localApiToken|Authorization|workspace-conversation-session/iu,
    );
  }
});

test('Loader activation and Profile disable remove conversation catalog without fallback', async () => {
  const bootstrap = loadBootstrap();
  const loader = new LoaderV2(rendererDefinitions(), 'desktop-renderer');
  const generation = await loader.stage(bootstrap);
  const service = generation.resolve(
    DESKTOP_WORKSPACE_CONVERSATION_CATALOG_AUTHORITY_SERVICE_V2,
    {
      kind: 'project',
      tenant_id: 'tenant / one',
      project_id: 'project / one',
    },
    { version: DESKTOP_WORKSPACE_CONVERSATION_CATALOG_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindOperation']);
  assert.equal('config' in service, false);
  assert.equal('client' in service, false);
  assert.throws(
    () =>
      applyDesktopWorkspaceConversationCatalogAuthorityV2(
        { provide: () => assert.fail('invalid config must not provide') },
        { strategy: 'legacy-client' },
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_conversation_catalog_authority_config_invalid',
  );

  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    ({ entry_id: entryId }) =>
      entryId === 'builtin-desktop-workspace-conversation-catalog-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_WORKSPACE_CONVERSATION_CATALOG_AUTHORITY_SERVICE_V2,
        {
          kind: 'project',
          tenant_id: 'tenant / one',
          project_id: 'project / one',
        },
        { version: DESKTOP_WORKSPACE_CONVERSATION_CATALOG_AUTHORITY_VERSION_V2 },
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service',
  );

  const manager = new GenerationManagerV2();
  await manager.publish(generation);
  const wrongDefinitionLoader = new LoaderV2(
    rendererDefinitions().map((definition) =>
      definition.moduleRef === DESKTOP_WORKSPACE_CONVERSATION_CATALOG_AUTHORITY_MODULE_REF_V2
        ? { ...definition, contractDigest: `sha256:${'0'.repeat(64)}` }
        : definition,
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

test('Local and Cloud transports keep scope filters exact without exposing credentials', async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const fetchCalls = [];
  const cloudCommands = [];
  globalThis.fetch = async (input, init) => {
    fetchCalls.push({ input: String(input), init });
    return json(page(conversation('local-conversation', 'workspace / one')));
  };
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          cloudCommands.push({ command, args });
          return {
            status: 200,
            body: page(conversation('cloud-conversation', null)),
          };
        },
      },
    },
  };

  try {
    const generation = await new LoaderV2(rendererDefinitions(), 'desktop-renderer').stage(
      loadBootstrap(),
    );
    const service = generation.resolve(
      DESKTOP_WORKSPACE_CONVERSATION_CATALOG_AUTHORITY_SERVICE_V2,
      {
        kind: 'project',
        tenant_id: 'tenant / one',
        project_id: 'project / one',
      },
      { version: DESKTOP_WORKSPACE_CONVERSATION_CATALOG_AUTHORITY_VERSION_V2 },
    );
    const controller = new AbortController();
    const localConfig = runtimeConfig();
    const local = service.bindOperation(localConfig);
    localConfig.apiBaseUrl = 'http://127.0.0.1:46999';
    localConfig.apiKey = 'mutated-session';
    const cloud = service.bindOperation(
      runtimeConfig({
        apiBaseUrl: 'https://cloud.example.test',
        apiKey: '',
        localApiToken: '',
        mode: 'cloud',
      }),
    );

    const localResult = await local.listConversations({
      workspaceId: 'workspace / one',
      unboundOnly: false,
      signal: controller.signal,
    });
    const cloudResult = await cloud.listConversations({
      workspaceId: null,
      unboundOnly: true,
      signal: controller.signal,
    });

    assert.equal(localResult.items[0].id, 'local-conversation');
    assert.equal(cloudResult.items[0].id, 'cloud-conversation');
    assert.equal(Object.isFrozen(local), true);
    assert.equal(Object.isFrozen(cloud), true);
    assert.deepEqual(Object.keys(local), ['listConversations']);
    assert.equal(fetchCalls.length, 1);
    const localUrl = new URL(fetchCalls[0].input);
    assert.equal(localUrl.origin, 'http://127.0.0.1:46931');
    assert.equal(localUrl.pathname, '/api/v1/agent/conversations');
    assert.equal(localUrl.searchParams.get('project_id'), 'project / one');
    assert.equal(localUrl.searchParams.get('workspace_id'), 'workspace / one');
    assert.equal(localUrl.searchParams.get('unbound_only'), null);
    assert.equal(fetchCalls[0].init.signal, controller.signal);
    const headers = new Headers(fetchCalls[0].init.headers);
    assert.equal(headers.get('Authorization'), 'Bearer workspace-conversation-session');
    assert.equal(headers.get('X-Agistack-Launch'), 'workspace-conversation-launch');
    assert.equal(cloudCommands.length, 1);
    assert.equal(cloudCommands[0].command, 'cloud_request');
    assert.equal(cloudCommands[0].args.request.method, 'GET');
    assert.equal(cloudCommands[0].args.request.path.includes('unbound_only=true'), true);
    assert.equal(JSON.stringify(cloudCommands).includes('Bearer'), false);
    assert.equal(JSON.stringify(cloudCommands).includes('workspace-conversation-session'), false);
    await generation.dispose();
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});
