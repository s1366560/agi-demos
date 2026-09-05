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
const { desktopTenantProvidersAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantProvidersAuthorityModuleV2.js',
);
const { desktopWorkspaceAgentPolicyAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceAgentPolicyAuthorityModuleV2.js',
);
const { desktopTenantSkillDefinitionsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantSkillDefinitionsAuthorityModuleV2.js',
);
const { desktopTenantSkillPackagesAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantSkillPackagesAuthorityModuleV2.js',
);
const { desktopTenantSkillEvolutionAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantSkillEvolutionAuthorityModuleV2.js',
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
  DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_MODULE_REF_V2,
  DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_SERVICE_V2,
  DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_VERSION_V2,
  DesktopWorkspaceMessageCatalogAuthorityUnavailableErrorV2,
  applyDesktopWorkspaceMessageCatalogAuthorityV2,
  createDesktopWorkspaceMessageCatalogOperationsV2,
  desktopWorkspaceMessageCatalogAuthorityDefinitionV2,
  withDesktopWorkspaceMessageCatalogAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopWorkspaceMessageCatalogAuthorityModuleV2.js');
const { desktopWorkspaceCatalogAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceCatalogAuthorityModuleV2.js',
);
const {
  desktopPluginMarketplaceCatalogDefinitionV2,
  desktopPluginMarketplaceManagementDefinitionV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopPluginMarketplaceAuthorityModulesV2.js');
const { desktopConversationConfigAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopConversationConfigAuthorityModuleV2.js',
);
const { desktopConversationLifecycleAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopConversationLifecycleAuthorityModuleV2.js',
);
const { desktopHitlResponseAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopHitlResponseAuthorityModuleV2.js',
);
const { desktopMyWorkAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopMyWorkAuthorityModuleV2.js',
);
const { desktopSessionProjectionAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopSessionProjectionAuthorityModuleV2.js',
);
const { desktopSessionRunChangesAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopSessionRunChangesAuthorityModuleV2.js',
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
    desktopTenantSkillDefinitionsAuthorityDefinitionV2,
    desktopTenantProvidersAuthorityDefinitionV2,
    desktopWorkspaceAgentPolicyAuthorityDefinitionV2,
    desktopTenantSkillPackagesAuthorityDefinitionV2,
    desktopTenantSkillEvolutionAuthorityDefinitionV2,
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
    apiBaseUrl: 'http://127.0.0.1:46501',
    apiKey: 'workspace-message-session',
    localApiToken: 'workspace-message-launch',
    mode: 'local',
    tenantId: 'tenant / one',
    projectId: 'project / one',
    workspaceId: 'workspace / one',
    workspaceRoot: '/workspace',
    ...overrides,
  };
}

function json(payload) {
  return new Response(JSON.stringify(payload), {
    status: 200,
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

test('generated manifest, catalog and Profile expose one credential-free root Provider', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const bootstrap = loadBootstrap();
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-workspace-message-catalog-authority',
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_SERVICE_V2,
        version: DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_VERSION_V2,
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
    desktopWorkspaceMessageCatalogAuthorityDefinitionV2.contractDigest,
  );
  assert.equal(catalog.entrypoint, 'applyDesktopWorkspaceMessageCatalogAuthorityV2');
  assert.equal(
    catalog.artifact_source,
    'repo+typescript://agi-stack/apps/desktop/src/plugins/' +
      'desktopWorkspaceMessageCatalogAuthorityModuleV2.ts',
  );
  assert.equal(entry.module_ref, DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_MODULE_REF_V2);
  assert.equal(entry.parent_entry_id, 'builtin-desktop-renderer-host');
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-client' });
  assert.deepEqual(entry.inject, {});
  assert.equal(entry.enabled, true);
  assert.match(profile, /entry_id: builtin-desktop-workspace-message-catalog-authority/u);
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(
      JSON.stringify(value),
      /apiKey|localApiToken|Authorization|workspace-message-session/iu,
    );
  }
});

test('Loader activates the exact service and Profile disable removes it without fallback', async () => {
  const bootstrap = loadBootstrap();
  const loader = new LoaderV2(rendererDefinitions(), 'desktop-renderer');
  const generation = await loader.stage(bootstrap);
  const service = generation.resolve(
    DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_SERVICE_V2,
    { kind: 'project', tenant_id: 'tenant / one', project_id: 'project / one' },
    { version: DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindOperation']);
  assert.equal('config' in service, false);
  assert.equal('client' in service, false);
  assert.throws(
    () =>
      applyDesktopWorkspaceMessageCatalogAuthorityV2(
        {
          provide: () => assert.fail('invalid config must not provide a service'),
        },
        { strategy: 'legacy-client' },
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_message_catalog_authority_config_invalid',
  );

  const invalid = structuredClone(bootstrap);
  invalid.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-workspace-message-catalog-authority',
  ).config.strategy = 'legacy-client';
  await assert.rejects(
    loader.stage(invalid),
    (error) => error instanceof RuntimeV2Error && error.code === 'invalid_module_config',
  );

  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-workspace-message-catalog-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_SERVICE_V2,
        {
          kind: 'project',
          tenant_id: 'tenant / one',
          project_id: 'project / one',
        },
        { version: DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_VERSION_V2 },
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service',
  );

  const manager = new GenerationManagerV2();
  await manager.publish(generation);
  const wrongDefinitionLoader = new LoaderV2(
    rendererDefinitions().map((definition) =>
      definition.moduleRef === DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_MODULE_REF_V2
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

test('local and cloud operations freeze config and forward AbortSignal through exact transport', async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const fetchCalls = [];
  const cloudCommands = [];
  globalThis.fetch = async (input, init) => {
    fetchCalls.push({ input: String(input), init });
    return json({
      messages: [{ id: 'local-message', content: 'Local message' }],
    });
  };
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          cloudCommands.push({ command, args });
          return {
            status: 200,
            body: {
              messages: [{ id: 'cloud-message', content: 'Cloud message' }],
            },
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
      DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_SERVICE_V2,
      {
        kind: 'project',
        tenant_id: 'tenant / one',
        project_id: 'project / one',
      },
      { version: DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_VERSION_V2 },
    );
    const controller = new AbortController();
    const localConfig = runtimeConfig();
    const local = service.bindOperation(localConfig);
    localConfig.apiBaseUrl = 'http://127.0.0.1:46999';
    localConfig.apiKey = 'mutated-session';
    localConfig.workspaceId = 'mutated-workspace';
    const cloud = service.bindOperation(
      runtimeConfig({
        apiBaseUrl: 'https://cloud.example.test',
        apiKey: '',
        localApiToken: '',
        mode: 'cloud',
      }),
    );

    assert.deepEqual(await local.listMessages(controller.signal), [
      { id: 'local-message', content: 'Local message' },
    ]);
    assert.deepEqual(await cloud.listMessages(controller.signal), [
      { id: 'cloud-message', content: 'Cloud message' },
    ]);
    assert.equal(Object.isFrozen(local), true);
    assert.equal(Object.isFrozen(cloud), true);
    assert.deepEqual(Object.keys(local), ['listMessages']);
    assert.equal(fetchCalls.length, 1);
    const localUrl = new URL(fetchCalls[0].input);
    assert.equal(localUrl.origin, 'http://127.0.0.1:46501');
    assert.equal(
      localUrl.pathname,
      '/api/v1/tenants/tenant%20%2F%20one/projects/project%20%2F%20one/' +
        'workspaces/workspace%20%2F%20one/messages',
    );
    assert.equal(fetchCalls[0].init.signal, controller.signal);
    const headers = new Headers(fetchCalls[0].init.headers);
    assert.equal(headers.get('Authorization'), 'Bearer workspace-message-session');
    assert.equal(headers.get('X-Agistack-Launch'), 'workspace-message-launch');
    assert.equal(cloudCommands.length, 1);
    assert.equal(cloudCommands[0].command, 'cloud_request');
    assert.equal(
      cloudCommands[0].args.request.path,
      '/api/v1/tenants/tenant%20%2F%20one/projects/project%20%2F%20one/' +
        'workspaces/workspace%20%2F%20one/messages',
    );
    assert.equal(cloudCommands[0].args.request.method, 'GET');
    assert.equal(JSON.stringify(cloudCommands).includes('Bearer'), false);
    await generation.dispose();
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test('operations acquire the current project generation lease and release after refresh', async () => {
  const lifecycle = [];
  const signals = [];
  const boundConfigs = [];
  const service = Object.freeze({
    bindOperation(config) {
      boundConfigs.push(config);
      return Object.freeze({
        async listMessages(signal) {
          signals.push(signal);
          lifecycle.push('list');
          return [{ id: 'message-1', content: 'Pinned message' }];
        },
      });
    },
  });
  let currentActions = acceptedActions(service, 'sha256:generation-1', lifecycle);
  const operations = createDesktopWorkspaceMessageCatalogOperationsV2(() => currentActions);
  const controller = new AbortController();
  const config = runtimeConfig();
  const pending = operations.listMessages({
    config,
    signal: controller.signal,
  });
  config.apiBaseUrl = 'http://127.0.0.1:46999';
  config.apiKey = 'mutated-session';
  currentActions = null;

  assert.deepEqual(await pending, [{ id: 'message-1', content: 'Pinned message' }]);
  assert.equal(Object.isFrozen(operations), true);
  assert.equal(Object.isFrozen(boundConfigs[0]), true);
  assert.equal(boundConfigs[0].apiBaseUrl, 'http://127.0.0.1:46501');
  assert.equal(boundConfigs[0].apiKey, 'workspace-message-session');
  assert.equal(signals[0], controller.signal);
  assert.deepEqual(lifecycle[0].request, {
    service: DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_SERVICE_V2,
    version: DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_VERSION_V2,
    scope: {
      kind: 'project',
      tenant_id: 'tenant / one',
      project_id: 'project / one',
    },
  });
  assert.deepEqual(
    lifecycle.filter((event) => typeof event === 'string'),
    ['list'],
  );
  assert.deepEqual(
    lifecycle.filter((event) => event.type === 'release').map((event) => event.digest),
    ['sha256:generation-1'],
  );
  assert.throws(
    () => operations.listMessages({ config: runtimeConfig() }),
    (error) =>
      error instanceof DesktopWorkspaceMessageCatalogAuthorityUnavailableErrorV2 &&
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
    operations.listMessages({ config: runtimeConfig() }),
    (error) =>
      error instanceof DesktopWorkspaceMessageCatalogAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_service_resolve_failed' &&
      error.runtimeCode === 'missing_service',
  );
});

test('invalid workspace scope fails before lease admission', () => {
  let acquisitions = 0;
  const operations = createDesktopWorkspaceMessageCatalogOperationsV2(() => ({
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      throw new Error('must_not_acquire');
    },
  }));

  for (const config of [
    runtimeConfig({ tenantId: '' }),
    runtimeConfig({ projectId: ' project-1' }),
    runtimeConfig({ workspaceId: '' }),
  ]) {
    assert.throws(
      () => operations.listMessages({ config }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_message_catalog_input_invalid',
    );
  }
  assert.equal(acquisitions, 0);
});

test('escaped authority is revoked and primary operation failure wins over release failure', async () => {
  const primary = new Error('workspace_message_catalog_primary_failure');
  let escapedAuthority = null;
  let releaseCount = 0;
  const actions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:accepted',
      useService(operation) {
        return operation({
          bindOperation() {
            return Object.freeze({
              async listMessages() {
                return [];
              },
            });
          },
        });
      },
      async release() {
        releaseCount += 1;
        throw new Error('workspace_message_catalog_release_failure');
      },
    }),
  };

  await assert.rejects(
    withDesktopWorkspaceMessageCatalogAuthorityOperationV2(
      actions,
      { config: runtimeConfig() },
      (authority) => {
        escapedAuthority = authority;
        throw primary;
      },
    ),
    (error) => error === primary,
  );
  assert.throws(
    () => escapedAuthority.listMessages(),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_message_catalog_operation_released',
  );
  assert.equal(releaseCount, 1);

  await assert.rejects(
    withDesktopWorkspaceMessageCatalogAuthorityOperationV2(
      actions,
      { config: runtimeConfig() },
      () => [],
    ),
    /workspace_message_catalog_release_failure/u,
  );
  assert.equal(releaseCount, 2);
});

test('HMR lets an in-flight read finish on old generation and sends the next to new', async () => {
  const lifecycle = [];
  let resolveOld;
  const oldPending = new Promise((resolve) => {
    resolveOld = resolve;
  });
  const serviceFor = (label) =>
    Object.freeze({
      bindOperation() {
        return Object.freeze({
          async listMessages() {
            lifecycle.push('list:' + label);
            if (label === 'old') await oldPending;
            return [{ id: 'message-' + label, content: label }];
          },
        });
      },
    });
  let currentActions = acceptedActions(serviceFor('old'), 'sha256:old', lifecycle);
  const operations = createDesktopWorkspaceMessageCatalogOperationsV2(() => currentActions);
  const oldRead = operations.listMessages({ config: runtimeConfig() });
  await Promise.resolve();
  currentActions = acceptedActions(serviceFor('next'), 'sha256:next', lifecycle);
  const nextRead = await operations.listMessages({ config: runtimeConfig() });
  resolveOld();
  const oldReadResult = await oldRead;

  assert.equal(oldReadResult[0].id, 'message-old');
  assert.equal(nextRead[0].id, 'message-next');
  assert.deepEqual(
    lifecycle.filter((event) => typeof event === 'string'),
    ['list:old', 'list:next'],
  );
  assert.deepEqual(
    lifecycle.filter((event) => event.type === 'release').map((event) => event.digest),
    ['sha256:next', 'sha256:old'],
  );
});
