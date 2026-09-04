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
  DESKTOP_SESSION_RUN_CONTROL_AUTHORITY_MODULE_REF_V2,
  DESKTOP_SESSION_RUN_CONTROL_AUTHORITY_SERVICE_V2,
  DESKTOP_SESSION_RUN_CONTROL_AUTHORITY_VERSION_V2,
  applyDesktopSessionRunControlAuthorityV2,
  desktopSessionRunControlAuthorityDefinitionV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopSessionRunControlAuthorityModuleV2.js');
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
  'desktopRuntimeClustersAuthorityModuleV2',
  'desktopProjectSearchAuthorityModuleV2',
  'desktopSessionArtifactActionAuthorityModuleV2',
  'desktopSessionProjectionAuthorityModuleV2',
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
    desktopSessionRunControlAuthorityDefinitionV2,
  ];
}

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46853',
    apiKey: 'run-control-session',
    localApiToken: 'run-control-launch',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    workspaceRoot: '/workspace/project-1',
    ...overrides,
  };
}

function identity(overrides = {}) {
  return {
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    session_id: 'conversation-1',
    ...overrides,
  };
}

function run(overrides = {}) {
  return {
    id: 'run-1',
    conversation_id: 'conversation-1',
    project_id: 'project-1',
    plan_version_id: 'plan-1',
    idempotency_key: 'run-idempotency-1',
    message_id: 'message-1',
    request_message: 'Build the report',
    status: 'running',
    revision: 8,
    created_at: '2026-09-02T00:00:00Z',
    updated_at: '2026-09-02T00:01:00Z',
    authorization_snapshot: {},
    ...overrides,
  };
}

function controlOutcome(status, expectedRevision, overrides = {}) {
  return {
    accepted: true,
    status,
    run: run({ status, revision: expectedRevision + 1 }),
    ...overrides,
  };
}

function requestedOutcome(status, expectedRevision, overrides = {}) {
  return {
    accepted: true,
    status,
    run: run({ status: 'running', revision: expectedRevision }),
    ...overrides,
  };
}

function forkOutcome(overrides = {}) {
  return {
    accepted: true,
    created: true,
    status: 'running',
    source_run: run({ status: 'disconnected', revision: 9 }),
    run: run({
      id: 'recovery-run-1',
      status: 'running',
      revision: 0,
      idempotency_key: 'desktop-recovery-fork:run-1:9',
    }),
    ...overrides,
  };
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

test('generated contract declares one credential-free root run-control Provider', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const bootstrap = loadBootstrap();
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_SESSION_RUN_CONTROL_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_SESSION_RUN_CONTROL_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-session-run-control-authority',
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_SESSION_RUN_CONTROL_AUTHORITY_SERVICE_V2,
        version: DESKTOP_SESSION_RUN_CONTROL_AUTHORITY_VERSION_V2,
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
    desktopSessionRunControlAuthorityDefinitionV2.contractDigest,
  );
  assert.equal(catalog.entrypoint, 'applyDesktopSessionRunControlAuthorityV2');
  assert.equal(
    catalog.artifact_source,
    'repo+typescript://agi-stack/apps/desktop/src/plugins/' +
      'desktopSessionRunControlAuthorityModuleV2.ts',
  );
  assert.equal(entry.module_ref, DESKTOP_SESSION_RUN_CONTROL_AUTHORITY_MODULE_REF_V2);
  assert.equal(entry.parent_entry_id, 'builtin-desktop-renderer-host');
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-client' });
  assert.deepEqual(entry.inject, {});
  assert.equal(entry.enabled, true);
  assert.match(profile, /entry_id: builtin-desktop-session-run-control-authority/u);
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(JSON.stringify(value), /apiKey|localApiToken|Authorization/iu);
  }
});

test('Loader activation and Profile disable remove run-control without fallback', async () => {
  const bootstrap = loadBootstrap();
  const loader = new LoaderV2(rendererDefinitions(), 'desktop-renderer');
  const generation = await loader.stage(bootstrap);
  const service = generation.resolve(
    DESKTOP_SESSION_RUN_CONTROL_AUTHORITY_SERVICE_V2,
    { kind: 'root' },
    { version: DESKTOP_SESSION_RUN_CONTROL_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindOperation']);
  assert.equal('config' in service, false);
  assert.equal('client' in service, false);
  assert.throws(
    () => service.bindOperation(runtimeConfig(), identity({ tenant_id: 'tenant-2' })),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_session_run_control_scope_mismatch',
  );
  assert.throws(
    () =>
      applyDesktopSessionRunControlAuthorityV2(
        { provide: () => assert.fail('invalid config must not provide') },
        { strategy: 'legacy-client' },
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_session_run_control_authority_config_invalid',
  );

  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-session-run-control-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_SESSION_RUN_CONTROL_AUTHORITY_SERVICE_V2,
        {
          kind: 'session',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          session_id: 'conversation-1',
        },
        { version: DESKTOP_SESSION_RUN_CONTROL_AUTHORITY_VERSION_V2 },
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service',
  );
  await disabledGeneration.dispose();
  await generation.dispose();
});

test('Local and Cloud transports preserve five mutation contracts and vault secrecy', async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const localCalls = [];
  globalThis.fetch = async (input, init) => {
    localCalls.push({ input, init });
    const action = new URL(String(input)).pathname.split('/').at(-1);
    const body = JSON.parse(String(init.body));
    if (action === 'fork') return json(forkOutcome());
    if (action === 'pause') {
      return json(requestedOutcome('pause_requested', body.expected_revision));
    }
    if (action === 'cancel') {
      return json(requestedOutcome('cancel_requested', body.expected_revision));
    }
    const statuses = {
      resume: 'running',
      review: body.action === 'approve' ? 'completed' : 'running',
    };
    return json(controlOutcome(statuses[action], body.expected_revision));
  };

  try {
    const generation = await new LoaderV2(rendererDefinitions(), 'desktop-renderer').stage(
      loadBootstrap(),
    );
    const service = generation.resolve(
      DESKTOP_SESSION_RUN_CONTROL_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: DESKTOP_SESSION_RUN_CONTROL_AUTHORITY_VERSION_V2 },
    );
    const local = service.bindOperation(runtimeConfig(), identity());
    await local.pauseRun('run-1', 7);
    await local.resumeRun('run-1', 8);
    await local.forkRecoveryRun('run-1', 9, 'desktop-recovery-fork:run-1:9');
    await local.cancelRun('run-1', 10);
    await local.reviewRun('run-1', {
      action: 'request_changes',
      expectedRevision: 11,
      feedback: 'Add the missing evidence.',
    });

    assert.deepEqual(
      localCalls.map(({ input }) => new URL(String(input)).pathname),
      [
        '/api/v1/agent/runs/run-1/pause',
        '/api/v1/agent/runs/run-1/resume',
        '/api/v1/agent/runs/run-1/fork',
        '/api/v1/agent/runs/run-1/cancel',
        '/api/v1/agent/runs/run-1/review',
      ],
    );
    assert.deepEqual(
      localCalls.map(({ init }) => JSON.parse(String(init.body))),
      [
        { expected_revision: 7 },
        { expected_revision: 8 },
        {
          expected_revision: 9,
          idempotency_key: 'desktop-recovery-fork:run-1:9',
        },
        { expected_revision: 10 },
        {
          action: 'request_changes',
          expected_revision: 11,
          feedback: 'Add the missing evidence.',
        },
      ],
    );
    for (const { init } of localCalls) {
      assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer run-control-session');
      assert.equal(new Headers(init.headers).get('X-Agistack-Launch'), 'run-control-launch');
    }

    const cloudCalls = [];
    globalThis.window = {
      __MEMSTACK_DESKTOP__: {
        core: {
          async invoke(command, args) {
            cloudCalls.push({ command, args });
            return {
              status: 200,
              body: requestedOutcome('pause_requested', 12, {
                run: run({ id: 'cloud-run', status: 'running', revision: 12 }),
              }),
            };
          },
        },
      },
    };
    const cloud = service.bindOperation(
      runtimeConfig({ mode: 'cloud', apiKey: '', localApiToken: '' }),
      identity(),
    );
    await cloud.pauseRun('cloud-run', 12);
    assert.deepEqual(
      cloudCalls.map(({ command, args }) => ({ command, request: args.request })),
      [
        {
          command: 'cloud_request',
          request: {
            path: '/api/v1/agent/runs/cloud-run/pause',
            method: 'POST',
            body: { expected_revision: 12 },
          },
        },
      ],
    );
    assert.equal(JSON.stringify(cloudCalls).includes('run-control-session'), false);
    assert.equal(JSON.stringify(cloudCalls).includes('run-control-launch'), false);
    assert.equal(JSON.stringify(cloudCalls).includes('Bearer'), false);
    await generation.dispose();
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});
