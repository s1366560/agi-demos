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
  DESKTOP_TENANT_OVERVIEW_AUTHORITY_MODULE_REF_V2,
  DESKTOP_TENANT_OVERVIEW_AUTHORITY_SERVICE_V2,
  DESKTOP_TENANT_OVERVIEW_AUTHORITY_VERSION_V2,
  applyDesktopTenantOverviewAuthorityV2,
  desktopTenantOverviewAuthorityDefinitionV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopTenantOverviewAuthorityModuleV2.js');

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
  'desktopPluginMarketplaceAuthorityModulesV2',
  'desktopProjectOverviewAuthorityModuleV2',
  'desktopProjectAgentDashboardAuthorityModuleV2',
  'desktopProjectAgentLogsAuthorityModuleV2',
  'desktopProjectAgentPatternsAuthorityModuleV2',
  'desktopProjectEntitiesAuthorityModuleV2',
  'desktopProjectCommunitiesAuthorityModuleV2',
  'desktopProjectMemoriesAuthorityModuleV2',
  'desktopProjectTeamAuthorityModuleV2',
  'desktopProjectGraphAuthorityModuleV2',
  'desktopProjectBlackboardAuthorityModuleV2',
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
  'desktopSessionRunInputAuthorityModuleV2',
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
  'desktopWorkspaceLifecycleAuthorityModuleV2',
  'desktopWorkspaceMemberMutationAuthorityModuleV2',
  'desktopWorkspaceMessageCatalogAuthorityModuleV2',
  'desktopWorkspaceRosterAuthorityModuleV2',
].flatMap((moduleName) =>
  Object.values(require(`${COMPILED_ROOT}/src/plugins/${moduleName}.js`)).filter(
    (value) => value?.moduleRef && typeof value?.apply === 'function',
  ),
);

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

function bootstrap() {
  return JSON.parse(readFileSync(BOOTSTRAP_PATH, 'utf8'));
}

test('generated contract declares one credential-free root tenant overview Provider', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_TENANT_OVERVIEW_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_TENANT_OVERVIEW_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap().entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-tenant-overview-authority',
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_TENANT_OVERVIEW_AUTHORITY_SERVICE_V2,
        version: DESKTOP_TENANT_OVERVIEW_AUTHORITY_VERSION_V2,
      },
    ],
    requires: [],
  });
  assert.deepEqual(module.contract.events, { emits: [], handles: [] });
  assert.equal(module.contract.config_schema.additionalProperties, false);
  assert.deepEqual(module.contract.config_schema.required, ['strategy']);
  assert.equal(module.contract.config_schema.properties.strategy.const, 'desktop-api-fetch');
  assert.equal(module.contract_digest, catalog.contract_digest);
  assert.equal(module.contract_digest, desktopTenantOverviewAuthorityDefinitionV2.contractDigest);
  assert.equal(catalog.entrypoint, 'applyDesktopTenantOverviewAuthorityV2');
  assert.equal(
    catalog.artifact_source,
    'repo+typescript://agi-stack/apps/desktop/src/plugins/' +
      'desktopTenantOverviewAuthorityModuleV2.ts',
  );
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-fetch' });
  assert.deepEqual(entry.inject, {});
  assert.equal(entry.enabled, true);
  assert.match(profile, /entry_id: builtin-desktop-tenant-overview-authority/u);
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(
      JSON.stringify(value),
      /apiKey|localApiToken|Authorization|tenant-overview-secret/iu,
    );
  }
});

test('Loader activates the exact service and disabled Profile fails closed', async () => {
  const definitions = [...createDesktopRendererDefinitionsV2(), ...authorityModules];
  const loader = new LoaderV2(definitions, 'desktop-renderer');
  const generation = await loader.stage(bootstrap());
  const service = generation.resolve(
    DESKTOP_TENANT_OVERVIEW_AUTHORITY_SERVICE_V2,
    { kind: 'root' },
    { version: DESKTOP_TENANT_OVERVIEW_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindOperation']);
  assert.throws(
    () =>
      applyDesktopTenantOverviewAuthorityV2(
        { provide: () => assert.fail('invalid config must not publish') },
        { strategy: 'legacy-client' },
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_tenant_overview_authority_config_invalid',
  );

  const disabled = structuredClone(bootstrap());
  disabled.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-tenant-overview-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_TENANT_OVERVIEW_AUTHORITY_SERVICE_V2,
        { kind: 'root' },
        { version: DESKTOP_TENANT_OVERVIEW_AUTHORITY_VERSION_V2 },
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service',
  );

  await disabledGeneration.dispose();
  await generation.dispose();
});
