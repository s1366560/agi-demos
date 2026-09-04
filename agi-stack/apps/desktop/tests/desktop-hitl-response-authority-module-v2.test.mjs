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
  DESKTOP_HITL_RESPONSE_AUTHORITY_MODULE_REF_V2,
  DESKTOP_HITL_RESPONSE_AUTHORITY_SERVICE_V2,
  DESKTOP_HITL_RESPONSE_AUTHORITY_VERSION_V2,
  DesktopHitlResponseAuthorityUnavailableErrorV2,
  applyDesktopHitlResponseAuthorityV2,
  createDesktopHitlResponseOperationsV2,
  desktopHitlResponseAuthorityDefinitionV2,
  withDesktopHitlResponseAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopHitlResponseAuthorityModuleV2.js');
const { desktopMyWorkAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopMyWorkAuthorityModuleV2.js',
);
const { DesktopApiError } = require(COMPILED_ROOT + '/src/api/client.js');
const { classifyHitlAuthorityRecovery } = require(
  COMPILED_ROOT + '/src/features/chat/hitlAuthorityRecovery.js',
);
const { desktopConversationConfigAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopConversationConfigAuthorityModuleV2.js',
);
const { desktopConversationLifecycleAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopConversationLifecycleAuthorityModuleV2.js',
);
const {
  desktopPluginMarketplaceCatalogDefinitionV2,
  desktopPluginMarketplaceManagementDefinitionV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopPluginMarketplaceAuthorityModulesV2.js');
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
    apiBaseUrl: 'http://127.0.0.1:46411',
    apiKey: 'hitl-session',
    localApiToken: 'hitl-launch',
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
    created_at: '2026-09-01T00:00:00Z',
    agent_config: {},
    ...overrides,
  };
}

function submission(overrides = {}) {
  return {
    requestId: 'request-1',
    hitlType: 'permission',
    responseData: {
      action: 'allow',
      remember: false,
      policy: { paths: ['/workspace/src'], limits: [1, 2, 3] },
    },
    expectedRevision: 1,
    idempotencyKey: 'request-1:1:permission',
    ...overrides,
  };
}

function receipt(overrides = {}) {
  return {
    success: true,
    message: 'Permission response received',
    status: 'answered',
    duplicate: false,
    request_id: 'request-1',
    authority_revision: 2,
    authority_status: 'answered',
    created_at: '2026-09-01T00:00:00+00:00',
    answered_at: '2026-09-01T00:00:01+00:00',
    expires_at: null,
    observed_at: '2026-09-01T00:00:02+00:00',
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

test('generated contract exposes one credential-free root Provider', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const bootstrap = loadBootstrap();
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_HITL_RESPONSE_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_HITL_RESPONSE_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-hitl-response-authority',
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_HITL_RESPONSE_AUTHORITY_SERVICE_V2,
        version: DESKTOP_HITL_RESPONSE_AUTHORITY_VERSION_V2,
      },
    ],
    requires: [],
  });
  assert.deepEqual(module.contract.events, { emits: [], handles: [] });
  assert.equal(module.contract.config_schema.additionalProperties, false);
  assert.deepEqual(module.contract.config_schema.required, ['strategy']);
  assert.equal(module.contract.config_schema.properties.strategy.const, 'desktop-api-client');
  assert.equal(module.contract_digest, catalog.contract_digest);
  assert.equal(module.contract_digest, desktopHitlResponseAuthorityDefinitionV2.contractDigest);
  assert.equal(catalog.entrypoint, 'applyDesktopHitlResponseAuthorityV2');
  assert.equal(
    catalog.artifact_source,
    'repo+typescript://agi-stack/apps/desktop/src/plugins/' +
      'desktopHitlResponseAuthorityModuleV2.ts',
  );
  assert.equal(entry.module_ref, DESKTOP_HITL_RESPONSE_AUTHORITY_MODULE_REF_V2);
  assert.equal(entry.parent_entry_id, 'builtin-desktop-renderer-host');
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-client' });
  assert.deepEqual(entry.inject, {});
  assert.equal(entry.enabled, true);
  assert.match(profile, /entry_id: builtin-desktop-hitl-response-authority/u);
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(JSON.stringify(value), /apiKey|localApiToken|Authorization/iu);
  }
});

test('Loader activates the exact service and disable removes it without fallback', async () => {
  const bootstrap = loadBootstrap();
  const loader = new LoaderV2(rendererDefinitions(), 'desktop-renderer');
  const generation = await loader.stage(bootstrap);
  const service = generation.resolve(
    DESKTOP_HITL_RESPONSE_AUTHORITY_SERVICE_V2,
    { kind: 'root' },
    { version: DESKTOP_HITL_RESPONSE_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindOperation']);
  assert.equal('config' in service, false);
  assert.equal('client' in service, false);
  assert.throws(
    () =>
      applyDesktopHitlResponseAuthorityV2(
        { provide: () => assert.fail('invalid config must not provide a service') },
        { strategy: 'legacy-client' },
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_hitl_response_authority_config_invalid',
  );

  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-hitl-response-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_HITL_RESPONSE_AUTHORITY_SERVICE_V2,
        {
          kind: 'session',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          session_id: 'conversation-1',
        },
        { version: DESKTOP_HITL_RESPONSE_AUTHORITY_VERSION_V2 },
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service',
  );

  const manager = new GenerationManagerV2();
  await manager.publish(generation);
  const wrongDefinitionLoader = new LoaderV2(
    rendererDefinitions().map((definition) =>
      definition.moduleRef === DESKTOP_HITL_RESPONSE_AUTHORITY_MODULE_REF_V2
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

test('revisioned transport returns only a validated immutable receipt', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const responses = [
    { ...receipt(), untrusted_extension: 'discard-me' },
    receipt({
      duplicate: true,
      expires_at: '2026-09-01T00:01:00+00:00',
    }),
  ];
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    return json(responses.shift());
  };

  try {
    const generation = await new LoaderV2(rendererDefinitions(), 'desktop-renderer').stage(
      loadBootstrap(),
    );
    const service = generation.resolve(
      DESKTOP_HITL_RESPONSE_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: DESKTOP_HITL_RESPONSE_AUTHORITY_VERSION_V2 },
    );
    const outcome = await service
      .bindOperation(runtimeConfig())
      .respond(conversation(), submission());
    const replayOutcome = await service
      .bindOperation(runtimeConfig())
      .respond(conversation(), submission());

    assert.equal(calls.length, 2);
    assert.equal(new URL(calls[0].input).pathname, '/api/v1/agent/hitl/respond');
    assert.deepEqual(JSON.parse(String(calls[0].init.body)), {
      request_id: 'request-1',
      hitl_type: 'permission',
      response_data: submission().responseData,
      expected_revision: 1,
      idempotency_key: 'request-1:1:permission',
    });
    assert.deepEqual(outcome, receipt());
    assert.equal(Object.isFrozen(outcome), true);
    assert.equal('untrusted_extension' in outcome, false);
    assert.equal(replayOutcome.duplicate, true);
    assert.equal(replayOutcome.expires_at, '2026-09-01T00:01:00+00:00');
    assert.equal(responses.length, 0);
    await generation.dispose();
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('transport conflicts preserve the original structured recovery error', async () => {
  const originalFetch = globalThis.fetch;
  const payload = {
    detail: {
      reason_code: 'hitl_already_answered',
      authority_revision: 2,
    },
  };
  globalThis.fetch = async () => json(payload, 409);

  try {
    const generation = await new LoaderV2(rendererDefinitions(), 'desktop-renderer').stage(
      loadBootstrap(),
    );
    const service = generation.resolve(
      DESKTOP_HITL_RESPONSE_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: DESKTOP_HITL_RESPONSE_AUTHORITY_VERSION_V2 },
    );
    await assert.rejects(
      service.bindOperation(runtimeConfig()).respond(conversation(), submission()),
      (error) => {
        assert.equal(error instanceof DesktopApiError, true);
        assert.equal(error.status, 409);
        assert.deepEqual(error.payload, payload);
        assert.deepEqual(classifyHitlAuthorityRecovery(error), {
          canonicalRefetch: true,
          settledByAuthority: true,
          reasonCode: 'hitl_already_answered',
        });
        return true;
      },
    );
    await generation.dispose();
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('operation freezes config, identity and JSON-safe response data before the lease', async () => {
  const lifecycle = [];
  const received = [];
  const service = Object.freeze({
    bindOperation(config) {
      received.push({ config });
      return Object.freeze({
        async respond(identity, command) {
          received.push({ identity, command });
          return receipt();
        },
      });
    },
  });
  const operations = createDesktopHitlResponseOperationsV2(() =>
    acceptedActions(service, 'sha256:generation-1', lifecycle),
  );
  const config = runtimeConfig();
  const currentConversation = conversation();
  const command = submission();
  const pending = operations.respond({
    config,
    conversation: currentConversation,
    submission: command,
  });
  config.apiBaseUrl = 'http://127.0.0.1:49999';
  currentConversation.id = 'mutated-conversation';
  command.requestId = 'mutated-request';
  command.responseData.policy.paths[0] = '/mutated';

  assert.equal((await pending).request_id, 'request-1');
  assert.equal(Object.isFrozen(operations), true);
  assert.equal(Object.isFrozen(received[0].config), true);
  assert.equal(received[0].config.apiBaseUrl, 'http://127.0.0.1:46411');
  assert.equal(Object.isFrozen(received[1].identity), true);
  assert.equal(received[1].identity.id, 'conversation-1');
  assert.equal(received[1].identity.workspace_id, 'workspace-1');
  assert.equal(Object.isFrozen(received[1].command), true);
  assert.equal(Object.isFrozen(received[1].command.responseData), true);
  assert.equal(Object.isFrozen(received[1].command.responseData.policy), true);
  assert.equal(Object.isFrozen(received[1].command.responseData.policy.paths), true);
  assert.equal(received[1].command.requestId, 'request-1');
  assert.equal(received[1].command.responseData.policy.paths[0], '/workspace/src');
  assert.deepEqual(lifecycle[0].request, {
    service: DESKTOP_HITL_RESPONSE_AUTHORITY_SERVICE_V2,
    version: DESKTOP_HITL_RESPONSE_AUTHORITY_VERSION_V2,
    scope: {
      kind: 'session',
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      session_id: 'conversation-1',
    },
  });
  assert.deepEqual(
    lifecycle.filter((event) => event.type === 'release').map((event) => event.digest),
    ['sha256:generation-1'],
  );
});

test('scope, revision, idempotency and JSON safety fail before acquiring a lease', () => {
  let acquireCount = 0;
  const operations = createDesktopHitlResponseOperationsV2(() => ({
    acquireServiceOperationLease: async () => {
      acquireCount += 1;
      return { status: 'rejected', reasonCode: 'desktop_renderer_service_resolve_failed' };
    },
  }));
  const invoke = (overrides = {}) =>
    operations.respond({
      config: runtimeConfig(overrides.config),
      conversation: conversation(overrides.conversation),
      submission: submission(overrides.submission),
    });

  for (const overrides of [
    { config: { tenantId: 'tenant-other' } },
    { config: { projectId: 'project-other' } },
    { config: { workspaceId: 'workspace-other' } },
    { conversation: { workspace_id: 'workspace-other' } },
  ]) {
    assert.throws(
      () => invoke(overrides),
      (error) =>
        error instanceof RuntimeV2Error && error.code === 'desktop_hitl_response_scope_mismatch',
    );
  }
  for (const invalidSubmission of [
    { expectedRevision: undefined },
    { expectedRevision: 2 },
    { expectedRevision: true },
    { idempotencyKey: undefined },
    { idempotencyKey: 'contains whitespace' },
    { idempotencyKey: 'non-ascii-\u00e9' },
    { idempotencyKey: 'x'.repeat(256) },
    { responseData: { value: Number.NaN } },
    { responseData: { value: Number.POSITIVE_INFINITY } },
    { responseData: { value: undefined } },
    { responseData: { value: 1n } },
    { responseData: { value: () => undefined } },
    { responseData: { value: Symbol('unsafe') } },
    { responseData: { value: new Date() } },
    { responseData: { value: new Map() } },
    { responseData: { value: Array(2) } },
  ]) {
    assert.throws(
      () => invoke({ submission: invalidSubmission }),
      (error) =>
        error instanceof RuntimeV2Error && error.code === 'desktop_hitl_response_input_invalid',
    );
  }
  const cyclic = {};
  cyclic.self = cyclic;
  assert.throws(
    () => invoke({ submission: { responseData: cyclic } }),
    (error) =>
      error instanceof RuntimeV2Error && error.code === 'desktop_hitl_response_input_invalid',
  );
  let tooDeep = { value: true };
  for (let depth = 0; depth < 40; depth += 1) tooDeep = { nested: tooDeep };
  assert.throws(
    () => invoke({ submission: { responseData: tooDeep } }),
    (error) =>
      error instanceof RuntimeV2Error && error.code === 'desktop_hitl_response_input_invalid',
  );
  assert.equal(acquireCount, 0);
});

test('every malformed or drifted success receipt fails closed', async () => {
  const originalFetch = globalThis.fetch;
  const invalidReceipts = [
    null,
    [],
    { success: false },
    receipt({ request_id: 'request-other' }),
    receipt({ status: 'pending' }),
    receipt({ authority_status: 'pending' }),
    receipt({ authority_revision: 1 }),
    receipt({ duplicate: 'false' }),
    receipt({ message: '' }),
    receipt({ created_at: '' }),
    receipt({ answered_at: null }),
    receipt({ observed_at: '' }),
    receipt({ expires_at: 123 }),
  ];
  for (const key of [
    'success',
    'message',
    'status',
    'duplicate',
    'request_id',
    'authority_revision',
    'authority_status',
    'created_at',
    'answered_at',
    'expires_at',
    'observed_at',
  ]) {
    const missing = receipt();
    delete missing[key];
    invalidReceipts.push(missing);
  }
  const invalidReceiptCount = invalidReceipts.length;
  globalThis.fetch = async () => json(invalidReceipts.shift());

  try {
    const generation = await new LoaderV2(rendererDefinitions(), 'desktop-renderer').stage(
      loadBootstrap(),
    );
    const service = generation.resolve(
      DESKTOP_HITL_RESPONSE_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: DESKTOP_HITL_RESPONSE_AUTHORITY_VERSION_V2 },
    );
    const authority = service.bindOperation(runtimeConfig());
    for (let index = 0; index < invalidReceiptCount; index += 1) {
      await assert.rejects(
        authority.respond(conversation(), submission()),
        (error) =>
          error instanceof RuntimeV2Error && error.code === 'desktop_hitl_response_receipt_invalid',
      );
    }
    assert.equal(invalidReceipts.length, 0);
    await generation.dispose();
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('missing service is structured and escaped authority is revoked exactly once', async () => {
  let currentActions = null;
  const operations = createDesktopHitlResponseOperationsV2(() => currentActions);
  assert.throws(
    () =>
      operations.respond({
        config: runtimeConfig(),
        conversation: conversation(),
        submission: submission(),
      }),
    (error) =>
      error instanceof DesktopHitlResponseAuthorityUnavailableErrorV2 &&
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
    operations.respond({
      config: runtimeConfig(),
      conversation: conversation(),
      submission: submission(),
    }),
    (error) =>
      error instanceof DesktopHitlResponseAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_service_resolve_failed' &&
      error.runtimeCode === 'missing_service',
  );

  let releaseStartedResolve;
  let finishRelease;
  const releaseStarted = new Promise((resolve) => {
    releaseStartedResolve = resolve;
  });
  const releasePending = new Promise((resolve) => {
    finishRelease = resolve;
  });
  let escapedDuringRelease = null;
  let transportCalls = 0;
  const deferredReleaseActions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:deferred',
      useService(operation) {
        return operation({
          bindOperation() {
            return Object.freeze({
              async respond() {
                transportCalls += 1;
                return receipt();
              },
            });
          },
        });
      },
      async release() {
        releaseStartedResolve();
        await releasePending;
      },
    }),
  };
  const input = {
    config: runtimeConfig(),
    conversation: conversation(),
    submission: submission(),
  };
  const releasing = withDesktopHitlResponseAuthorityOperationV2(
    deferredReleaseActions,
    input,
    (authority) => {
      escapedDuringRelease = authority;
      return receipt();
    },
  );
  await releaseStarted;
  assert.throws(
    () => escapedDuringRelease.respond(conversation(), submission()),
    (error) =>
      error instanceof RuntimeV2Error && error.code === 'desktop_hitl_response_operation_released',
  );
  assert.equal(transportCalls, 0);
  finishRelease();
  await releasing;

  const primary = new Error('hitl_primary_failure');
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
              async respond() {
                return receipt();
              },
            });
          },
        });
      },
      async release() {
        releaseCount += 1;
        throw new Error('hitl_release_failure');
      },
    }),
  };
  await assert.rejects(
    withDesktopHitlResponseAuthorityOperationV2(actions, input, (authority) => {
      escapedAuthority = authority;
      throw primary;
    }),
    (error) => error === primary,
  );
  assert.throws(
    () => escapedAuthority.respond(conversation(), submission()),
    (error) =>
      error instanceof RuntimeV2Error && error.code === 'desktop_hitl_response_operation_released',
  );
  assert.equal(releaseCount, 1);

  await assert.rejects(
    withDesktopHitlResponseAuthorityOperationV2(actions, input, () => receipt()),
    /hitl_release_failure/u,
  );
  assert.equal(releaseCount, 2);
});

test('HMR pins an in-flight response to old generation and sends the next to new', async () => {
  const lifecycle = [];
  let resolveOld;
  const oldPending = new Promise((resolve) => {
    resolveOld = resolve;
  });
  const serviceFor = (label) =>
    Object.freeze({
      bindOperation() {
        return Object.freeze({
          async respond() {
            lifecycle.push('respond:' + label);
            if (label === 'old') await oldPending;
            return receipt({ message: label });
          },
        });
      },
    });
  let currentActions = acceptedActions(serviceFor('old'), 'sha256:old', lifecycle);
  const operations = createDesktopHitlResponseOperationsV2(() => currentActions);
  const input = {
    config: runtimeConfig(),
    conversation: conversation(),
    submission: submission(),
  };
  const oldResponse = operations.respond(input);
  await Promise.resolve();
  currentActions = acceptedActions(serviceFor('next'), 'sha256:next', lifecycle);
  const nextResponse = await operations.respond(input);
  resolveOld();
  const oldResponseResult = await oldResponse;

  assert.equal(oldResponseResult.message, 'old');
  assert.equal(nextResponse.message, 'next');
  assert.deepEqual(
    lifecycle.filter((event) => typeof event === 'string'),
    ['respond:old', 'respond:next'],
  );
  assert.deepEqual(
    lifecycle.filter((event) => event.type === 'release').map((event) => event.digest),
    ['sha256:next', 'sha256:old'],
  );
});
