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
  DESKTOP_MY_WORK_AUTHORITY_MODULE_REF_V2,
  DESKTOP_MY_WORK_AUTHORITY_SERVICE_V2,
  DESKTOP_MY_WORK_AUTHORITY_VERSION_V2,
  DesktopMyWorkAuthorityUnavailableErrorV2,
  applyDesktopMyWorkAuthorityV2,
  createDesktopMyWorkOperationsV2,
  desktopMyWorkAuthorityDefinitionV2,
  withDesktopMyWorkAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopMyWorkAuthorityModuleV2.js');
const { desktopConversationConfigAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopConversationConfigAuthorityModuleV2.js',
);
const { desktopConversationLifecycleAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopConversationLifecycleAuthorityModuleV2.js',
);
const { desktopHitlResponseAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopHitlResponseAuthorityModuleV2.js',
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
const { desktopTenantAnalyticsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantAnalyticsAuthorityModuleV2.js',
);
const { desktopTenantCatalogAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantCatalogAuthorityModuleV2.js',
);
const { desktopTenantOverviewAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantOverviewAuthorityModuleV2.js',
);
const { desktopTerminalLifecycleAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTerminalLifecycleAuthorityModuleV2.js',
);
const { desktopWorkspaceCatalogAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceCatalogAuthorityModuleV2.js',
);
const { desktopWorkspaceContextAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceContextAuthorityModuleV2.js',
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
    desktopTenantTrustAuthorityDefinitionV2,
    desktopSessionArtifactActionAuthorityDefinitionV2,
    desktopSessionRunControlAuthorityDefinitionV2,
    desktopPluginMarketplaceCatalogDefinitionV2,
    desktopPluginMarketplaceManagementDefinitionV2,
    desktopConversationConfigAuthorityDefinitionV2,
    desktopConversationLifecycleAuthorityDefinitionV2,
    desktopHitlResponseAuthorityDefinitionV2,
    desktopMyWorkAuthorityDefinitionV2,
    desktopSessionProjectionAuthorityDefinitionV2,
    desktopSessionRunChangesAuthorityDefinitionV2,
    desktopSessionTimelineAuthorityDefinitionV2,
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
    desktopWorkspaceContextAuthorityDefinitionV2,
    desktopWorkspaceCatalogAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopWorkspaceLifecycleAuthorityModuleV2.js')
      .desktopWorkspaceLifecycleAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopWorkspaceRosterAuthorityModuleV2.js')
      .desktopWorkspaceRosterAuthorityDefinitionV2,
    desktopWorkspaceAgentBindingAuthorityDefinitionV2,
    desktopWorkspaceAutonomyAttentionAuthorityDefinitionV2,
    desktopWorkspaceMemberMutationAuthorityDefinitionV2,
    desktopWorkspaceConversationCatalogAuthorityDefinitionV2,
    desktopWorkspaceExecutionSnapshotAuthorityDefinitionV2,
    desktopWorkspaceMessageCatalogAuthorityDefinitionV2,
  ];
}

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46701',
    apiKey: 'my-work-session',
    localApiToken: 'my-work-launch',
    mode: 'local',
    tenantId: 'tenant / one',
    projectId: 'project / one',
    workspaceId: 'workspace / one',
    workspaceRoot: '/workspace',
    ...overrides,
  };
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function memoryStorage() {
  const values = new Map();
  return {
    getItem(key) {
      return values.get(key) ?? null;
    },
    setItem(key, value) {
      values.set(key, String(value));
    },
    removeItem(key) {
      values.delete(key);
    },
  };
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

test('generated contract exposes one credential-free root My Work Provider', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const bootstrap = loadBootstrap();
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_MY_WORK_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_MY_WORK_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-my-work-authority',
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_MY_WORK_AUTHORITY_SERVICE_V2,
        version: DESKTOP_MY_WORK_AUTHORITY_VERSION_V2,
      },
    ],
    requires: [],
  });
  assert.deepEqual(module.contract.events, { emits: [], handles: [] });
  assert.equal(module.contract.config_schema.additionalProperties, false);
  assert.deepEqual(module.contract.config_schema.required, ['strategy']);
  assert.equal(module.contract.config_schema.properties.strategy.const, 'desktop-api-client');
  assert.equal(module.contract_digest, catalog.contract_digest);
  assert.equal(module.contract_digest, desktopMyWorkAuthorityDefinitionV2.contractDigest);
  assert.equal(catalog.entrypoint, 'applyDesktopMyWorkAuthorityV2');
  assert.equal(
    catalog.artifact_source,
    'repo+typescript://agi-stack/apps/desktop/src/plugins/desktopMyWorkAuthorityModuleV2.ts',
  );
  assert.equal(entry.module_ref, DESKTOP_MY_WORK_AUTHORITY_MODULE_REF_V2);
  assert.equal(entry.parent_entry_id, 'builtin-desktop-renderer-host');
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-client' });
  assert.deepEqual(entry.inject, {});
  assert.equal(entry.enabled, true);
  assert.match(profile, /entry_id: builtin-desktop-my-work-authority/u);
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(JSON.stringify(value), /apiKey|localApiToken|my-work-session/iu);
  }
});

test('Loader activates the exact service and invalid candidates keep last-good', async () => {
  const bootstrap = loadBootstrap();
  const loader = new LoaderV2(rendererDefinitions(), 'desktop-renderer');
  const generation = await loader.stage(bootstrap);
  const service = generation.resolve(
    DESKTOP_MY_WORK_AUTHORITY_SERVICE_V2,
    { kind: 'project', tenant_id: 'tenant / one', project_id: 'project / one' },
    { version: DESKTOP_MY_WORK_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindOperation']);
  assert.equal('config' in service, false);
  assert.equal('client' in service, false);
  assert.throws(
    () =>
      applyDesktopMyWorkAuthorityV2(
        { provide: () => assert.fail('invalid config must not provide') },
        { strategy: 'legacy-client' },
      ),
    (error) =>
      error instanceof RuntimeV2Error && error.code === 'desktop_my_work_authority_config_invalid',
  );

  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-my-work-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_MY_WORK_AUTHORITY_SERVICE_V2,
        { kind: 'project', tenant_id: 'tenant / one', project_id: 'project / one' },
        { version: DESKTOP_MY_WORK_AUTHORITY_VERSION_V2 },
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service',
  );

  const manager = new GenerationManagerV2();
  await manager.publish(generation);
  const wrongDefinitionLoader = new LoaderV2(
    rendererDefinitions().map((definition) =>
      definition.moduleRef === DESKTOP_MY_WORK_AUTHORITY_MODULE_REF_V2
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

test('local and vault-bound cloud transports preserve exact authority semantics', async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const originalLocalStorage = globalThis.localStorage;
  const fetchCalls = [];
  const cloudCommands = [];
  globalThis.localStorage = memoryStorage();
  globalThis.fetch = async (input, init) => {
    fetchCalls.push({ input: String(input), init });
    return json({ project_id: 'project / one', items: [], total: 0 });
  };
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          cloudCommands.push({ command, args });
          return {
            status: 200,
            body: { project_id: 'project / one', items: [], total: 0 },
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
      DESKTOP_MY_WORK_AUTHORITY_SERVICE_V2,
      { kind: 'project', tenant_id: 'tenant / one', project_id: 'project / one' },
      { version: DESKTOP_MY_WORK_AUTHORITY_VERSION_V2 },
    );
    const controller = new AbortController();
    const localConfig = runtimeConfig();
    const local = service.bindOperation({ config: localConfig, principalId: null });
    localConfig.apiBaseUrl = 'http://127.0.0.1:46999';
    localConfig.projectId = 'mutated-project';
    const cloud = service.bindOperation({
      config: runtimeConfig({
        apiBaseUrl: 'https://cloud.example.test',
        apiKey: '',
        localApiToken: '',
        mode: 'cloud',
      }),
      principalId: 'user / one',
    });

    assert.deepEqual(await local.listMyWork(controller.signal), {
      project_id: 'project / one',
      items: [],
      total: 0,
    });
    assert.deepEqual(await cloud.listMyWork(controller.signal), {
      project_id: 'project / one',
      items: [],
      total: 0,
    });
    assert.equal(Object.isFrozen(local), true);
    assert.deepEqual(Object.keys(local), ['listMyWork']);
    assert.equal(fetchCalls.length, 1);
    const localCall = fetchCalls[0];
    const localUrl = new URL(localCall.input);
    const localHeaders = new Headers(localCall.init.headers);
    assert.equal(localUrl.origin, 'http://127.0.0.1:46701');
    assert.equal(localUrl.pathname, '/api/v1/projects/project%20%2F%20one/my-work');
    assert.equal(localCall.init.signal, controller.signal);
    assert.equal(localHeaders.get('Authorization'), 'Bearer my-work-session');
    assert.equal(localHeaders.get('X-Agistack-Launch'), 'my-work-launch');
    assert.equal(cloudCommands.length, 1);
    assert.equal(cloudCommands[0].command, 'cloud_request');
    assert.equal(
      cloudCommands[0].args.request.path,
      '/api/v1/projects/project%20%2F%20one/my-work',
    );
    assert.equal(JSON.stringify(cloudCommands).includes('Bearer'), false);
    await generation.dispose();
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
    if (originalLocalStorage === undefined) delete globalThis.localStorage;
    else globalThis.localStorage = originalLocalStorage;
  }
});

test('operation freezes identity and principal before one exact project lease', async () => {
  const lifecycle = [];
  const boundInputs = [];
  const signals = [];
  const service = Object.freeze({
    bindOperation(input) {
      boundInputs.push(input);
      return Object.freeze({
        async listMyWork(signal) {
          signals.push(signal);
          lifecycle.push('list');
          return { project_id: input.config.projectId, items: [], total: 0 };
        },
      });
    },
  });
  const actions = acceptedActions(service, 'sha256:generation-1', lifecycle);
  const operations = createDesktopMyWorkOperationsV2(() => actions);
  const controller = new AbortController();
  const config = runtimeConfig({ mode: 'cloud' });
  const pending = operations.listMyWork({
    config,
    principalId: 'user / one',
    signal: controller.signal,
  });
  config.tenantId = 'mutated-tenant';
  config.projectId = 'mutated-project';

  const response = await pending;

  assert.equal(response.project_id, 'project / one');
  assert.equal(Object.isFrozen(operations), true);
  assert.equal(Object.isFrozen(boundInputs[0].config), true);
  assert.equal(boundInputs[0].principalId, 'user / one');
  assert.deepEqual(signals, [controller.signal]);
  assert.deepEqual(lifecycle.find((event) => event.type === 'acquire').request, {
    service: DESKTOP_MY_WORK_AUTHORITY_SERVICE_V2,
    version: DESKTOP_MY_WORK_AUTHORITY_VERSION_V2,
    scope: {
      kind: 'project',
      tenant_id: 'tenant / one',
      project_id: 'project / one',
    },
  });
  assert.equal(lifecycle.filter((event) => event.type === 'release').length, 1);
});

test('invalid input and cross-project responses fail closed', async () => {
  let acquisitions = 0;
  const operations = createDesktopMyWorkOperationsV2(() => ({
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      throw new Error('must_not_acquire');
    },
  }));
  for (const input of [
    { config: runtimeConfig({ tenantId: '' }) },
    { config: runtimeConfig({ projectId: ' project-1' }) },
    { config: runtimeConfig({ mode: 'cloud' }), principalId: null },
    { config: runtimeConfig(), signal: {} },
  ]) {
    assert.throws(
      () => operations.listMyWork(input),
      (error) => error instanceof RuntimeV2Error && error.code === 'desktop_my_work_input_invalid',
    );
  }
  assert.equal(acquisitions, 0);

  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => json({ project_id: 'project-other', items: [], total: 0 });
  try {
    const context = {
      provided: null,
      provide(_key, service) {
        this.provided = service;
      },
    };
    applyDesktopMyWorkAuthorityV2(context, { strategy: 'desktop-api-client' });
    const authority = context.provided.bindOperation({
      config: runtimeConfig(),
      principalId: null,
    });
    await assert.rejects(
      authority.listMyWork(),
      (error) =>
        error instanceof RuntimeV2Error && error.code === 'desktop_my_work_response_scope_mismatch',
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('missing or wrong service fails closed and release preserves the primary error', async () => {
  let currentActions = null;
  const operations = createDesktopMyWorkOperationsV2(() => currentActions);
  assert.throws(
    () => operations.listMyWork({ config: runtimeConfig() }),
    (error) =>
      error instanceof DesktopMyWorkAuthorityUnavailableErrorV2 &&
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
    operations.listMyWork({ config: runtimeConfig() }),
    (error) =>
      error instanceof DesktopMyWorkAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_service_resolve_failed' &&
      error.runtimeCode === 'missing_service',
  );

  let wrongReleaseCount = 0;
  currentActions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:wrong-service',
      useService(operation) {
        return operation(Object.freeze({ bindOperation: null }));
      },
      async release() {
        wrongReleaseCount += 1;
      },
    }),
  };
  await assert.rejects(
    operations.listMyWork({ config: runtimeConfig() }),
    (error) => error instanceof RuntimeV2Error && error.code === 'desktop_my_work_service_invalid',
  );
  assert.equal(wrongReleaseCount, 1);

  const primary = new Error('my_work_primary_failure');
  let escapedAuthority = null;
  let releaseCount = 0;
  const releaseFailingActions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:accepted',
      useService(operation) {
        return operation({
          bindOperation(input) {
            return Object.freeze({
              async listMyWork() {
                return { project_id: input.config.projectId, items: [], total: 0 };
              },
            });
          },
        });
      },
      async release() {
        releaseCount += 1;
        throw new Error('my_work_release_failure');
      },
    }),
  };
  await assert.rejects(
    withDesktopMyWorkAuthorityOperationV2(
      releaseFailingActions,
      { config: runtimeConfig() },
      (authority) => {
        escapedAuthority = authority;
        throw primary;
      },
    ),
    (error) => error === primary,
  );
  assert.throws(
    () => escapedAuthority.listMyWork(),
    (error) =>
      error instanceof RuntimeV2Error && error.code === 'desktop_my_work_operation_released',
  );
  assert.equal(releaseCount, 1);
  await assert.rejects(
    withDesktopMyWorkAuthorityOperationV2(
      releaseFailingActions,
      { config: runtimeConfig() },
      (authority) => authority.listMyWork(),
    ),
    /my_work_release_failure/u,
  );
  assert.equal(releaseCount, 2);
});

test('in-flight read stays on its old generation and the next read uses the new one', async () => {
  const lifecycle = [];
  let resolveOld;
  const oldPending = new Promise((resolve) => {
    resolveOld = resolve;
  });
  const serviceFor = (label) =>
    Object.freeze({
      bindOperation(input) {
        return Object.freeze({
          async listMyWork() {
            lifecycle.push('list:' + label);
            if (label === 'old') await oldPending;
            return { project_id: input.config.projectId, items: [], total: label };
          },
        });
      },
    });
  let currentActions = acceptedActions(serviceFor('old'), 'sha256:old', lifecycle);
  const operations = createDesktopMyWorkOperationsV2(() => currentActions);
  const oldRead = operations.listMyWork({ config: runtimeConfig() });
  await Promise.resolve();
  currentActions = acceptedActions(serviceFor('next'), 'sha256:next', lifecycle);
  const nextRead = await operations.listMyWork({ config: runtimeConfig() });
  resolveOld();
  const oldResult = await oldRead;

  assert.equal(oldResult.total, 'old');
  assert.equal(nextRead.total, 'next');
  assert.deepEqual(
    lifecycle.filter((event) => typeof event === 'string'),
    ['list:old', 'list:next'],
  );
  assert.deepEqual(
    lifecycle.filter((event) => event.type === 'release').map((event) => event.digest),
    ['sha256:next', 'sha256:old'],
  );
});
