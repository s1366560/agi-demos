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
  DESKTOP_WORKSPACE_AUTONOMY_ATTENTION_AUTHORITY_MODULE_REF_V2,
  DESKTOP_WORKSPACE_AUTONOMY_ATTENTION_AUTHORITY_SERVICE_V2,
  DESKTOP_WORKSPACE_AUTONOMY_ATTENTION_AUTHORITY_VERSION_V2,
  applyDesktopWorkspaceAutonomyAttentionAuthorityV2,
  desktopWorkspaceAutonomyAttentionAuthorityDefinitionV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopWorkspaceAutonomyAttentionAuthorityModuleV2.js');
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
  'desktopWorkspaceCatalogAuthorityModuleV2',
  'desktopWorkspaceLifecycleAuthorityModuleV2',
  'desktopWorkspaceRosterAuthorityModuleV2',
  'desktopWorkspaceContextAuthorityModuleV2',
  'desktopWorkspaceConversationCatalogAuthorityModuleV2',
  'desktopWorkspaceExecutionSnapshotAuthorityModuleV2',
  'desktopWorkspaceMemberMutationAuthorityModuleV2',
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
    desktopWorkspaceAutonomyAttentionAuthorityDefinitionV2,
  ];
}

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46951',
    apiKey: 'workspace-attention-session',
    localApiToken: 'workspace-attention-launch',
    mode: 'local',
    tenantId: 'tenant / one',
    projectId: 'project / one',
    workspaceId: 'workspace / one',
    workspaceRoot: '/workspace/project-one',
    ...overrides,
  };
}

function attention() {
  return {
    attention_id: 'attention / one',
    root_task_id: null,
    source_kind: 'judge_block',
    source_id: 'judge / one',
    reason: 'Operator decision required',
    status: 'open',
    created_at_ms: 17,
  };
}

function responseForPath(path) {
  if (path.endsWith('/collaboration/authority')) {
    return {
      contract_version: '2.0.0',
      tenant_id: 'tenant / one',
      project_id: 'project / one',
      workspace_id: 'workspace / one',
      revision: 7,
      cursor: 'authority-cursor-7',
    };
  }
  if (path.endsWith('/retry')) {
    return { attention_id: 'attention / one', status: 'retry_queued' };
  }
  if (path.endsWith('/resolve')) {
    return {
      attention_id: 'attention / one',
      status: 'resolved',
      committed_revision: 8,
      replayed: false,
    };
  }
  return [attention()];
}

test('generated contract declares one credential-free root autonomy-attention Provider', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const bootstrap = loadBootstrap();
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_WORKSPACE_AUTONOMY_ATTENTION_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_WORKSPACE_AUTONOMY_ATTENTION_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-workspace-autonomy-attention-authority',
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_WORKSPACE_AUTONOMY_ATTENTION_AUTHORITY_SERVICE_V2,
        version: DESKTOP_WORKSPACE_AUTONOMY_ATTENTION_AUTHORITY_VERSION_V2,
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
    desktopWorkspaceAutonomyAttentionAuthorityDefinitionV2.contractDigest,
  );
  assert.equal(catalog.entrypoint, 'applyDesktopWorkspaceAutonomyAttentionAuthorityV2');
  assert.equal(
    catalog.artifact_source,
    'repo+typescript://agi-stack/apps/desktop/src/plugins/' +
      'desktopWorkspaceAutonomyAttentionAuthorityModuleV2.ts',
  );
  assert.equal(entry.module_ref, DESKTOP_WORKSPACE_AUTONOMY_ATTENTION_AUTHORITY_MODULE_REF_V2);
  assert.equal(entry.parent_entry_id, 'builtin-desktop-renderer-host');
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-client' });
  assert.deepEqual(entry.inject, {});
  assert.equal(entry.enabled, true);
  assert.match(profile, /entry_id: builtin-desktop-workspace-autonomy-attention-authority/u);
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(
      JSON.stringify(value),
      /apiKey|localApiToken|Authorization|workspace-attention-session/iu,
    );
  }
});

test('Loader activation and Profile disable remove autonomy attention without fallback', async () => {
  const bootstrap = loadBootstrap();
  const loader = new LoaderV2(rendererDefinitions(), 'desktop-renderer');
  const generation = await loader.stage(bootstrap);
  const service = generation.resolve(
    DESKTOP_WORKSPACE_AUTONOMY_ATTENTION_AUTHORITY_SERVICE_V2,
    { kind: 'project', tenant_id: 'tenant / one', project_id: 'project / one' },
    { version: DESKTOP_WORKSPACE_AUTONOMY_ATTENTION_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindOperation']);
  assert.equal('config' in service, false);
  assert.equal('client' in service, false);
  assert.throws(
    () =>
      applyDesktopWorkspaceAutonomyAttentionAuthorityV2(
        { provide: () => assert.fail('invalid config must not provide') },
        { strategy: 'legacy-client' },
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_autonomy_attention_authority_config_invalid',
  );

  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-workspace-autonomy-attention-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_WORKSPACE_AUTONOMY_ATTENTION_AUTHORITY_SERVICE_V2,
        { kind: 'project', tenant_id: 'tenant / one', project_id: 'project / one' },
        { version: DESKTOP_WORKSPACE_AUTONOMY_ATTENTION_AUTHORITY_VERSION_V2 },
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service',
  );

  const manager = new GenerationManagerV2();
  await manager.publish(generation);
  const wrongDefinitionLoader = new LoaderV2(
    rendererDefinitions().map((candidate) =>
      candidate.moduleRef === DESKTOP_WORKSPACE_AUTONOMY_ATTENTION_AUTHORITY_MODULE_REF_V2
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

test('Local and vault-bound Cloud transports retain exact scope, signals and mutation headers', async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const fetchCalls = [];
  const cloudCommands = [];
  globalThis.fetch = async (input, init) => {
    const path = new URL(String(input)).pathname;
    fetchCalls.push({ input: String(input), init });
    return new Response(JSON.stringify(responseForPath(path)), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          cloudCommands.push({ command, args });
          return { status: 200, body: responseForPath(args.request.path) };
        },
      },
    },
  };

  try {
    const generation = await new LoaderV2(rendererDefinitions(), 'desktop-renderer').stage(
      loadBootstrap(),
    );
    const service = generation.resolve(
      DESKTOP_WORKSPACE_AUTONOMY_ATTENTION_AUTHORITY_SERVICE_V2,
      { kind: 'project', tenant_id: 'tenant / one', project_id: 'project / one' },
      { version: DESKTOP_WORKSPACE_AUTONOMY_ATTENTION_AUTHORITY_VERSION_V2 },
    );
    const controller = new AbortController();
    const localConfig = runtimeConfig();
    const local = service.bindOperation(localConfig, 'workspace / one');
    localConfig.apiBaseUrl = 'http://127.0.0.1:46999';
    const cloud = service.bindOperation(
      runtimeConfig({
        apiBaseUrl: 'https://cloud.example.test',
        apiKey: '',
        localApiToken: '',
        mode: 'cloud',
      }),
      'workspace / one',
    );

    for (const authority of [local, cloud]) {
      const listed = await authority.listWorkspaceAutonomyAttentions(controller.signal);
      const revision = await authority.getWorkspaceAuthorityRevision(controller.signal);
      const retried = await authority.retryWorkspaceAutonomyAttention(
        'attention / one',
        controller.signal,
      );
      const resolved = await authority.resolveWorkspaceAutonomyAttention(
        'attention / one',
        revision,
        'desktop-attention-idempotency-1',
        controller.signal,
      );
      assert.equal(Object.isFrozen(authority), true);
      assert.equal(Object.isFrozen(listed), true);
      assert.equal(Object.isFrozen(listed[0]), true);
      assert.equal(retried.status, 'retry_queued');
      assert.equal(resolved.status, 'resolved');
      assert.equal(Object.isFrozen(retried), true);
      assert.equal(Object.isFrozen(resolved), true);
    }

    assert.equal(fetchCalls.length, 4);
    assert.equal(new URL(fetchCalls[0].input).origin, 'http://127.0.0.1:46951');
    assert.equal(
      fetchCalls.every(({ init }) => init.signal === controller.signal),
      true,
    );
    assert.equal(cloudCommands.length, 4);
    assert.equal(
      cloudCommands.every(({ command }) => command === 'cloud_request'),
      true,
    );
    assert.equal(JSON.stringify(cloudCommands).includes('Bearer'), false);
    assert.equal(JSON.stringify(cloudCommands).includes('workspace-attention-session'), false);
    const localResolveHeaders = new Headers(fetchCalls[3].init.headers);
    assert.equal(localResolveHeaders.get('If-Match'), '7');
    assert.equal(localResolveHeaders.get('X-Expected-Revision'), '7');
    assert.equal(localResolveHeaders.get('Idempotency-Key'), 'desktop-attention-idempotency-1');
    assert.deepEqual(cloudCommands[3].args.request.mutation, {
      expected_revision: 7,
      idempotency_key: 'desktop-attention-idempotency-1',
    });
    await generation.dispose();
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});
