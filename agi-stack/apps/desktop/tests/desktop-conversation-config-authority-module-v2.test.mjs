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
  DESKTOP_CONVERSATION_CONFIG_AUTHORITY_MODULE_REF_V2,
  DESKTOP_CONVERSATION_CONFIG_AUTHORITY_SERVICE_V2,
  DESKTOP_CONVERSATION_CONFIG_AUTHORITY_VERSION_V2,
  DesktopConversationConfigAuthorityUnavailableErrorV2,
  applyDesktopConversationConfigAuthorityV2,
  createDesktopConversationConfigOperationsV2,
  desktopConversationConfigAuthorityDefinitionV2,
  withDesktopConversationConfigAuthorityOperationV2,
} = require(
  COMPILED_ROOT + '/src/plugins/desktopConversationConfigAuthorityModuleV2.js',
);
const { desktopConversationLifecycleAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopConversationLifecycleAuthorityModuleV2.js',
);
const {
  desktopPluginMarketplaceCatalogDefinitionV2,
  desktopPluginMarketplaceManagementDefinitionV2,
} = require(
  COMPILED_ROOT + '/src/plugins/desktopPluginMarketplaceAuthorityModulesV2.js',
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
  COMPILED_ROOT +
    '/src/plugins/desktopWorkspaceConversationCatalogAuthorityModuleV2.js',
);
const { desktopWorkspaceExecutionSnapshotAuthorityDefinitionV2 } = require(
  COMPILED_ROOT +
    '/src/plugins/desktopWorkspaceExecutionSnapshotAuthorityModuleV2.js',
);
const { desktopTerminalLifecycleAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTerminalLifecycleAuthorityModuleV2.js',
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
    require(COMPILED_ROOT + '/src/plugins/desktopProjectGraphAuthorityModuleV2.js')
      .desktopProjectGraphAuthorityDefinitionV2,
    desktopArtifactContentAuthorityDefinitionV2,
    desktopAutomationAuthorityDefinitionV2,
    desktopNewTaskFlowAuthorityDefinitionV2,
    desktopNewThreadCreationAuthorityDefinitionV2,
    desktopProjectSearchAuthorityDefinitionV2,
    desktopRuntimePoolAuthorityDefinitionV2,
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
    apiKey: 'conversation-session',
    localApiToken: 'conversation-launch',
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

test('generated contract exposes one credential-free root Provider', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const bootstrap = loadBootstrap();
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_CONVERSATION_CONFIG_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_CONVERSATION_CONFIG_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-conversation-config-authority',
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_CONVERSATION_CONFIG_AUTHORITY_SERVICE_V2,
        version: DESKTOP_CONVERSATION_CONFIG_AUTHORITY_VERSION_V2,
      },
    ],
    requires: [],
  });
  assert.deepEqual(module.contract.events, { emits: [], handles: [] });
  assert.equal(module.contract.config_schema.additionalProperties, false);
  assert.deepEqual(module.contract.config_schema.required, ['strategy']);
  assert.equal(module.contract.config_schema.properties.strategy.const, 'desktop-api-client');
  assert.equal(module.contract_digest, catalog.contract_digest);
  assert.equal(module.contract_digest, desktopConversationConfigAuthorityDefinitionV2.contractDigest);
  assert.equal(catalog.entrypoint, 'applyDesktopConversationConfigAuthorityV2');
  assert.equal(
    catalog.artifact_source,
    'repo+typescript://agi-stack/apps/desktop/src/plugins/' +
      'desktopConversationConfigAuthorityModuleV2.ts',
  );
  assert.equal(entry.module_ref, DESKTOP_CONVERSATION_CONFIG_AUTHORITY_MODULE_REF_V2);
  assert.equal(entry.parent_entry_id, 'builtin-desktop-renderer-host');
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-client' });
  assert.deepEqual(entry.inject, {});
  assert.equal(entry.enabled, true);
  assert.match(profile, /entry_id: builtin-desktop-conversation-config-authority/u);
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(JSON.stringify(value), /apiKey|localApiToken|Authorization/iu);
  }
});

test('Loader activates the exact service and disable removes it without fallback', async () => {
  const bootstrap = loadBootstrap();
  const loader = new LoaderV2(rendererDefinitions(), 'desktop-renderer');
  const generation = await loader.stage(bootstrap);
  const service = generation.resolve(
    DESKTOP_CONVERSATION_CONFIG_AUTHORITY_SERVICE_V2,
    { kind: 'root' },
    { version: DESKTOP_CONVERSATION_CONFIG_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindOperation']);
  assert.equal('config' in service, false);
  assert.equal('client' in service, false);
  assert.throws(
    () =>
      applyDesktopConversationConfigAuthorityV2(
        { provide: () => assert.fail('invalid config must not provide a service') },
        { strategy: 'legacy-client' },
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_conversation_config_authority_config_invalid',
  );

  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-conversation-config-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_CONVERSATION_CONFIG_AUTHORITY_SERVICE_V2,
        {
          kind: 'session',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          session_id: 'conversation-1',
        },
        { version: DESKTOP_CONVERSATION_CONFIG_AUTHORITY_VERSION_V2 },
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service',
  );

  const manager = new GenerationManagerV2();
  await manager.publish(generation);
  const wrongDefinitionLoader = new LoaderV2(
    rendererDefinitions().map((definition) =>
      definition.moduleRef === DESKTOP_CONVERSATION_CONFIG_AUTHORITY_MODULE_REF_V2
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

test('local includes the route override while cloud explicitly omits it', async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const fetchCalls = [];
  const cloudCommands = [];
  globalThis.fetch = async (input, init) => {
    fetchCalls.push({ input: String(input), init });
    return json(conversation({ agent_config: { llm_model_override: 'model-local' } }));
  };
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          cloudCommands.push({ command, args });
          return {
            status: 200,
            body: conversation({ agent_config: { llm_model_override: 'model-cloud' } }),
          };
        },
      },
    },
  };

  try {
    const generation = await new LoaderV2(
      rendererDefinitions(),
      'desktop-renderer',
    ).stage(loadBootstrap());
    const service = generation.resolve(
      DESKTOP_CONVERSATION_CONFIG_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: DESKTOP_CONVERSATION_CONFIG_AUTHORITY_VERSION_V2 },
    );
    const local = service.bindOperation(runtimeConfig());
    const cloud = service.bindOperation(
      runtimeConfig({
        apiBaseUrl: 'https://cloud.example.test',
        apiKey: '',
        localApiToken: '',
        mode: 'cloud',
      }),
    );
    const route = { provider_id: 'provider-local', model_id: 'model-local' };
    const pendingLocal = local.updateModelOverride(conversation(), {
      llmModelOverride: 'model-local',
      llmRouteOverride: route,
    });
    route.provider_id = 'mutated-provider';
    await pendingLocal;
    await cloud.updateModelOverride(conversation(), {
      llmModelOverride: 'model-cloud',
      llmRouteOverride: { provider_id: 'provider-cloud', model_id: 'model-cloud' },
    });

    assert.equal(fetchCalls.length, 1);
    const localUrl = new URL(fetchCalls[0].input);
    assert.equal(localUrl.pathname, '/api/v1/agent/conversations/conversation-1/config');
    assert.equal(localUrl.searchParams.get('project_id'), 'project-1');
    assert.deepEqual(JSON.parse(String(fetchCalls[0].init.body)), {
      llm_model_override: 'model-local',
      llm_route_override: { provider_id: 'provider-local', model_id: 'model-local' },
    });
    assert.equal(cloudCommands.length, 1);
    assert.equal(cloudCommands[0].command, 'cloud_request');
    assert.deepEqual(cloudCommands[0].args.request, {
      path: '/api/v1/agent/conversations/conversation-1/config?project_id=project-1',
      method: 'PATCH',
      body: { llm_model_override: 'model-cloud' },
    });
    await generation.dispose();
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test('each mutation freezes inputs before acquiring one exact session lease', async () => {
  const lifecycle = [];
  const received = [];
  const service = Object.freeze({
    bindOperation(config) {
      received.push({ config });
      return Object.freeze({
        async updateModelOverride(identity, mutation) {
          received.push({ identity, mutation });
          return conversation();
        },
      });
    },
  });
  const actions = acceptedActions(service, 'sha256:generation-1', lifecycle);
  const operations = createDesktopConversationConfigOperationsV2(() => actions);
  const config = runtimeConfig();
  const currentConversation = conversation();
  const route = { provider_id: 'provider-1', model_id: 'model-1' };
  const pending = operations.updateModelOverride({
    config,
    conversation: currentConversation,
    llmModelOverride: 'model-1',
    llmRouteOverride: route,
  });
  config.apiBaseUrl = 'http://127.0.0.1:49999';
  currentConversation.id = 'mutated-conversation';
  route.provider_id = 'mutated-provider';

  assert.equal((await pending).id, 'conversation-1');
  assert.equal(Object.isFrozen(operations), true);
  assert.equal(Object.isFrozen(received[0].config), true);
  assert.equal(received[0].config.apiBaseUrl, 'http://127.0.0.1:46411');
  assert.equal(Object.isFrozen(received[1].identity), true);
  assert.equal(received[1].identity.id, 'conversation-1');
  assert.equal(Object.isFrozen(received[1].mutation), true);
  assert.equal(Object.isFrozen(received[1].mutation.llmRouteOverride), true);
  assert.equal(received[1].mutation.llmRouteOverride.provider_id, 'provider-1');
  assert.deepEqual(lifecycle[0].request, {
    service: DESKTOP_CONVERSATION_CONFIG_AUTHORITY_SERVICE_V2,
    version: DESKTOP_CONVERSATION_CONFIG_AUTHORITY_VERSION_V2,
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

test('scope mismatch and every response identity drift fail closed', async () => {
  let acquireCount = 0;
  const operations = createDesktopConversationConfigOperationsV2(() => ({
    acquireServiceOperationLease: async () => {
      acquireCount += 1;
      return { status: 'rejected', reasonCode: 'desktop_renderer_service_resolve_failed' };
    },
  }));

  for (const configOverrides of [
    { tenantId: 'tenant-other' },
    { projectId: 'project-other' },
  ]) {
    assert.throws(
      () =>
        operations.updateModelOverride({
          config: runtimeConfig(configOverrides),
          conversation: conversation(),
          llmModelOverride: null,
          llmRouteOverride: null,
        }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_conversation_config_scope_mismatch',
    );
  }
  assert.equal(acquireCount, 0);

  const originalFetch = globalThis.fetch;
  const responseDrifts = [
    { id: 'conversation-other' },
    { tenant_id: 'tenant-other' },
    { project_id: 'project-other' },
    { workspace_id: 'workspace-other' },
  ];
  globalThis.fetch = async () => json(conversation(responseDrifts.shift()));
  try {
    const generation = await new LoaderV2(
      rendererDefinitions(),
      'desktop-renderer',
    ).stage(loadBootstrap());
    const service = generation.resolve(
      DESKTOP_CONVERSATION_CONFIG_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: DESKTOP_CONVERSATION_CONFIG_AUTHORITY_VERSION_V2 },
    );
    const authority = service.bindOperation(runtimeConfig());
    for (let index = 0; index < 4; index += 1) {
      await assert.rejects(
        authority.updateModelOverride(conversation(), {
          llmModelOverride: null,
          llmRouteOverride: null,
        }),
        (error) =>
          error instanceof RuntimeV2Error &&
          error.code === 'desktop_conversation_config_response_scope_mismatch',
      );
    }
    assert.equal(responseDrifts.length, 0);
    await generation.dispose();
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('missing service is structured and escaped authority is revoked once', async () => {
  let currentActions = null;
  const operations = createDesktopConversationConfigOperationsV2(() => currentActions);
  assert.throws(
    () =>
      operations.updateModelOverride({
        config: runtimeConfig(),
        conversation: conversation(),
        llmModelOverride: null,
        llmRouteOverride: null,
      }),
    (error) =>
      error instanceof DesktopConversationConfigAuthorityUnavailableErrorV2 &&
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
    operations.updateModelOverride({
      config: runtimeConfig(),
      conversation: conversation(),
      llmModelOverride: null,
      llmRouteOverride: null,
    }),
    (error) =>
      error instanceof DesktopConversationConfigAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_service_resolve_failed' &&
      error.runtimeCode === 'missing_service',
  );

  const primary = new Error('conversation_config_primary_failure');
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
              async updateModelOverride() {
                return conversation();
              },
            });
          },
        });
      },
      async release() {
        releaseCount += 1;
        throw new Error('conversation_config_release_failure');
      },
    }),
  };
  const input = {
    config: runtimeConfig(),
    conversation: conversation(),
    llmModelOverride: null,
    llmRouteOverride: null,
  };

  await assert.rejects(
    withDesktopConversationConfigAuthorityOperationV2(actions, input, (authority) => {
      escapedAuthority = authority;
      throw primary;
    }),
    (error) => error === primary,
  );
  assert.throws(
    () =>
      escapedAuthority.updateModelOverride(conversation(), {
        llmModelOverride: null,
        llmRouteOverride: null,
      }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_conversation_config_operation_released',
  );
  assert.equal(releaseCount, 1);

  await assert.rejects(
    withDesktopConversationConfigAuthorityOperationV2(actions, input, () => conversation()),
    /conversation_config_release_failure/u,
  );
  assert.equal(releaseCount, 2);
});

test('HMR keeps an in-flight mutation on old generation and sends the next to new', async () => {
  const lifecycle = [];
  let resolveOld;
  const oldPending = new Promise((resolve) => {
    resolveOld = resolve;
  });
  const serviceFor = (label) =>
    Object.freeze({
      bindOperation() {
        return Object.freeze({
          async updateModelOverride() {
            lifecycle.push('update:' + label);
            if (label === 'old') await oldPending;
            return conversation({ id: 'conversation-' + label });
          },
        });
      },
    });
  let currentActions = acceptedActions(
    serviceFor('old'),
    'sha256:old',
    lifecycle,
  );
  const operations = createDesktopConversationConfigOperationsV2(() => currentActions);
  const input = {
    config: runtimeConfig(),
    conversation: conversation(),
    llmModelOverride: null,
    llmRouteOverride: null,
  };
  const oldMutation = operations.updateModelOverride(input);
  await Promise.resolve();
  currentActions = acceptedActions(serviceFor('next'), 'sha256:next', lifecycle);
  const nextMutation = await operations.updateModelOverride(input);
  resolveOld();
  const oldMutationResult = await oldMutation;

  assert.equal(oldMutationResult.id, 'conversation-old');
  assert.equal(nextMutation.id, 'conversation-next');
  assert.deepEqual(
    lifecycle.filter((event) => typeof event === 'string'),
    ['update:old', 'update:next'],
  );
  assert.deepEqual(
    lifecycle.filter((event) => event.type === 'release').map((event) => event.digest),
    ['sha256:next', 'sha256:old'],
  );
});
