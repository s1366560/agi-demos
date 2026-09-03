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
  DESKTOP_NEW_THREAD_CREATION_AUTHORITY_MODULE_REF_V2,
  DESKTOP_NEW_THREAD_CREATION_AUTHORITY_SERVICE_V2,
  DESKTOP_NEW_THREAD_CREATION_AUTHORITY_VERSION_V2,
  DesktopNewThreadCreationAuthorityUnavailableErrorV2,
  applyDesktopNewThreadCreationAuthorityV2,
  createDesktopNewThreadCreationOperationsV2,
  desktopNewThreadCreationAuthorityDefinitionV2,
  withDesktopNewThreadCreationAuthorityOperationV2,
} = require(
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
const { desktopArtifactContentAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopArtifactContentAuthorityModuleV2.js',
);
const { desktopAutomationAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopAutomationAuthorityModuleV2.js',
);
const { desktopConversationConfigAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopConversationConfigAuthorityModuleV2.js',
);
const { desktopConversationLifecycleAuthorityDefinitionV2 } = require(
  COMPILED_ROOT +
    '/src/plugins/desktopConversationLifecycleAuthorityModuleV2.js',
);
const { desktopHitlResponseAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopHitlResponseAuthorityModuleV2.js',
);
const { desktopMyWorkAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopMyWorkAuthorityModuleV2.js',
);
const {
  DESKTOP_NEW_TASK_FLOW_AUTHORITY_MODULE_REF_V2,
  DESKTOP_NEW_TASK_FLOW_AUTHORITY_SERVICE_V2,
  desktopNewTaskFlowAuthorityDefinitionV2,
} = require(
  COMPILED_ROOT + '/src/plugins/desktopNewTaskFlowAuthorityModuleV2.js',
);
const {
  desktopPluginMarketplaceCatalogDefinitionV2,
  desktopPluginMarketplaceManagementDefinitionV2,
} = require(
  COMPILED_ROOT + '/src/plugins/desktopPluginMarketplaceAuthorityModulesV2.js',
);
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
  COMPILED_ROOT +
    '/src/plugins/desktopWorkspaceConversationCatalogAuthorityModuleV2.js',
);
const { desktopWorkspaceExecutionSnapshotAuthorityDefinitionV2 } = require(
  COMPILED_ROOT +
    '/src/plugins/desktopWorkspaceExecutionSnapshotAuthorityModuleV2.js',
);
const { desktopWorkspaceMessageCatalogAuthorityDefinitionV2 } = require(
  COMPILED_ROOT +
    '/src/plugins/desktopWorkspaceMessageCatalogAuthorityModuleV2.js',
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
const SERVICE_GRAPH_PATH = new URL(
  'shared/graphs/plugin-service-dependencies.v2.json',
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
    require(COMPILED_ROOT + '/src/plugins/desktopProjectGraphAuthorityModuleV2.js')
      .desktopProjectGraphAuthorityDefinitionV2,
    desktopArtifactContentAuthorityDefinitionV2,
    desktopAutomationAuthorityDefinitionV2,
    desktopPluginMarketplaceCatalogDefinitionV2,
    desktopPluginMarketplaceManagementDefinitionV2,
    desktopConversationConfigAuthorityDefinitionV2,
    desktopConversationLifecycleAuthorityDefinitionV2,
    desktopHitlResponseAuthorityDefinitionV2,
    desktopMyWorkAuthorityDefinitionV2,
    desktopNewTaskFlowAuthorityDefinitionV2,
    desktopNewThreadCreationAuthorityDefinitionV2,
    desktopProjectSearchAuthorityDefinitionV2,
    desktopRuntimePoolAuthorityDefinitionV2,
    desktopSessionArtifactActionAuthorityDefinitionV2,
    desktopSessionRunControlAuthorityDefinitionV2,
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
    apiBaseUrl: 'http://127.0.0.1:46751',
    apiKey: 'api-secret-value',
    localApiToken: 'launch-secret-value',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: '',
    workspaceRoot: '',
    ...overrides,
  };
}

function conversation(overrides = {}) {
  return {
    id: 'conversation-1',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    user_id: 'user-1',
    workspace_id: null,
    workspace_name: null,
    title: 'Start a task',
    summary: null,
    status: 'active',
    message_count: 0,
    agent_config: null,
    metadata: null,
    conversation_mode: 'single_agent',
    current_mode: null,
    linked_workspace_task_id: null,
    participant_agents: [],
    coordinator_agent_id: null,
    focused_agent_id: null,
    created_at: '2026-09-02T00:00:00Z',
    updated_at: null,
    ...overrides,
  };
}

function workspace(overrides = {}) {
  return {
    id: 'workspace-1',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    name: 'Start a task',
    is_archived: false,
    ...overrides,
  };
}

function taskSessionRequest(overrides = {}) {
  return {
    idempotency_key: 'new-thread-session-1',
    workspace: { kind: 'existing', workspace_id: 'workspace-1' },
    conversation: { title: 'Start a task', capability_mode: 'work' },
    initial_message: {
      content: 'Prepare the implementation plan',
      context_items: [],
    },
    ...overrides,
  };
}

function taskSession(overrides = {}) {
  return {
    replayed: false,
    workspace: workspace(),
    conversation: conversation({
      workspace_id: 'workspace-1',
      conversation_mode: 'workspace',
      current_mode: 'plan',
      agent_config: {
        selected_agent_id: 'builtin:all-access',
        capability_mode: 'work',
      },
    }),
    initial_message: {
      id: 'message-1',
      workspace_id: 'workspace-1',
      sender_id: 'user-1',
      sender_type: 'human',
      content: 'Prepare the implementation plan',
      mentions: [],
      parent_message_id: null,
      metadata: { source: 'task_session', conversation_id: 'conversation-1' },
      created_at: '2026-09-02T00:00:00Z',
    },
    ...overrides,
  };
}

function serviceFixture(received = [], values = {}) {
  return Object.freeze({
    bindOperation(config) {
      received.push({ kind: 'bind', config });
      return Object.freeze({
        async createAgentConversation(
          title,
          projectId,
          expectedUserId,
          capabilityMode,
          agentConfig,
        ) {
          received.push({
            kind: 'createAgentConversation',
            title,
            projectId,
            expectedUserId,
            capabilityMode,
            agentConfig,
          });
          return (
            values.conversation ??
            conversation({ title, user_id: expectedUserId })
          );
        },
        async createTaskSession(input) {
          received.push({ kind: 'createTaskSession', input });
          return values.taskSession ?? taskSession();
        },
        async runAgentMessage(
          conversationId,
          message,
          messageId,
          projectId,
          workloadRole,
          execution,
        ) {
          received.push({
            kind: 'runAgentMessage',
            conversationId,
            message,
            messageId,
            projectId,
            workloadRole,
            execution,
          });
          return values.queued ?? { queued: true };
        },
      });
    },
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

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

test('generated contract declares one root Provider with an exact task-flow alias', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const bootstrap = loadBootstrap();
  const graph = JSON.parse(readFileSync(SERVICE_GRAPH_PATH, 'utf8'));
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_NEW_THREAD_CREATION_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_NEW_THREAD_CREATION_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap.entries.find(
    ({ entry_id: entryId }) =>
      entryId === 'builtin-desktop-new-thread-creation-authority',
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_NEW_THREAD_CREATION_AUTHORITY_SERVICE_V2,
        version: DESKTOP_NEW_THREAD_CREATION_AUTHORITY_VERSION_V2,
      },
    ],
    requires: [
      {
        alias: 'task_flow',
        service: DESKTOP_NEW_TASK_FLOW_AUTHORITY_SERVICE_V2,
        version: '1.0.0',
      },
    ],
  });
  assert.deepEqual(module.contract.events, { emits: [], handles: [] });
  assert.equal(module.contract.config_schema.additionalProperties, false);
  assert.deepEqual(module.contract.config_schema.required, ['strategy']);
  assert.equal(
    module.contract.config_schema.properties.strategy.const,
    'desktop-api-client',
  );
  assert.equal(module.contract_digest, catalog.contract_digest);
  assert.equal(
    module.contract_digest,
    desktopNewThreadCreationAuthorityDefinitionV2.contractDigest,
  );
  assert.equal(catalog.entrypoint, 'applyDesktopNewThreadCreationAuthorityV2');
  assert.equal(
    catalog.artifact_source,
    'repo+typescript://agi-stack/apps/desktop/src/plugins/' +
      'desktopNewThreadCreationAuthorityModuleV2.ts',
  );
  assert.equal(
    entry.module_ref,
    DESKTOP_NEW_THREAD_CREATION_AUTHORITY_MODULE_REF_V2,
  );
  assert.equal(entry.parent_entry_id, 'builtin-desktop-renderer-host');
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-client' });
  assert.deepEqual(entry.inject, {
    task_flow: DESKTOP_NEW_TASK_FLOW_AUTHORITY_SERVICE_V2,
  });
  assert.equal(entry.enabled, true);
  assert.match(
    profile,
    /entry_id: builtin-desktop-new-thread-creation-authority/u,
  );
  assert.equal(
    graph.edges.some(
      (edge) =>
        edge.consumer_module_ref ===
          DESKTOP_NEW_THREAD_CREATION_AUTHORITY_MODULE_REF_V2 &&
        edge.provider_module_ref ===
          DESKTOP_NEW_TASK_FLOW_AUTHORITY_MODULE_REF_V2 &&
        edge.alias === 'task_flow',
    ),
    true,
  );
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(
      JSON.stringify(value),
      /apiKey|localApiToken|Authorization/iu,
    );
  }
});

test('Loader activates the service and rejects a disabled required Provider without fallback', async () => {
  const bootstrap = loadBootstrap();
  const loader = new LoaderV2(rendererDefinitions(), 'desktop-renderer');
  const generation = await loader.stage(bootstrap);
  const service = generation.resolve(
    DESKTOP_NEW_THREAD_CREATION_AUTHORITY_SERVICE_V2,
    { kind: 'root' },
    { version: DESKTOP_NEW_THREAD_CREATION_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindOperation']);
  assert.throws(
    () =>
      applyDesktopNewThreadCreationAuthorityV2(
        {
          provide: () =>
            assert.fail('invalid config must not provide a service'),
        },
        { strategy: 'legacy-client' },
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_new_thread_creation_authority_config_invalid',
  );

  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    ({ entry_id: entryId }) =>
      entryId === 'builtin-desktop-new-thread-creation-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_NEW_THREAD_CREATION_AUTHORITY_SERVICE_V2,
        { kind: 'root' },
        { version: DESKTOP_NEW_THREAD_CREATION_AUTHORITY_VERSION_V2 },
      ),
    (error) =>
      error instanceof RuntimeV2Error && error.code === 'missing_service',
  );

  const missingProvider = structuredClone(bootstrap);
  missingProvider.entries.find(
    ({ entry_id: entryId }) =>
      entryId === 'builtin-desktop-new-task-flow-authority',
  ).enabled = false;
  await assert.rejects(
    loader.stage(missingProvider),
    (error) => error instanceof RuntimeV2Error,
  );

  const manager = new GenerationManagerV2();
  await manager.publish(generation);
  const wrongDefinitionLoader = new LoaderV2(
    rendererDefinitions().map((definition) =>
      definition.moduleRef ===
      DESKTOP_NEW_THREAD_CREATION_AUTHORITY_MODULE_REF_V2
        ? { ...definition, contractDigest: 'sha256:' + '0'.repeat(64) }
        : definition,
    ),
    'desktop-renderer',
  );
  await assert.rejects(
    wrongDefinitionLoader.stage(bootstrap),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'contract_digest_mismatch',
  );
  assert.equal(manager.current, generation);
  await disabledGeneration.dispose();
  await manager.close();
});

test('local service routes conversation and message transport while task creation uses its alias', async () => {
  const originalFetch = globalThis.fetch;
  const transportCalls = [];
  const taskFlowCalls = [];
  globalThis.fetch = async (input, init) => {
    const url = new URL(String(input));
    transportCalls.push({ url, init });
    if (url.pathname === '/api/v1/agent/conversations')
      return json(conversation());
    if (url.pathname.endsWith('/messages')) return json({ queued: true });
    return json({ detail: `unexpected route ${url.pathname}` }, 404);
  };
  const definitions = rendererDefinitions().map((definition) =>
    definition.moduleRef === DESKTOP_NEW_TASK_FLOW_AUTHORITY_MODULE_REF_V2
      ? {
          ...definition,
          apply(context) {
            context.provide(
              DESKTOP_NEW_TASK_FLOW_AUTHORITY_SERVICE_V2,
              Object.freeze({
                bindOperation(config) {
                  taskFlowCalls.push({ kind: 'bind', config });
                  return Object.freeze({
                    async createTaskSession(input) {
                      taskFlowCalls.push({ kind: 'createTaskSession', input });
                      return taskSession();
                    },
                  });
                },
              }),
            );
          },
        }
      : definition,
  );

  try {
    const generation = await new LoaderV2(
      definitions,
      'desktop-renderer',
    ).stage(loadBootstrap());
    const service = generation.resolve(
      DESKTOP_NEW_THREAD_CREATION_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: DESKTOP_NEW_THREAD_CREATION_AUTHORITY_VERSION_V2 },
    );
    const client = service.bindOperation(runtimeConfig());

    assert.deepEqual(
      await client.createAgentConversation(
        'Start a task',
        'project-1',
        'user-1',
        'work',
      ),
      conversation(),
    );
    assert.deepEqual(
      await client.createTaskSession(taskSessionRequest()),
      taskSession(),
    );
    assert.deepEqual(
      await client.runAgentMessage(
        'conversation-1',
        'Begin',
        'message-1',
        'project-1',
        'coding',
        { agentId: 'agent-1' },
      ),
      { queued: true },
    );
    assert.deepEqual(
      taskFlowCalls.map(({ kind }) => kind),
      ['bind', 'createTaskSession'],
    );
    assert.deepEqual(
      transportCalls.map(({ url }) => url.pathname),
      [
        '/api/v1/agent/conversations',
        '/api/v1/agent/conversations/conversation-1/messages',
      ],
    );
    for (const call of transportCalls) {
      const headers = new Headers(call.init.headers);
      assert.equal(headers.get('Authorization'), 'Bearer api-secret-value');
      assert.equal(headers.get('X-Agistack-Launch'), 'launch-secret-value');
    }
    await generation.dispose();
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Cloud service uses the vault broker for all three operations without credentials', async () => {
  const originalWindow = globalThis.window;
  const calls = [];
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          calls.push({ command, args });
          const path = args.request.path;
          return {
            status: 200,
            body: path.endsWith('/task-sessions')
              ? taskSession()
              : path === '/api/v1/agent/conversations'
                ? conversation()
                : { queued: true },
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
      DESKTOP_NEW_THREAD_CREATION_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: DESKTOP_NEW_THREAD_CREATION_AUTHORITY_VERSION_V2 },
    );
    const client = service.bindOperation(
      runtimeConfig({ mode: 'cloud', apiKey: '', localApiToken: '' }),
    );

    await client.createAgentConversation('Start a task', 'project-1', 'user-1');
    await client.createTaskSession(taskSessionRequest());
    await client.runAgentMessage(
      'conversation-1',
      'Begin',
      'message-1',
      'project-1',
    );
    assert.deepEqual(
      calls.map(({ command }) => command),
      ['cloud_request', 'cloud_request', 'cloud_request'],
    );
    assert.deepEqual(
      calls.map(({ args }) => args.request.method),
      ['POST', 'POST', 'POST'],
    );
    assert.deepEqual(
      calls.map(({ args }) => args.request.path),
      [
        '/api/v1/agent/conversations',
        '/api/v1/tenants/tenant-1/projects/project-1/task-sessions',
        '/api/v1/agent/conversations/conversation-1/messages',
      ],
    );
    assert.equal(JSON.stringify(calls).includes('api-secret-value'), false);
    assert.equal(JSON.stringify(calls).includes('launch-secret-value'), false);
    await generation.dispose();
  } finally {
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});
