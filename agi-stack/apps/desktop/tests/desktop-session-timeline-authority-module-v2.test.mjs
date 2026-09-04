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
  DESKTOP_SESSION_TIMELINE_AUTHORITY_MODULE_REF_V2,
  DESKTOP_SESSION_TIMELINE_AUTHORITY_SERVICE_V2,
  DESKTOP_SESSION_TIMELINE_AUTHORITY_VERSION_V2,
  DesktopSessionTimelineAuthorityUnavailableErrorV2,
  applyDesktopSessionTimelineAuthorityV2,
  createDesktopSessionTimelineOperationsV2,
  desktopSessionTimelineAuthorityDefinitionV2,
  withDesktopSessionTimelineAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopSessionTimelineAuthorityModuleV2.js');
const { DesktopApiError } = require(COMPILED_ROOT + '/src/api/client.js');
const { desktopConversationConfigAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopConversationConfigAuthorityModuleV2.js'
);
const { desktopConversationLifecycleAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopConversationLifecycleAuthorityModuleV2.js'
);
const { desktopHitlResponseAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopHitlResponseAuthorityModuleV2.js'
);
const { desktopMyWorkAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopMyWorkAuthorityModuleV2.js'
);
const {
  desktopPluginMarketplaceCatalogDefinitionV2,
  desktopPluginMarketplaceManagementDefinitionV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopPluginMarketplaceAuthorityModulesV2.js');
const { desktopSessionProjectionAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopSessionProjectionAuthorityModuleV2.js'
);
const { desktopSessionRunChangesAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopSessionRunChangesAuthorityModuleV2.js'
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
    '/src/plugins/desktopWorkspaceExecutionSnapshotAuthorityModuleV2.js'
);
const { desktopTerminalLifecycleAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTerminalLifecycleAuthorityModuleV2.js'
);
const { desktopTenantAnalyticsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantAnalyticsAuthorityModuleV2.js',
);
const { desktopTenantCatalogAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantCatalogAuthorityModuleV2.js'
);
const { desktopTenantOverviewAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantOverviewAuthorityModuleV2.js',
);
const { desktopWorkspaceCatalogAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceCatalogAuthorityModuleV2.js'
);
const { desktopWorkspaceContextAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceContextAuthorityModuleV2.js'
);
const { desktopWorkspaceMessageCatalogAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceMessageCatalogAuthorityModuleV2.js'
);
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

const REPOSITORY_ROOT = new URL('../../../../', import.meta.url);
const BOOTSTRAP_PATH = new URL(
  'shared/profiles/memstack-default-bootstrap.v2.json',
  REPOSITORY_ROOT
);
const MANIFEST_PATH = new URL(
  'config/plugin-manifests-v2/memstack-renderer-target-hosts.v2.json',
  REPOSITORY_ROOT
);
const PROFILE_PATH = new URL(
  'config/plugin-profiles/memstack-production-target-hosts.v2.yaml',
  REPOSITORY_ROOT
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
    apiBaseUrl: 'http://127.0.0.1:46481',
    apiKey: 'timeline-session',
    localApiToken: 'timeline-launch',
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
    created_at: '2026-09-02T00:00:00Z',
    agent_config: {},
    ...overrides,
  };
}

function timelinePayload(overrides = {}) {
  return {
    conversationId: 'conversation-1',
    timeline: [],
    total: 0,
    has_more: false,
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

test('generated contract exposes one credential-free root session timeline Provider', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const bootstrap = loadBootstrap();
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_SESSION_TIMELINE_AUTHORITY_MODULE_REF_V2
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_SESSION_TIMELINE_AUTHORITY_MODULE_REF_V2
  );
  const entry = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-session-timeline-authority'
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_SESSION_TIMELINE_AUTHORITY_SERVICE_V2,
        version: DESKTOP_SESSION_TIMELINE_AUTHORITY_VERSION_V2,
      },
    ],
    requires: [],
  });
  assert.deepEqual(module.contract.events, { emits: [], handles: [] });
  assert.equal(module.contract.config_schema.additionalProperties, false);
  assert.deepEqual(module.contract.config_schema.required, ['strategy']);
  assert.equal(module.contract.config_schema.properties.strategy.const, 'desktop-api-client');
  assert.equal(module.contract_digest, catalog.contract_digest);
  assert.equal(module.contract_digest, desktopSessionTimelineAuthorityDefinitionV2.contractDigest);
  assert.equal(catalog.entrypoint, 'applyDesktopSessionTimelineAuthorityV2');
  assert.equal(
    catalog.artifact_source,
    'repo+typescript://agi-stack/apps/desktop/src/plugins/' +
      'desktopSessionTimelineAuthorityModuleV2.ts'
  );
  assert.equal(entry.module_ref, DESKTOP_SESSION_TIMELINE_AUTHORITY_MODULE_REF_V2);
  assert.equal(entry.parent_entry_id, 'builtin-desktop-renderer-host');
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-client' });
  assert.deepEqual(entry.inject, {});
  assert.equal(entry.enabled, true);
  assert.match(profile, /entry_id: builtin-desktop-session-timeline-authority/u);
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(JSON.stringify(value), /apiKey|localApiToken|Authorization/iu);
  }
});

test('Loader activates the exact service and disable removes it without fallback', async () => {
  const bootstrap = loadBootstrap();
  const loader = new LoaderV2(rendererDefinitions(), 'desktop-renderer');
  const generation = await loader.stage(bootstrap);
  const service = generation.resolve(
    DESKTOP_SESSION_TIMELINE_AUTHORITY_SERVICE_V2,
    { kind: 'root' },
    { version: DESKTOP_SESSION_TIMELINE_AUTHORITY_VERSION_V2 }
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindOperation']);
  assert.equal('config' in service, false);
  assert.equal('client' in service, false);
  assert.throws(
    () =>
      applyDesktopSessionTimelineAuthorityV2(
        {
          provide: () => assert.fail('invalid config must not provide a service'),
        },
        { strategy: 'legacy-client' }
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_session_timeline_authority_config_invalid'
  );

  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-session-timeline-authority'
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_SESSION_TIMELINE_AUTHORITY_SERVICE_V2,
        {
          kind: 'session',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          session_id: 'conversation-1',
        },
        { version: DESKTOP_SESSION_TIMELINE_AUTHORITY_VERSION_V2 }
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service'
  );

  const manager = new GenerationManagerV2();
  await manager.publish(generation);
  const wrongDefinitionLoader = new LoaderV2(
    rendererDefinitions().map((definition) =>
      definition.moduleRef === DESKTOP_SESSION_TIMELINE_AUTHORITY_MODULE_REF_V2
        ? { ...definition, contractDigest: 'sha256:' + '0'.repeat(64) }
        : definition
    ),
    'desktop-renderer'
  );
  await assert.rejects(
    wrongDefinitionLoader.stage(bootstrap),
    (error) => error instanceof RuntimeV2Error && error.code === 'contract_digest_mismatch'
  );
  assert.equal(manager.current, generation);
  await disabledGeneration.dispose();
  await manager.close();
});

test('local transport performs one exact request for each page and forwards every cursor', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    return json(timelinePayload({ page: calls.length }));
  };

  try {
    let service;
    applyDesktopSessionTimelineAuthorityV2(
      {
        provide: (_key, provided) => {
          service = provided;
        },
      },
      { strategy: 'desktop-api-client' }
    );
    const authority = service.bindOperation(runtimeConfig());
    const controller = new AbortController();
    const initial = await authority.getConversationMessages(
      conversation(),
      { limit: 75, fromTimeUs: 1_000, fromCounter: 4 },
      controller.signal
    );
    const earlier = await authority.getConversationMessages(
      conversation(),
      { limit: 50, beforeTimeUs: 2_000, beforeCounter: 7 },
      controller.signal
    );

    assert.equal(initial.page, 1);
    assert.equal(earlier.page, 2);
    assert.equal(calls.length, 2);
    assertTimelineCall(calls[0], {
      limit: '75',
      fromTimeUs: '1000',
      fromCounter: '4',
      beforeTimeUs: null,
      beforeCounter: null,
      signal: controller.signal,
    });
    assertTimelineCall(calls[1], {
      limit: '50',
      fromTimeUs: null,
      fromCounter: null,
      beforeTimeUs: '2000',
      beforeCounter: '7',
      signal: controller.signal,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('vault-bound cloud transport remains behind DesktopApiClient', async () => {
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
  const calls = [];
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: {
      __MEMSTACK_DESKTOP__: {
        core: {
          async invoke(command, args) {
            calls.push({ command, args });
            return {
              status: 200,
              body: timelinePayload({ transport: 'vault-bound-cloud' }),
            };
          },
        },
      },
    },
  });

  try {
    let service;
    applyDesktopSessionTimelineAuthorityV2(
      {
        provide: (_key, provided) => {
          service = provided;
        },
      },
      { strategy: 'desktop-api-client' }
    );
    const payload = await service
      .bindOperation(runtimeConfig({ apiKey: '', localApiToken: '', mode: 'cloud' }))
      .getConversationMessages(conversation(), { limit: 25 });

    assert.equal(payload.transport, 'vault-bound-cloud');
    assert.equal(calls.length, 1);
    assert.equal(calls[0].command, 'cloud_request');
    assert.equal(calls[0].args.request.method, 'GET');
    const url = new URL(calls[0].args.request.path, 'https://desktop.invalid');
    assert.equal(url.pathname, '/api/v1/agent/conversations/conversation-1/messages');
    assert.equal(url.searchParams.get('project_id'), 'project-1');
    assert.equal(url.searchParams.get('limit'), '25');
  } finally {
    if (originalWindow === undefined) delete globalThis.window;
    else Object.defineProperty(globalThis, 'window', originalWindow);
  }
});

test('operation freezes config, identity and page before the exact session lease', async () => {
  const lifecycle = [];
  const received = [];
  const service = Object.freeze({
    bindOperation(config) {
      received.push({ config });
      return Object.freeze({
        async getConversationMessages(identity, page, signal) {
          received.push({ identity, page, signal });
          return timelinePayload();
        },
      });
    },
  });
  const operations = createDesktopSessionTimelineOperationsV2(() =>
    acceptedActions(service, 'sha256:generation-1', lifecycle)
  );
  const config = runtimeConfig();
  const currentConversation = conversation();
  const controller = new AbortController();
  const input = {
    config,
    conversation: currentConversation,
    limit: 75,
    fromTimeUs: 1_000,
    fromCounter: 4,
    beforeTimeUs: 2_000,
    beforeCounter: 7,
    signal: controller.signal,
  };
  const pending = operations.getConversationMessages(input);
  config.apiBaseUrl = 'http://127.0.0.1:49999';
  currentConversation.id = 'mutated-conversation';
  input.limit = 1;

  assert.deepEqual(await pending, timelinePayload());
  assert.equal(Object.isFrozen(operations), true);
  assert.equal(Object.isFrozen(received[0].config), true);
  assert.equal(received[0].config.apiBaseUrl, 'http://127.0.0.1:46481');
  assert.equal(Object.isFrozen(received[1].identity), true);
  assert.equal(received[1].identity.id, 'conversation-1');
  assert.equal(received[1].identity.workspace_id, 'workspace-1');
  assert.equal(Object.isFrozen(received[1].page), true);
  assert.deepEqual(received[1].page, {
    limit: 75,
    fromTimeUs: 1_000,
    fromCounter: 4,
    beforeTimeUs: 2_000,
    beforeCounter: 7,
  });
  assert.equal(received[1].signal, controller.signal);
  assert.deepEqual(lifecycle[0].request, {
    service: DESKTOP_SESSION_TIMELINE_AUTHORITY_SERVICE_V2,
    version: DESKTOP_SESSION_TIMELINE_AUTHORITY_VERSION_V2,
    scope: {
      kind: 'session',
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      session_id: 'conversation-1',
    },
  });
  assert.deepEqual(
    lifecycle.filter((event) => event.type === 'release').map((event) => event.digest),
    ['sha256:generation-1']
  );
});

test('invalid identity, scope, page and signal fail before acquiring a lease', async () => {
  let acquireCount = 0;
  const operations = createDesktopSessionTimelineOperationsV2(() => ({
    acquireServiceOperationLease: async () => {
      acquireCount += 1;
      return {
        status: 'rejected',
        reasonCode: 'desktop_renderer_service_resolve_failed',
      };
    },
  }));
  const invoke = (overrides = {}) =>
    operations.getConversationMessages({
      config: runtimeConfig(overrides.config),
      conversation: conversation(overrides.conversation),
      limit: overrides.limit ?? 50,
      ...(overrides.cursor ?? {}),
      ...(overrides.signal === undefined ? {} : { signal: overrides.signal }),
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
        error instanceof RuntimeV2Error && error.code === 'desktop_session_timeline_scope_mismatch'
    );
  }
  for (const overrides of [
    { conversation: { id: '' } },
    { conversation: { tenant_id: ' tenant-1' } },
    { conversation: { workspace_id: '' } },
    { config: { workspaceId: ' ' } },
    { limit: 0 },
    { limit: 501 },
    { limit: 1.5 },
    { cursor: { fromTimeUs: Number.NaN } },
    { cursor: { fromCounter: Number.POSITIVE_INFINITY } },
    { cursor: { beforeTimeUs: 1.5 } },
    { signal: {} },
  ]) {
    assert.throws(
      () => invoke(overrides),
      (error) =>
        error instanceof RuntimeV2Error && error.code === 'desktop_session_timeline_input_invalid'
    );
  }
  assert.equal(acquireCount, 0);

  await assert.rejects(
    operations.getConversationMessages({
      config: runtimeConfig({ workspaceId: '' }),
      conversation: conversation({ workspace_id: null }),
      limit: 50,
    }),
    (error) =>
      error instanceof DesktopSessionTimelineAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_service_resolve_failed'
  );
  assert.equal(acquireCount, 1);
});

test('transport scope is revalidated and non-2xx preserves DesktopApiError', async () => {
  let service;
  applyDesktopSessionTimelineAuthorityV2(
    {
      provide: (_key, provided) => {
        service = provided;
      },
    },
    { strategy: 'desktop-api-client' }
  );
  const authority = service.bindOperation(runtimeConfig());
  assert.throws(
    () => authority.getConversationMessages(conversation({ project_id: 'project-other' }), {}),
    (error) =>
      error instanceof RuntimeV2Error && error.code === 'desktop_session_timeline_scope_mismatch'
  );

  const originalFetch = globalThis.fetch;
  const response = { detail: { reason_code: 'session_timeline_unavailable' } };
  globalThis.fetch = async () => json(response, 503);
  try {
    await assert.rejects(
      authority.getConversationMessages(conversation(), { limit: 50 }),
      (error) => {
        assert.equal(error instanceof DesktopApiError, true);
        assert.equal(error.status, 503);
        assert.deepEqual(error.payload, response);
        return true;
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('missing service is structured and escaped authority is revoked before release', async () => {
  let currentActions = null;
  const operations = createDesktopSessionTimelineOperationsV2(() => currentActions);
  const input = {
    config: runtimeConfig(),
    conversation: conversation(),
    limit: 50,
  };
  assert.throws(
    () => operations.getConversationMessages(input),
    (error) =>
      error instanceof DesktopSessionTimelineAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable'
  );

  currentActions = {
    acquireServiceOperationLease: async () => ({
      status: 'rejected',
      reasonCode: 'desktop_renderer_service_resolve_failed',
      runtimeCode: 'missing_service',
    }),
  };
  await assert.rejects(
    operations.getConversationMessages(input),
    (error) =>
      error instanceof DesktopSessionTimelineAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_service_resolve_failed' &&
      error.runtimeCode === 'missing_service'
  );

  let releaseStartedResolve;
  let finishRelease;
  const releaseStarted = new Promise((resolve) => {
    releaseStartedResolve = resolve;
  });
  const releasePending = new Promise((resolve) => {
    finishRelease = resolve;
  });
  let escapedAuthority = null;
  let transportCalls = 0;
  const releasing = withDesktopSessionTimelineAuthorityOperationV2(
    {
      acquireServiceOperationLease: async () => ({
        status: 'accepted',
        digest: 'sha256:deferred',
        useService(operation) {
          return operation({
            bindOperation() {
              return Object.freeze({
                async getConversationMessages() {
                  transportCalls += 1;
                  return timelinePayload();
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
    },
    input,
    (authority) => {
      escapedAuthority = authority;
      return timelinePayload();
    }
  );
  await releaseStarted;
  assert.throws(
    () => escapedAuthority.getConversationMessages(conversation(), { limit: 50 }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_session_timeline_operation_released'
  );
  assert.equal(transportCalls, 0);
  finishRelease();
  await releasing;
});

test('Abort releases once and primary failures outrank release failures', async () => {
  let releaseCount = 0;
  const controller = new AbortController();
  const abortService = Object.freeze({
    bindOperation() {
      return Object.freeze({
        getConversationMessages(_identity, _page, signal) {
          return new Promise((_resolve, reject) => {
            signal.addEventListener('abort', () => reject(signal.reason), {
              once: true,
            });
          });
        },
      });
    },
  });
  const abortOperations = createDesktopSessionTimelineOperationsV2(() => ({
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:abort',
      useService: (operation) => operation(abortService),
      async release() {
        releaseCount += 1;
      },
    }),
  }));
  const aborted = abortOperations.getConversationMessages({
    config: runtimeConfig(),
    conversation: conversation(),
    limit: 50,
    signal: controller.signal,
  });
  await Promise.resolve();
  controller.abort();
  await assert.rejects(aborted, (error) => error?.name === 'AbortError');
  assert.equal(releaseCount, 1);

  const primary = new Error('timeline_primary_failure');
  let failureReleaseCount = 0;
  const releaseFailureActions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:release-failure',
      useService(operation) {
        return operation({
          bindOperation() {
            return Object.freeze({
              async getConversationMessages() {
                return timelinePayload();
              },
            });
          },
        });
      },
      async release() {
        failureReleaseCount += 1;
        throw new Error('timeline_release_failure');
      },
    }),
  };
  const input = {
    config: runtimeConfig(),
    conversation: conversation(),
    limit: 50,
  };
  await assert.rejects(
    withDesktopSessionTimelineAuthorityOperationV2(releaseFailureActions, input, () => {
      throw primary;
    }),
    (error) => error === primary
  );
  await assert.rejects(
    withDesktopSessionTimelineAuthorityOperationV2(releaseFailureActions, input, () =>
      timelinePayload()
    ),
    /timeline_release_failure/u
  );
  assert.equal(failureReleaseCount, 2);
});

test('concurrent pages pin independent generations and release independently', async () => {
  const lifecycle = [];
  let resolveOld;
  const oldPending = new Promise((resolve) => {
    resolveOld = resolve;
  });
  const serviceFor = (label) =>
    Object.freeze({
      bindOperation() {
        return Object.freeze({
          async getConversationMessages(_identity, page) {
            lifecycle.push(`read:${label}:${page.beforeTimeUs ?? 'initial'}`);
            if (label === 'old') await oldPending;
            return timelinePayload({ source: label });
          },
        });
      },
    });
  let currentActions = acceptedActions(serviceFor('old'), 'sha256:old', lifecycle);
  const operations = createDesktopSessionTimelineOperationsV2(() => currentActions);
  const baseInput = {
    config: runtimeConfig(),
    conversation: conversation(),
    limit: 50,
  };
  const oldRead = operations.getConversationMessages(baseInput);
  await Promise.resolve();
  currentActions = acceptedActions(serviceFor('next'), 'sha256:next', lifecycle);
  const nextRead = await operations.getConversationMessages({
    ...baseInput,
    beforeTimeUs: 2_000,
    beforeCounter: 7,
  });
  resolveOld();
  const oldReadResult = await oldRead;

  assert.equal(oldReadResult.source, 'old');
  assert.equal(nextRead.source, 'next');
  assert.deepEqual(
    lifecycle.filter((event) => typeof event === 'string'),
    ['read:old:initial', 'read:next:2000']
  );
  assert.deepEqual(
    lifecycle.filter((event) => event.type === 'release').map((event) => event.digest),
    ['sha256:next', 'sha256:old']
  );
});

function assertTimelineCall(
  call,
  { limit, fromTimeUs, fromCounter, beforeTimeUs, beforeCounter, signal }
) {
  const url = new URL(call.input);
  const headers = new Headers(call.init.headers);
  assert.equal(url.pathname, '/api/v1/agent/conversations/conversation-1/messages');
  assert.equal(url.searchParams.get('project_id'), 'project-1');
  assert.equal(url.searchParams.get('limit'), limit);
  assert.equal(url.searchParams.get('from_time_us'), fromTimeUs);
  assert.equal(url.searchParams.get('from_counter'), fromCounter);
  assert.equal(url.searchParams.get('before_time_us'), beforeTimeUs);
  assert.equal(url.searchParams.get('before_counter'), beforeCounter);
  assert.equal(call.init.signal, signal);
  assert.equal(headers.get('Authorization'), 'Bearer timeline-session');
  assert.equal(headers.get('X-Agistack-Launch'), 'timeline-launch');
}
