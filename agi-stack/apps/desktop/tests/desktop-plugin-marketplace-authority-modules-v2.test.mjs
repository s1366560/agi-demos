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
  DESKTOP_PLUGIN_MARKETPLACE_CATALOG_MODULE_REF_V2,
  DESKTOP_PLUGIN_MARKETPLACE_CATALOG_SERVICE_V2,
  DESKTOP_PLUGIN_MARKETPLACE_CATALOG_VERSION_V2,
  DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_MODULE_REF_V2,
  DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_SERVICE_V2,
  DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_VERSION_V2,
  DesktopPluginMarketplaceAuthorityUnavailableErrorV2,
  createDesktopPluginMarketplaceOperationsV2,
  desktopPluginMarketplaceCatalogDefinitionV2,
  desktopPluginMarketplaceManagementDefinitionV2,
  withDesktopPluginMarketplaceCatalogOperationV2,
} = require(
  `${COMPILED_ROOT}/src/plugins/desktopPluginMarketplaceAuthorityModulesV2.js`,
);
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
const { desktopWorkspaceContextAuthorityDefinitionV2 } = require(
  `${COMPILED_ROOT}/src/plugins/desktopWorkspaceContextAuthorityModuleV2.js`,
);
const { desktopSessionTimelineAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopSessionTimelineAuthorityModuleV2.js',
);
const { desktopWorkspaceConversationCatalogAuthorityDefinitionV2 } = require(
  COMPILED_ROOT +
    '/src/plugins/desktopWorkspaceConversationCatalogAuthorityModuleV2.js',
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
    require(COMPILED_ROOT + '/src/plugins/desktopProjectGraphAuthorityModuleV2.js')
      .desktopProjectGraphAuthorityDefinitionV2,
    desktopArtifactContentAuthorityDefinitionV2,
    desktopAutomationAuthorityDefinitionV2,
    desktopNewTaskFlowAuthorityDefinitionV2,
    desktopNewThreadCreationAuthorityDefinitionV2,
    desktopProjectSearchAuthorityDefinitionV2,
    desktopRuntimePoolAuthorityDefinitionV2,
    desktopRuntimeClustersAuthorityDefinitionV2,
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

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46201',
    apiKey: 'plugin-marketplace-session',
    localApiToken: 'plugin-marketplace-launch',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    ...overrides,
  };
}

function catalogPayload() {
  return {
    items: [
      {
        plugin_id: 'github',
        version: '2.4.1',
        publisher: 'MemStack Labs',
        artifact_digest: 'sha256:github-artifact',
        artifact_registry: 'registry.test.invalid',
        artifact_repository: 'plugins/github',
        oci_manifest_digest: 'sha256:github-manifest',
        install_status: 'installed',
        manifest: { targets: ['python', 'desktop-renderer'] },
        signature: { algorithm: 'Ed25519' },
        provenance: { builder_id: 'test-builder-v2' },
        security_scan_status: 'passed',
        revoked: false,
        revocation_reason: null,
      },
    ],
  };
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

test('generated manifest, catalog and Profile expose two independent root services', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const bootstrap = loadBootstrap();
  const expected = [
    {
      moduleRef: DESKTOP_PLUGIN_MARKETPLACE_CATALOG_MODULE_REF_V2,
      service: DESKTOP_PLUGIN_MARKETPLACE_CATALOG_SERVICE_V2,
      version: DESKTOP_PLUGIN_MARKETPLACE_CATALOG_VERSION_V2,
      entryId: 'builtin-desktop-plugin-marketplace-catalog-authority',
      entrypoint: 'applyDesktopPluginMarketplaceCatalogAuthorityV2',
    },
    {
      moduleRef: DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_MODULE_REF_V2,
      service: DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_SERVICE_V2,
      version: DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_VERSION_V2,
      entryId: 'builtin-desktop-plugin-marketplace-management-authority',
      entrypoint: 'applyDesktopPluginMarketplaceManagementAuthorityV2',
    },
  ];

  assert.deepEqual(manifest.permissions, []);
  assert.deepEqual(manifest.quotas, {});

  for (const contract of expected) {
    const module = manifest.modules.find(
      ({ module_ref: moduleRef }) => moduleRef === contract.moduleRef,
    );
    const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
      ({ module_ref: moduleRef }) => moduleRef === contract.moduleRef,
    );
    const entry = bootstrap.entries.find(
      ({ entry_id: entryId }) => entryId === contract.entryId,
    );

    assert.ok(module);
    assert.ok(catalog);
    assert.ok(entry);
    assert.deepEqual(module.targets, ['desktop-renderer']);
    assert.deepEqual(module.contract.services, {
      provides: [{ service: contract.service, version: contract.version }],
      requires: [],
    });
    assert.deepEqual(module.contract.events, { emits: [], handles: [] });
    assert.equal(module.contract.config_schema.additionalProperties, false);
    assert.deepEqual(module.contract.config_schema.required, ['strategy']);
    assert.equal(module.contract.config_schema.properties.strategy.const, 'desktop-api-client');
    assert.equal(module.contract_digest, catalog.contract_digest);
    assert.equal(catalog.entrypoint, contract.entrypoint);
    assert.equal(
      catalog.artifact_source,
      'repo+typescript://agi-stack/apps/desktop/src/plugins/' +
        'desktopPluginMarketplaceAuthorityModulesV2.ts',
    );
    assert.equal(entry.module_ref, contract.moduleRef);
    assert.equal(entry.parent_entry_id, 'builtin-desktop-renderer-host');
    assert.deepEqual(entry.scope, { kind: 'root' });
    assert.deepEqual(entry.isolate, {});
    assert.deepEqual(entry.config, { strategy: 'desktop-api-client' });
    assert.deepEqual(entry.permissions, []);
    assert.deepEqual(entry.quotas, {});
    assert.equal(entry.enabled, true);
    assert.match(profile, new RegExp(`entry_id: ${contract.entryId}`, 'u'));
    assert.doesNotMatch(JSON.stringify(module), /apiKey|localApiToken|Authorization/u);
    assert.doesNotMatch(JSON.stringify(entry), /apiKey|localApiToken|Authorization/u);
  }

  assert.equal(
    desktopPluginMarketplaceCatalogDefinitionV2.contractDigest,
    PLUGIN_MODULE_CATALOG_V2.modules.find(
      ({ module_ref: moduleRef }) =>
        moduleRef === DESKTOP_PLUGIN_MARKETPLACE_CATALOG_MODULE_REF_V2,
    ).contract_digest,
  );
  assert.equal(
    desktopPluginMarketplaceManagementDefinitionV2.contractDigest,
    PLUGIN_MODULE_CATALOG_V2.modules.find(
      ({ module_ref: moduleRef }) =>
        moduleRef === DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_MODULE_REF_V2,
    ).contract_digest,
  );
});

test('Loader activates frozen services and each Profile entry disables independently', async () => {
  const bootstrap = loadBootstrap();
  const loader = new LoaderV2(rendererDefinitions(), 'desktop-renderer');
  const generation = await loader.stage(bootstrap);
  const catalogService = generation.resolve(
    DESKTOP_PLUGIN_MARKETPLACE_CATALOG_SERVICE_V2,
    { kind: 'root' },
    { version: DESKTOP_PLUGIN_MARKETPLACE_CATALOG_VERSION_V2 },
  );
  const managementService = generation.resolve(
    DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_SERVICE_V2,
    { kind: 'root' },
    { version: DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_VERSION_V2 },
  );

  for (const service of [catalogService, managementService]) {
    assert.equal(Object.isFrozen(service), true);
    assert.deepEqual(Object.keys(service), ['bindOperation']);
    assert.equal('client' in service, false);
    assert.equal('request' in service, false);
    assert.equal('config' in service, false);
  }

  for (const [entryId, service, version] of [
    [
      'builtin-desktop-plugin-marketplace-catalog-authority',
      DESKTOP_PLUGIN_MARKETPLACE_CATALOG_SERVICE_V2,
      DESKTOP_PLUGIN_MARKETPLACE_CATALOG_VERSION_V2,
    ],
    [
      'builtin-desktop-plugin-marketplace-management-authority',
      DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_SERVICE_V2,
      DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_VERSION_V2,
    ],
  ]) {
    const disabled = structuredClone(bootstrap);
    disabled.entries.find(({ entry_id: candidate }) => candidate === entryId).enabled = false;
    const disabledGeneration = await loader.stage(disabled);
    assert.throws(
      () => disabledGeneration.resolve(service, { kind: 'root' }, { version }),
      (error) => error instanceof RuntimeV2Error && error.code === 'missing_service',
    );
    await disabledGeneration.dispose();
  }

  const missingDefinitionLoader = new LoaderV2(
    [
      ...createDesktopRendererDefinitionsV2(),
      desktopWorkspaceContextAuthorityDefinitionV2,
      desktopTerminalLifecycleAuthorityDefinitionV2,
      desktopTenantCatalogAuthorityDefinitionV2,
      desktopPluginMarketplaceCatalogDefinitionV2,
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
      desktopWorkspaceContextAuthorityDefinitionV2,
      desktopTerminalLifecycleAuthorityDefinitionV2,
      desktopTenantCatalogAuthorityDefinitionV2,
      desktopPluginMarketplaceCatalogDefinitionV2,
      {
        ...desktopPluginMarketplaceManagementDefinitionV2,
        contractDigest: `sha256:${'0'.repeat(64)}`,
      },
    ],
    'desktop-renderer',
  );
  const manager = new GenerationManagerV2();
  await manager.publish(generation);
  await assert.rejects(
    wrongDefinitionLoader.stage(bootstrap),
    (error) => error instanceof RuntimeV2Error && error.code === 'contract_digest_mismatch',
  );
  assert.equal(manager.current, generation);
  await manager.close();
  assert.equal(generation.disposed, true);
});

test('bound authorities freeze config and forward AbortSignal through exact V2 endpoints', async () => {
  const generation = await new LoaderV2(
    rendererDefinitions(),
    'desktop-renderer',
  ).stage(loadBootstrap());
  const catalogService = generation.resolve(
    DESKTOP_PLUGIN_MARKETPLACE_CATALOG_SERVICE_V2,
    { kind: 'root' },
    { version: DESKTOP_PLUGIN_MARKETPLACE_CATALOG_VERSION_V2 },
  );
  const managementService = generation.resolve(
    DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_SERVICE_V2,
    { kind: 'root' },
    { version: DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_VERSION_V2 },
  );
  const config = runtimeConfig();
  const catalog = catalogService.bindOperation(config);
  const management = managementService.bindOperation(config);
  config.apiBaseUrl = 'http://127.0.0.1:46999';
  config.apiKey = 'mutated-session';
  config.localApiToken = 'mutated-launch';
  config.tenantId = 'mutated-tenant';
  const originalFetch = globalThis.fetch;
  const calls = [];
  const controller = new AbortController();
  globalThis.fetch = async (input, init) => {
    calls.push({ url: new URL(String(input)), init });
    if (String(input).includes('/uninstall')) {
      return json({
        plugin_id: 'github',
        version: '2.4.1',
        status: 'uninstalled',
        desired_removed: true,
        revoked_permissions: 0,
      });
    }
    return json(catalogPayload());
  };

  try {
    const plugins = await catalog.listMarketplacePlugins(controller.signal);
    const outcome = await management.uninstallMarketplacePlugin(
      'github',
      '2.4.1',
      controller.signal,
    );

    assert.equal(Object.isFrozen(catalog), true);
    assert.equal(Object.isFrozen(management), true);
    assert.deepEqual(Object.keys(catalog), ['listMarketplacePlugins']);
    assert.deepEqual(Object.keys(management), ['uninstallMarketplacePlugin']);
    assert.equal(plugins[0].id, 'github@2.4.1');
    assert.equal(outcome.desired_removed, true);
    assert.equal(calls.length, 2);
    for (const call of calls) {
      assert.equal(call.url.origin, 'http://127.0.0.1:46201');
      assert.equal(call.init.signal, controller.signal);
      const headers = new Headers(call.init.headers);
      assert.equal(headers.get('Authorization'), 'Bearer plugin-marketplace-session');
      assert.equal(headers.get('X-Agistack-Launch'), 'plugin-marketplace-launch');
    }
    assert.equal(
      calls[0].url.pathname,
      '/api/v1/plugin-marketplace/packages',
    );
    assert.equal(calls[0].url.searchParams.get('include_revoked'), 'true');
    assert.equal(
      calls[1].url.pathname,
      '/api/v1/plugin-marketplace/packages/github/uninstall',
    );
    assert.deepEqual(JSON.parse(calls[1].init.body), {
      tenant_id: 'tenant-1',
      version: '2.4.1',
    });
    assert.doesNotMatch(
      JSON.stringify([catalogService, managementService, catalog, management]),
      /plugin-marketplace-session|plugin-marketplace-launch/u,
    );
  } finally {
    globalThis.fetch = originalFetch;
    await generation.dispose();
  }
});

test('operation runner snapshots actions, leases exact services and releases exactly once', async () => {
  const requestConfig = runtimeConfig();
  const requests = [];
  const boundConfigs = [];
  const signals = [];
  const lifecycle = [];
  let releaseCount = 0;
  const actions = {
    acquireServiceOperationLease: async (request) => {
      requests.push(request);
      const leaseIndex = requests.length;
      const authority =
        request.service === DESKTOP_PLUGIN_MARKETPLACE_CATALOG_SERVICE_V2
          ? {
              listMarketplacePlugins: async (signal) => {
                signals.push(signal);
                lifecycle.push(`list:${leaseIndex}`);
                return [];
              },
            }
          : {
              uninstallMarketplacePlugin: async (_pluginId, _version, signal) => {
                signals.push(signal);
                lifecycle.push(`uninstall:${leaseIndex}`);
                return {
                  plugin_id: 'github',
                  version: '2.4.1',
                  status: 'uninstalled',
                  desired_removed: true,
                  revoked_permissions: 0,
                };
              },
            };
      return {
        status: 'accepted',
        digest: 'sha256:accepted',
        useService(operation) {
          return operation({
            bindOperation(config) {
              boundConfigs.push(config);
              return Object.freeze(authority);
            },
          });
        },
        async release() {
          releaseCount += 1;
          lifecycle.push(`release:${leaseIndex}`);
        },
      };
    },
  };
  let currentActions = actions;
  const operations = createDesktopPluginMarketplaceOperationsV2(
    () => currentActions,
  );
  const controller = new AbortController();
  const listPending = operations.listMarketplacePlugins(
    requestConfig,
    controller.signal,
  );
  requestConfig.apiBaseUrl = 'http://127.0.0.1:46999';
  requestConfig.apiKey = 'mutated-session';
  currentActions = null;
  await listPending;
  assert.throws(
    () => operations.listMarketplacePlugins(requestConfig, controller.signal),
    (error) => {
      assert.equal(error instanceof DesktopPluginMarketplaceAuthorityUnavailableErrorV2, true);
      assert.equal(error.reasonCode, 'desktop_renderer_generation_actions_unavailable');
      assert.equal(error.service, 'catalog');
      return true;
    },
  );
  currentActions = actions;
  const projectedCount = await operations.projectMarketplacePlugins(
    runtimeConfig(),
    controller.signal,
    async (plugins) => {
      lifecycle.push('project:start');
      await Promise.resolve();
      lifecycle.push('project:end');
      return plugins.length;
    },
  );
  await operations.uninstallMarketplacePlugin(
    runtimeConfig(),
    'github',
    '2.4.1',
    controller.signal,
  );

  assert.equal(Object.isFrozen(operations), true);
  assert.deepEqual(requests, [
    {
      service: DESKTOP_PLUGIN_MARKETPLACE_CATALOG_SERVICE_V2,
      version: DESKTOP_PLUGIN_MARKETPLACE_CATALOG_VERSION_V2,
      scope: { kind: 'root' },
    },
    {
      service: DESKTOP_PLUGIN_MARKETPLACE_CATALOG_SERVICE_V2,
      version: DESKTOP_PLUGIN_MARKETPLACE_CATALOG_VERSION_V2,
      scope: { kind: 'root' },
    },
    {
      service: DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_SERVICE_V2,
      version: DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_VERSION_V2,
      scope: { kind: 'root' },
    },
  ]);
  assert.equal(projectedCount, 0);
  assert.equal(boundConfigs[0].apiBaseUrl, 'http://127.0.0.1:46201');
  assert.equal(boundConfigs[0].apiKey, 'plugin-marketplace-session');
  assert.equal(Object.isFrozen(boundConfigs[0]), true);
  assert.equal(signals[0], controller.signal);
  assert.equal(signals[1], controller.signal);
  assert.equal(signals[2], controller.signal);
  assert.ok(lifecycle.indexOf('project:end') < lifecycle.indexOf('release:2'));
  assert.equal(releaseCount, 3);
});

test('operation helper revokes escaped authority and preserves primary failure over release', async () => {
  const primary = new Error('plugin_marketplace_primary_failure');
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
              async listMarketplacePlugins() {
                return [];
              },
            });
          },
        });
      },
      async release() {
        releaseCount += 1;
        throw new Error('plugin_marketplace_release_failure');
      },
    }),
  };

  await assert.rejects(
    withDesktopPluginMarketplaceCatalogOperationV2(
      actions,
      runtimeConfig(),
      (authority) => {
        escapedAuthority = authority;
        throw primary;
      },
    ),
    (error) => error === primary,
  );
  assert.throws(
    () => escapedAuthority.listMarketplacePlugins(new AbortController().signal),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_plugin_marketplace_catalog_operation_released',
  );
  assert.equal(releaseCount, 1);
});

test('production and QA wiring remove every direct Marketplace transport fallback', () => {
  const source = (relativePath) =>
    readFileSync(new URL(relativePath, REPOSITORY_ROOT), 'utf8');
  const hook = source('agi-stack/apps/desktop/src/plugins/useDesktopPluginGenerationV2.ts');
  const app = source('agi-stack/apps/desktop/src/App.tsx');
  const settings = source(
    'agi-stack/apps/desktop/src/features/settings/SettingsWindow.tsx',
  );
  const management = source(
    'agi-stack/apps/desktop/src/features/settings/usePluginManagement.ts',
  );
  const routeClient = source(
    'agi-stack/apps/desktop/src/features/settings-routes/pluginsRouteClient.ts',
  );
  const routeRuntime = source(
    'agi-stack/apps/desktop/src/features/settings-routes/settingsRouteRuntime.ts',
  );
  const routeRegistry = source(
    'agi-stack/apps/desktop/src/features/navigation/appRouteRegistry.ts',
  );
  const workbench = source(
    'agi-stack/apps/desktop/src/features/runtime/workbenchCapabilityClient.ts',
  );
  const workbenchProvider = source(
    'agi-stack/apps/desktop/src/features/runtime/desktopWorkbenchCapabilityClientProviderV2.ts',
  );
  const composerProvider = source(
    'agi-stack/apps/desktop/src/features/task/desktopNewThreadComposerCatalogClientProviderV2.ts',
  );
  const noProjectQa = source(
    'agi-stack/apps/desktop/src/qa/NoProjectEntryQa.tsx',
  );
  const providerQa = source(
    'agi-stack/apps/desktop/src/qa/ProviderSettingsQa.tsx',
  );

  assert.match(hook, /desktopPluginMarketplaceCatalogDefinitionV2/u);
  assert.match(hook, /desktopPluginMarketplaceManagementDefinitionV2/u);
  assert.match(app, /createDesktopPluginMarketplaceOperationsV2/u);
  assert.match(app, /useLayoutEffect/u);
  assert.match(app, /desktopPluginMarketplaceGenerationActionsRefV2/u);
  assert.match(app, /pluginMarketplaceOperationsV2:\s*desktopPluginMarketplaceOperationsV2/u);
  assert.match(settings, /pluginMarketplaceOperationsV2/u);
  assert.match(management, /pluginMarketplaceOperationsV2/u);
  assert.match(routeClient, /pluginMarketplaceOperationsV2/u);
  assert.match(routeClient, /projectMarketplacePlugins/u);
  assert.match(routeRuntime, /createClient/u);
  assert.match(routeRegistry, /pluginMarketplaceOperationsV2/u);
  assert.match(workbenchProvider, /pluginMarketplaceOperationsV2/u);
  assert.match(composerProvider, /pluginMarketplaceOperationsV2/u);
  assert.match(noProjectQa, /noProjectPluginMarketplaceOperationsV2/u);
  assert.match(providerQa, /qaPluginMarketplaceOperationsV2/u);

  for (const content of [settings, management, routeClient]) {
    assert.doesNotMatch(content, /new DesktopApiClient|import \{ DesktopApiClient \}/u);
  }
  assert.doesNotMatch(routeClient, /=\s*new DesktopApiClient/u);
  assert.doesNotMatch(workbench, /createPluginsRouteClient\(config\)(?:,|\))/u);
  assert.doesNotMatch(
    composerProvider,
    /listMarketplacePlugins:[\s\S]{0,180}authority\.listMarketplacePlugins/u,
  );
  assert.doesNotMatch(noProjectQa, /new DesktopApiClient/u);
  assert.doesNotMatch(providerQa, /new DesktopApiClient/u);
});
