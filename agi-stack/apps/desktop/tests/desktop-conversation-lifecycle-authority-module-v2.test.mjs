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
const { desktopBackendStoresAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopBackendStoresAuthorityModuleV2.js',
);
const { desktopDeadLetterQueueAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopDeadLetterQueueAuthorityModuleV2.js',
);
const { desktopInstanceTemplatesAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopInstanceTemplatesAuthorityModuleV2.js',
);
const { desktopUnifiedRuntimesAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopUnifiedRuntimesAuthorityModuleV2.js',
);
const { desktopTenantEventsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantEventsAuthorityModuleV2.js',
);
const { desktopTenantPatternsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantPatternsAuthorityModuleV2.js',
);
const { desktopTenantDecisionRecordsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantDecisionRecordsAuthorityModuleV2.js',
);
const { desktopTenantSettingsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantSettingsAuthorityModuleV2.js',
);
const { desktopTenantWebhooksAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantWebhooksAuthorityModuleV2.js',
);
const { desktopTenantBillingAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantBillingAuthorityModuleV2.js',
);

const { desktopTenantAuditAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantAuditAuthorityModuleV2.js',
);
const { desktopTenantGovernanceAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantGovernanceAuthorityModuleV2.js',
);
const { desktopTenantAcpAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantAcpAuthorityModuleV2.js',
);
const { desktopTenantEvolutionAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantEvolutionAuthorityModuleV2.js',
);
const { desktopTenantGenesAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantGenesAuthorityModuleV2.js',
);
const { desktopTenantTemplatesAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantTemplatesAuthorityModuleV2.js',
);
const { desktopProjectChannelsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopProjectChannelsAuthorityModuleV2.js',
);
const { desktopUserProfileAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopUserProfileAuthorityModuleV2.js',
);
const { desktopTenantAgentDefinitionsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantAgentDefinitionsAuthorityModuleV2.js',
);
const { desktopTenantPromptTemplatesAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantPromptTemplatesAuthorityModuleV2.js',
);
const { desktopTenantSubAgentDefinitionsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantSubAgentDefinitionsAuthorityModuleV2.js',
);
const { desktopTenantOrganizationSettingsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantOrganizationSettingsAuthorityModuleV2.js',
);
const { desktopTenantTrustAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantTrustAuthorityModuleV2.js',
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
  DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_MODULE_REF_V2,
  DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_SERVICE_V2,
  DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_VERSION_V2,
  DesktopConversationLifecycleAuthorityUnavailableErrorV2,
  applyDesktopConversationLifecycleAuthorityV2,
  createDesktopConversationLifecycleOperationsV2,
  desktopConversationLifecycleAuthorityDefinitionV2,
  withDesktopConversationLifecycleAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopConversationLifecycleAuthorityModuleV2.js');
const { DesktopApiError } = require(COMPILED_ROOT + '/src/api/client.js');
const { desktopConversationConfigAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopConversationConfigAuthorityModuleV2.js',
);
const { desktopHitlResponseAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopHitlResponseAuthorityModuleV2.js',
);
const { desktopMyWorkAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopMyWorkAuthorityModuleV2.js',
);
const {
  desktopPluginMarketplaceCatalogDefinitionV2,
  desktopPluginMarketplaceManagementDefinitionV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopPluginMarketplaceAuthorityModulesV2.js');
const { desktopSessionProjectionAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopSessionProjectionAuthorityModuleV2.js',
);
const { desktopSessionRunChangesAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopSessionRunChangesAuthorityModuleV2.js',
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
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceConversationCatalogAuthorityModuleV2.js',
);
const { desktopWorkspaceExecutionSnapshotAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceExecutionSnapshotAuthorityModuleV2.js',
);
const { desktopTerminalLifecycleAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTerminalLifecycleAuthorityModuleV2.js',
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
const { desktopWorkspaceContextAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceContextAuthorityModuleV2.js',
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
    desktopBackendStoresAuthorityDefinitionV2,
    desktopDeadLetterQueueAuthorityDefinitionV2,
    desktopInstanceTemplatesAuthorityDefinitionV2,
    desktopUnifiedRuntimesAuthorityDefinitionV2,
    desktopTenantEventsAuthorityDefinitionV2,
    desktopTenantPatternsAuthorityDefinitionV2,
    desktopTenantDecisionRecordsAuthorityDefinitionV2,
    desktopTenantSettingsAuthorityDefinitionV2,
    desktopTenantWebhooksAuthorityDefinitionV2,
    desktopTenantBillingAuthorityDefinitionV2,
    desktopTenantAuditAuthorityDefinitionV2,
    desktopTenantGovernanceAuthorityDefinitionV2,
    desktopTenantAcpAuthorityDefinitionV2,
    desktopTenantEvolutionAuthorityDefinitionV2,
  desktopTenantGenesAuthorityDefinitionV2,
  desktopTenantTemplatesAuthorityDefinitionV2,
  desktopProjectChannelsAuthorityDefinitionV2,
    desktopUserProfileAuthorityDefinitionV2,
    desktopTenantAgentDefinitionsAuthorityDefinitionV2,
    desktopTenantPromptTemplatesAuthorityDefinitionV2,
    desktopTenantSubAgentDefinitionsAuthorityDefinitionV2,
  desktopTenantOrganizationSettingsAuthorityDefinitionV2,
    desktopTenantTrustAuthorityDefinitionV2,
    desktopSessionArtifactActionAuthorityDefinitionV2,
    desktopSessionRunControlAuthorityDefinitionV2,
    desktopWorkspaceContextAuthorityDefinitionV2,
    desktopPluginMarketplaceCatalogDefinitionV2,
    desktopPluginMarketplaceManagementDefinitionV2,
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
  ];
}

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46441',
    apiKey: 'lifecycle-session',
    localApiToken: 'lifecycle-launch',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    workspaceRoot: '/workspace',
    ...overrides,
  };
}

function conversation(overrides = {}) {
  return {
    id: 'conversation-1',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    workspace_id: 'workspace-1',
    user_id: 'user-1',
    title: 'Conversation one',
    status: 'active',
    message_count: 1,
    created_at: '2026-09-02T00:00:00Z',
    agent_config: {},
    ...overrides,
  };
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function acceptedActions(service, digest, lifecycle = []) {
  return {
    acquireServiceOperationLease: async (request) => {
      lifecycle.push({ type: 'acquire', digest, request });
      let released = false;
      return {
        status: 'accepted',
        digest,
        useService(operation) {
          if (released) throw new Error('lease_released');
          return operation(service);
        },
        async release() {
          if (released) return;
          released = true;
          lifecycle.push({ type: 'release', digest });
        },
      };
    },
  };
}

test('generated contract exposes one credential-free root lifecycle Provider', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const bootstrap = loadBootstrap();
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-conversation-lifecycle-authority',
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_SERVICE_V2,
        version: DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_VERSION_V2,
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
    desktopConversationLifecycleAuthorityDefinitionV2.contractDigest,
  );
  assert.equal(catalog.entrypoint, 'applyDesktopConversationLifecycleAuthorityV2');
  assert.equal(
    catalog.artifact_source,
    'repo+typescript://agi-stack/apps/desktop/src/plugins/' +
      'desktopConversationLifecycleAuthorityModuleV2.ts',
  );
  assert.equal(entry.module_ref, DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_MODULE_REF_V2);
  assert.equal(entry.parent_entry_id, 'builtin-desktop-renderer-host');
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-client' });
  assert.deepEqual(entry.inject, {});
  assert.equal(entry.enabled, true);
  assert.match(profile, /entry_id: builtin-desktop-conversation-lifecycle-authority/u);
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(JSON.stringify(value), /apiKey|localApiToken|Authorization/iu);
  }
});

test('Loader activates the exact service and failed candidate preserves last-good', async () => {
  const bootstrap = loadBootstrap();
  const loader = new LoaderV2(rendererDefinitions(), 'desktop-renderer');
  const generation = await loader.stage(bootstrap);
  const service = generation.resolve(
    DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_SERVICE_V2,
    { kind: 'root' },
    { version: DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindOperation']);
  assert.equal('config' in service, false);
  assert.equal('client' in service, false);
  assert.throws(
    () =>
      applyDesktopConversationLifecycleAuthorityV2(
        {
          provide: () => assert.fail('invalid config must not provide a service'),
        },
        { strategy: 'legacy-client' },
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_conversation_lifecycle_authority_config_invalid',
  );

  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-conversation-lifecycle-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_SERVICE_V2,
        {
          kind: 'session',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          session_id: 'conversation-1',
        },
        { version: DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_VERSION_V2 },
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service',
  );

  const manager = new GenerationManagerV2();
  await manager.publish(generation);
  const wrongDefinitionLoader = new LoaderV2(
    rendererDefinitions().map((definition) =>
      definition.moduleRef === DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_MODULE_REF_V2
        ? { ...definition, contractDigest: 'sha256:' + '0'.repeat(64) }
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

test('local transport preserves exact methods, paths, bodies and credentials', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    if (init.method === 'DELETE') return new Response(null, { status: 204 });
    if (init.method === 'PATCH') {
      return json(conversation({ title: JSON.parse(String(init.body)).title }));
    }
    return json(conversation({ summary: 'Generated summary' }));
  };

  try {
    const generation = await new LoaderV2(rendererDefinitions(), 'desktop-renderer').stage(
      loadBootstrap(),
    );
    const service = generation.resolve(
      DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_VERSION_V2 },
    );
    const authority = service.bindOperation(runtimeConfig());
    const renamed = await authority.updateAgentConversationTitle(
      conversation(),
      'Renamed conversation',
    );
    const summarized = await authority.generateAgentConversationSummary(conversation());
    await authority.deleteAgentConversation(conversation());

    assert.equal(renamed.title, 'Renamed conversation');
    assert.equal(summarized.summary, 'Generated summary');
    assert.equal(calls.length, 3);
    assert.deepEqual(
      calls.map((call) => {
        const url = new URL(call.input);
        return {
          method: call.init.method,
          path: url.pathname,
          query: url.search,
        };
      }),
      [
        {
          method: 'PATCH',
          path: '/api/v1/agent/conversations/conversation-1/title',
          query: '?project_id=project-1',
        },
        {
          method: 'POST',
          path: '/api/v1/agent/conversations/conversation-1/summary',
          query: '?project_id=project-1',
        },
        {
          method: 'DELETE',
          path: '/api/v1/agent/conversations/conversation-1',
          query: '?project_id=project-1',
        },
      ],
    );
    assert.deepEqual(JSON.parse(String(calls[0].init.body)), {
      title: 'Renamed conversation',
    });
    assert.deepEqual(JSON.parse(String(calls[1].init.body)), {});
    for (const call of calls) {
      const headers = new Headers(call.init.headers);
      assert.equal(headers.get('Authorization'), 'Bearer lifecycle-session');
      assert.equal(headers.get('X-Agistack-Launch'), 'lifecycle-launch');
    }
    await generation.dispose();
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('cloud summary uses the vault-bound request broker without renderer credentials', async () => {
  const originalWindow = globalThis.window;
  const commands = [];
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          commands.push({ command, args });
          return {
            status: 200,
            body: conversation({ summary: 'Cloud summary' }),
          };
        },
      },
    },
  };

  try {
    let service;
    applyDesktopConversationLifecycleAuthorityV2(
      { provide: (_key, provided) => (service = provided) },
      { strategy: 'desktop-api-client' },
    );
    const result = await service
      .bindOperation(
        runtimeConfig({
          apiBaseUrl: 'https://cloud.example.test',
          apiKey: '',
          localApiToken: '',
          mode: 'cloud',
        }),
      )
      .generateAgentConversationSummary(conversation());

    assert.equal(result.summary, 'Cloud summary');
    assert.equal(commands.length, 1);
    assert.equal(commands[0].command, 'cloud_request');
    assert.equal(typeof commands[0].args.requestId, 'string');
    assert.deepEqual(commands[0].args.request, {
      path: '/api/v1/agent/conversations/conversation-1/summary?project_id=project-1',
      method: 'POST',
      body: {},
    });
    assert.doesNotMatch(JSON.stringify(commands), /Authorization|lifecycle-session/u);
  } finally {
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test('operations freeze config, identity and title before exact session leases', async () => {
  const lifecycle = [];
  const received = [];
  const service = Object.freeze({
    bindOperation(config) {
      received.push({ config });
      return Object.freeze({
        async deleteAgentConversation(identity) {
          received.push({ method: 'delete', identity });
        },
        async generateAgentConversationSummary(identity) {
          received.push({ method: 'summary', identity });
          return conversation({ summary: 'Summary' });
        },
        async updateAgentConversationTitle(identity, title) {
          received.push({ method: 'title', identity, title });
          return conversation({ title });
        },
      });
    },
  });
  const operations = createDesktopConversationLifecycleOperationsV2(() =>
    acceptedActions(service, 'sha256:generation-1', lifecycle),
  );
  const config = runtimeConfig();
  const currentConversation = conversation();
  const pending = operations.updateAgentConversationTitle({
    config,
    conversation: currentConversation,
    title: '  Stable title  ',
  });
  config.apiBaseUrl = 'http://127.0.0.1:49999';
  currentConversation.id = 'mutated-conversation';

  assert.equal((await pending).title, 'Stable title');
  await operations.generateAgentConversationSummary({
    config: runtimeConfig(),
    conversation: conversation(),
  });
  await operations.deleteAgentConversation({
    config: runtimeConfig(),
    conversation: conversation(),
  });

  assert.equal(Object.isFrozen(operations), true);
  assert.equal(Object.isFrozen(received[0].config), true);
  assert.equal(received[0].config.apiBaseUrl, 'http://127.0.0.1:46441');
  assert.equal(Object.isFrozen(received[1].identity), true);
  assert.equal(received[1].identity.id, 'conversation-1');
  assert.equal(received[1].title, 'Stable title');
  assert.deepEqual(
    lifecycle.filter((event) => event.type === 'acquire').map((event) => event.request),
    Array.from({ length: 3 }, () => ({
      service: DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_SERVICE_V2,
      version: DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_VERSION_V2,
      scope: {
        kind: 'session',
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        session_id: 'conversation-1',
      },
    })),
  );
  assert.deepEqual(
    lifecycle.filter((event) => event.type === 'release').map((event) => event.digest),
    ['sha256:generation-1', 'sha256:generation-1', 'sha256:generation-1'],
  );
});

test('invalid input and scope mismatch fail before acquiring a lease', () => {
  let acquireCount = 0;
  const operations = createDesktopConversationLifecycleOperationsV2(() => ({
    acquireServiceOperationLease: async () => {
      acquireCount += 1;
      return {
        status: 'rejected',
        reasonCode: 'desktop_renderer_service_resolve_failed',
      };
    },
  }));
  const update = (configOverrides = {}, conversationOverrides = {}, title = 'Title') =>
    operations.updateAgentConversationTitle({
      config: runtimeConfig(configOverrides),
      conversation: conversation(conversationOverrides),
      title,
    });

  for (const configOverrides of [
    { tenantId: 'tenant-other' },
    { projectId: 'project-other' },
    { workspaceId: 'workspace-other' },
  ]) {
    assert.throws(
      () => update(configOverrides),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_conversation_lifecycle_scope_mismatch',
    );
  }
  for (const [conversationOverrides, title] of [
    [{ id: '' }, 'Title'],
    [{ tenant_id: ' tenant-1' }, 'Title'],
    [{ project_id: '' }, 'Title'],
    [{ workspace_id: '' }, 'Title'],
    [{}, '   '],
  ]) {
    assert.throws(
      () => update({}, conversationOverrides, title),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_conversation_lifecycle_input_invalid',
    );
  }
  assert.equal(acquireCount, 0);
});

test('response drift and non-2xx failures remain fail-closed', async () => {
  const originalFetch = globalThis.fetch;
  let response = conversation({ title: 'Unexpected title' });
  let status = 200;
  globalThis.fetch = async () => json(response, status);

  try {
    let service;
    applyDesktopConversationLifecycleAuthorityV2(
      { provide: (_key, provided) => (service = provided) },
      { strategy: 'desktop-api-client' },
    );
    const authority = service.bindOperation(runtimeConfig());
    await assert.rejects(
      authority.updateAgentConversationTitle(conversation(), 'Expected title'),
      (error) => error instanceof DesktopApiError && error.status === 502,
    );

    response = conversation({ id: 'conversation-other' });
    await assert.rejects(
      authority.generateAgentConversationSummary(conversation()),
      (error) => error instanceof DesktopApiError && error.status === 502,
    );

    response = {
      detail: { reason_code: 'conversation_lifecycle_unavailable' },
    };
    status = 503;
    await assert.rejects(authority.deleteAgentConversation(conversation()), (error) => {
      assert.equal(error instanceof DesktopApiError, true);
      assert.equal(error.status, 503);
      assert.deepEqual(error.payload, response);
      return true;
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('missing service is structured and release revokes escaped authority exactly once', async () => {
  let currentActions = null;
  const operations = createDesktopConversationLifecycleOperationsV2(() => currentActions);
  const input = { config: runtimeConfig(), conversation: conversation() };
  assert.throws(
    () => operations.deleteAgentConversation(input),
    (error) =>
      error instanceof DesktopConversationLifecycleAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );

  currentActions = {
    acquireServiceOperationLease: async () => ({
      status: 'rejected',
      reasonCode: 'desktop_renderer_service_resolve_failed',
      runtimeCode: 'missing_service',
    }),
  };
  await assert.rejects(
    operations.deleteAgentConversation(input),
    (error) =>
      error instanceof DesktopConversationLifecycleAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_service_resolve_failed' &&
      error.runtimeCode === 'missing_service',
  );

  let releaseStartedResolve;
  let finishRelease;
  const releaseStarted = new Promise((resolve) => (releaseStartedResolve = resolve));
  const releasePending = new Promise((resolve) => (finishRelease = resolve));
  let escapedAuthority = null;
  let transportCalls = 0;
  let releaseCount = 0;
  const releasing = withDesktopConversationLifecycleAuthorityOperationV2(
    {
      acquireServiceOperationLease: async () => ({
        status: 'accepted',
        digest: 'sha256:deferred',
        useService(operation) {
          return operation({
            bindOperation() {
              return Object.freeze({
                async deleteAgentConversation() {
                  transportCalls += 1;
                },
                async generateAgentConversationSummary() {
                  transportCalls += 1;
                  return conversation();
                },
                async updateAgentConversationTitle() {
                  transportCalls += 1;
                  return conversation();
                },
              });
            },
          });
        },
        async release() {
          releaseCount += 1;
          releaseStartedResolve();
          await releasePending;
        },
      }),
    },
    input,
    (authority) => {
      escapedAuthority = authority;
      return conversation();
    },
  );
  await releaseStarted;
  assert.throws(
    () => escapedAuthority.deleteAgentConversation(conversation()),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_conversation_lifecycle_operation_released',
  );
  assert.equal(transportCalls, 0);
  finishRelease();
  await releasing;
  assert.equal(releaseCount, 1);

  const primary = new Error('conversation_lifecycle_primary_failure');
  await assert.rejects(
    withDesktopConversationLifecycleAuthorityOperationV2(
      {
        acquireServiceOperationLease: async () => ({
          status: 'accepted',
          digest: 'sha256:release-failure',
          useService: (operation) => operation({ bindOperation: () => ({}) }),
          async release() {
            throw new Error('conversation_lifecycle_release_failure');
          },
        }),
      },
      input,
      () => {
        throw primary;
      },
    ),
    (error) => error === primary,
  );
});

test('HMR pins an in-flight mutation and the next operation uses the new generation', async () => {
  const lifecycle = [];
  let resolveOld;
  const oldPending = new Promise((resolve) => (resolveOld = resolve));
  const serviceFor = (label) =>
    Object.freeze({
      bindOperation() {
        return Object.freeze({
          async deleteAgentConversation() {},
          async generateAgentConversationSummary() {
            return conversation({ summary: label });
          },
          async updateAgentConversationTitle(_identity, title) {
            lifecycle.push('update:' + label);
            if (label === 'old') await oldPending;
            return conversation({ title });
          },
        });
      },
    });
  let currentActions = acceptedActions(serviceFor('old'), 'sha256:old', lifecycle);
  const operations = createDesktopConversationLifecycleOperationsV2(() => currentActions);
  const input = {
    config: runtimeConfig(),
    conversation: conversation(),
    title: 'Renamed',
  };
  const oldMutation = operations.updateAgentConversationTitle(input);
  await Promise.resolve();
  currentActions = acceptedActions(serviceFor('next'), 'sha256:next', lifecycle);
  const nextMutation = await operations.updateAgentConversationTitle(input);
  resolveOld();
  const oldMutationResult = await oldMutation;

  assert.equal(oldMutationResult.title, 'Renamed');
  assert.equal(nextMutation.title, 'Renamed');
  assert.deepEqual(
    lifecycle.filter((event) => typeof event === 'string'),
    ['update:old', 'update:next'],
  );
  assert.deepEqual(
    lifecycle.filter((event) => event.type === 'release').map((event) => event.digest),
    ['sha256:next', 'sha256:old'],
  );
});
