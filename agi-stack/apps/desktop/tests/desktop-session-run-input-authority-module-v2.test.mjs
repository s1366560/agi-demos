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
  DESKTOP_SESSION_RUN_INPUT_AUTHORITY_MODULE_REF_V2,
  DESKTOP_SESSION_RUN_INPUT_AUTHORITY_SERVICE_V2,
  DESKTOP_SESSION_RUN_INPUT_AUTHORITY_VERSION_V2,
  applyDesktopSessionRunInputAuthorityV2,
  desktopSessionRunInputAuthorityDefinitionV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopSessionRunInputAuthorityModuleV2.js');
const marketplace = require(
  COMPILED_ROOT + '/src/plugins/desktopPluginMarketplaceAuthorityModulesV2.js',
);
const roster = require(COMPILED_ROOT + '/src/plugins/desktopWorkspaceRosterAuthorityModuleV2.js');
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

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
  'desktopWorkspaceCatalogAuthorityModuleV2',
  'desktopWorkspaceContextAuthorityModuleV2',
  'desktopWorkspaceConversationCatalogAuthorityModuleV2',
  'desktopWorkspaceExecutionSnapshotAuthorityModuleV2',
  'desktopWorkspaceLifecycleAuthorityModuleV2',
  'desktopWorkspaceMemberMutationAuthorityModuleV2',
  'desktopWorkspaceMessageCatalogAuthorityModuleV2',
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

function loadBootstrap() {
  const profile = JSON.parse(readFileSync(BOOTSTRAP_PATH, 'utf8'));
  // This focused Loader fixture does not exercise the coordinating snapshot module.
  profile.entries = profile.entries.filter(
    (entry) => entry.module_ref !== 'builtin://memstack/desktop/workbench-snapshot-authority',
  );
  return profile;
}

function rendererDefinitions() {
  return [
    ...createDesktopRendererDefinitionsV2(),
    require(COMPILED_ROOT + '/src/plugins/desktopProjectBlackboardAuthorityModuleV2.js')
      .desktopProjectBlackboardAuthorityDefinitionV2,
    ...authorityModules,
    marketplace.desktopPluginMarketplaceCatalogDefinitionV2,
    marketplace.desktopPluginMarketplaceManagementDefinitionV2,
    roster.desktopWorkspaceRosterAuthorityDefinitionV2,
    desktopSessionRunInputAuthorityDefinitionV2,
  ];
}

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46991',
    apiKey: 'run-input-session',
    localApiToken: 'run-input-launch',
    mode: 'local',
    tenantId: 'tenant / one',
    projectId: 'project / one',
    workspaceId: 'workspace / one',
    workspaceRoot: '/workspace/project-one',
    ...overrides,
  };
}

function identity() {
  return Object.freeze({
    tenant_id: 'tenant / one',
    project_id: 'project / one',
    workspace_id: 'workspace / one',
    session_id: 'conversation / one',
  });
}

function receipt(overrides = {}) {
  return {
    id: 'input / one',
    conversation_id: 'conversation / one',
    run_id: 'run / one',
    expected_run_revision: 7,
    message_id: 'message-1',
    idempotency_key: 'run-input-key-1',
    delivery: 'queue_next',
    status: 'queued',
    sequence: 1,
    queue_position: 1,
    content: 'Review the focused change',
    references: [],
    context_items: [],
    applied_round: null,
    applied_at: null,
    created_at: '2026-09-02T00:00:00Z',
    updated_at: '2026-09-02T00:00:01Z',
    ...overrides,
  };
}

function createAck(overrides = {}) {
  return {
    accepted: true,
    created: true,
    action: 'send_message',
    conversation_id: 'conversation / one',
    message_id: 'message-1',
    delivery_mode: 'queue_next',
    run_id: 'run / one',
    run_revision: 7,
    queue_position: 1,
    input: receipt(),
    ...overrides,
  };
}

function listResponse(overrides = {}) {
  return {
    run_id: 'run / one',
    run_revision: 7,
    inputs: [receipt()],
    total_count: 1,
    ...overrides,
  };
}

function promoteResponse(overrides = {}) {
  return {
    accepted: true,
    created: true,
    action: 'start_plan_turn',
    input: receipt({
      status: 'promoted_to_plan',
      promotion_idempotency_key: 'promotion-key-1',
      promoted_at: '2026-09-02T00:00:02Z',
    }),
    conversation: {
      id: 'conversation / one',
      tenant_id: 'tenant / one',
      project_id: 'project / one',
      workspace_id: 'workspace / one',
      current_mode: 'plan',
    },
    source_run: {
      id: 'run / one',
      conversation_id: 'conversation / one',
      project_id: 'project / one',
      revision: 7,
    },
    ...overrides,
  };
}

function responseForRequest(path, method) {
  if (path.endsWith('/promote') || path.endsWith('/promote-to-plan')) {
    return promoteResponse();
  }
  return method === 'POST' ? createAck() : listResponse();
}

test('generated contract declares one credential-free root session run-input Provider', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const bootstrap = loadBootstrap();
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_SESSION_RUN_INPUT_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_SESSION_RUN_INPUT_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-session-run-input-authority',
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_SESSION_RUN_INPUT_AUTHORITY_SERVICE_V2,
        version: DESKTOP_SESSION_RUN_INPUT_AUTHORITY_VERSION_V2,
      },
    ],
    requires: [],
  });
  assert.deepEqual(module.contract.events, { emits: [], handles: [] });
  assert.equal(module.contract.config_schema.additionalProperties, false);
  assert.deepEqual(module.contract.config_schema.required, ['strategy']);
  assert.equal(module.contract.config_schema.properties.strategy.const, 'desktop-api-client');
  assert.equal(module.contract_digest, catalog.contract_digest);
  assert.equal(module.contract_digest, desktopSessionRunInputAuthorityDefinitionV2.contractDigest);
  assert.equal(catalog.entrypoint, 'applyDesktopSessionRunInputAuthorityV2');
  assert.equal(
    catalog.artifact_source,
    'repo+typescript://agi-stack/apps/desktop/src/plugins/' +
      'desktopSessionRunInputAuthorityModuleV2.ts',
  );
  assert.equal(entry.module_ref, DESKTOP_SESSION_RUN_INPUT_AUTHORITY_MODULE_REF_V2);
  assert.equal(entry.parent_entry_id, 'builtin-desktop-renderer-host');
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-client' });
  assert.deepEqual(entry.inject, {});
  assert.equal(entry.enabled, true);
  assert.match(profile, /entry_id: builtin-desktop-session-run-input-authority/u);
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(
      JSON.stringify(value),
      /apiKey|localApiToken|Authorization|run-input-session/iu,
    );
  }
});

test('Loader activation and Profile disable remove session run-input without fallback', async () => {
  const bootstrap = loadBootstrap();
  const loader = new LoaderV2(rendererDefinitions(), 'desktop-renderer');
  const generation = await loader.stage(bootstrap);
  const service = generation.resolve(
    DESKTOP_SESSION_RUN_INPUT_AUTHORITY_SERVICE_V2,
    {
      kind: 'session',
      tenant_id: 'tenant / one',
      project_id: 'project / one',
      session_id: 'conversation / one',
    },
    { version: DESKTOP_SESSION_RUN_INPUT_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindOperation']);
  assert.equal('config' in service, false);
  assert.equal('client' in service, false);
  assert.throws(
    () =>
      applyDesktopSessionRunInputAuthorityV2(
        { provide: () => assert.fail('invalid config must not provide') },
        { strategy: 'legacy-client' },
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_session_run_input_authority_config_invalid',
  );

  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-session-run-input-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_SESSION_RUN_INPUT_AUTHORITY_SERVICE_V2,
        {
          kind: 'session',
          tenant_id: 'tenant / one',
          project_id: 'project / one',
          session_id: 'conversation / one',
        },
        { version: DESKTOP_SESSION_RUN_INPUT_AUTHORITY_VERSION_V2 },
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service',
  );

  const manager = new GenerationManagerV2();
  await manager.publish(generation);
  const wrongDefinitionLoader = new LoaderV2(
    rendererDefinitions().map((candidate) =>
      candidate.moduleRef === DESKTOP_SESSION_RUN_INPUT_AUTHORITY_MODULE_REF_V2
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

test('Local and vault-bound Cloud transports preserve identity, paths and signals', async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const fetchCalls = [];
  const cloudCommands = [];
  const controller = new AbortController();
  globalThis.fetch = async (input, init = {}) => {
    const url = new URL(String(input));
    fetchCalls.push({ input: String(input), init });
    return Response.json(responseForRequest(url.pathname, init.method ?? 'GET'));
  };
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          cloudCommands.push({ command, args });
          return {
            status: 200,
            body: responseForRequest(args.request.path, args.request.method),
          };
        },
      },
    },
  };

  try {
    let service;
    applyDesktopSessionRunInputAuthorityV2(
      { provide: (_key, provided) => (service = provided) },
      { strategy: 'desktop-api-client' },
    );
    const localConfig = runtimeConfig();
    const local = service.bindOperation(localConfig, identity());
    localConfig.apiBaseUrl = 'http://127.0.0.1:49999';
    await local.createRunInput(
      'run / one',
      {
        expectedRunRevision: 7,
        message: 'Review the focused change',
        messageId: 'message-1',
        idempotencyKey: 'run-input-key-1',
        delivery: 'queue_next',
        references: [],
        contextItems: [],
      },
      controller.signal,
    );
    await local.listRunInputs('run / one', controller.signal);
    await local.promoteRunInput(
      'run / one',
      'input / one',
      7,
      'promotion-key-1',
      controller.signal,
    );

    const cloud = service.bindOperation(
      runtimeConfig({
        apiBaseUrl: 'https://cloud.example.test',
        apiKey: '',
        localApiToken: '',
        mode: 'cloud',
      }),
      identity(),
    );
    await cloud.createRunInput(
      'run / one',
      {
        expectedRunRevision: 7,
        message: 'Review the focused change',
        messageId: 'message-1',
        idempotencyKey: 'run-input-key-1',
        delivery: 'queue_next',
        references: [],
        contextItems: [],
      },
      controller.signal,
    );
    await cloud.listRunInputs('run / one', controller.signal);
    await cloud.promoteRunInput(
      'run / one',
      'input / one',
      7,
      'promotion-key-1',
      controller.signal,
    );

    assert.deepEqual(
      fetchCalls.map(({ input }) => new URL(input).pathname),
      [
        '/api/v1/agent/runs/run%20%2F%20one/inputs',
        '/api/v1/agent/runs/run%20%2F%20one/inputs',
        '/api/v1/agent/run-inputs/input%20%2F%20one/promote-to-plan',
      ],
    );
    assert.equal(
      fetchCalls.every(({ init }) => init.signal === controller.signal),
      true,
    );
    for (const call of fetchCalls) {
      const headers = new Headers(call.init.headers);
      assert.equal(headers.get('Authorization'), 'Bearer run-input-session');
      assert.equal(headers.get('X-Agistack-Launch'), 'run-input-launch');
    }
    assert.deepEqual(
      cloudCommands.map(({ args }) => args.request.path),
      [
        '/api/v1/agent/runs/run%20%2F%20one/inputs',
        '/api/v1/agent/runs/run%20%2F%20one/inputs',
        '/api/v1/agent/runs/run%20%2F%20one/inputs/input%20%2F%20one/promote',
      ],
    );
    assert.equal(
      cloudCommands.every(({ command }) => command === 'cloud_request'),
      true,
    );
    assert.doesNotMatch(
      JSON.stringify(cloudCommands),
      /Authorization|run-input-session|run-input-launch/u,
    );
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});
