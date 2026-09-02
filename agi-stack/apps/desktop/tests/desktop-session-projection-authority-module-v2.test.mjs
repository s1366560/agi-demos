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
  DESKTOP_SESSION_PROJECTION_AUTHORITY_MODULE_REF_V2,
  DESKTOP_SESSION_PROJECTION_AUTHORITY_SERVICE_V2,
  DESKTOP_SESSION_PROJECTION_AUTHORITY_VERSION_V2,
  DesktopSessionProjectionAuthorityUnavailableErrorV2,
  applyDesktopSessionProjectionAuthorityV2,
  createDesktopSessionProjectionOperationsV2,
  desktopSessionProjectionAuthorityDefinitionV2,
  withDesktopSessionProjectionAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopSessionProjectionAuthorityModuleV2.js');
const { desktopSessionRunChangesAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopSessionRunChangesAuthorityModuleV2.js',
);
const { DesktopApiError } = require(COMPILED_ROOT + '/src/api/client.js');
const { desktopConversationConfigAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopConversationConfigAuthorityModuleV2.js',
);
const { desktopConversationLifecycleAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopConversationLifecycleAuthorityModuleV2.js',
);
const { desktopHitlResponseAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopHitlResponseAuthorityModuleV2.js',
);
const { desktopMyWorkAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopMyWorkAuthorityModuleV2.js',
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
    require(COMPILED_ROOT + '/src/plugins/desktopSessionRunInputAuthorityModuleV2.js')
      .desktopSessionRunInputAuthorityDefinitionV2,
    desktopArtifactContentAuthorityDefinitionV2,
    desktopAutomationAuthorityDefinitionV2,
    desktopNewTaskFlowAuthorityDefinitionV2,
    desktopNewThreadCreationAuthorityDefinitionV2,
    desktopProjectSearchAuthorityDefinitionV2,
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
    apiBaseUrl: 'http://127.0.0.1:46421',
    apiKey: 'projection-session',
    localApiToken: 'projection-launch',
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

function projection(overrides = {}) {
  return {
    schema_version: 2,
    projection_kind: 'workspace_session',
    snapshot_revision: 'projection-revision-1',
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

test('generated contract exposes one credential-free root session projection Provider', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const bootstrap = loadBootstrap();
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_SESSION_PROJECTION_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_SESSION_PROJECTION_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-session-projection-authority',
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_SESSION_PROJECTION_AUTHORITY_SERVICE_V2,
        version: DESKTOP_SESSION_PROJECTION_AUTHORITY_VERSION_V2,
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
    desktopSessionProjectionAuthorityDefinitionV2.contractDigest,
  );
  assert.equal(catalog.entrypoint, 'applyDesktopSessionProjectionAuthorityV2');
  assert.equal(
    catalog.artifact_source,
    'repo+typescript://agi-stack/apps/desktop/src/plugins/' +
      'desktopSessionProjectionAuthorityModuleV2.ts',
  );
  assert.equal(entry.module_ref, DESKTOP_SESSION_PROJECTION_AUTHORITY_MODULE_REF_V2);
  assert.equal(entry.parent_entry_id, 'builtin-desktop-renderer-host');
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-client' });
  assert.deepEqual(entry.inject, {});
  assert.equal(entry.enabled, true);
  assert.match(profile, /entry_id: builtin-desktop-session-projection-authority/u);
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(JSON.stringify(value), /apiKey|localApiToken|Authorization/iu);
  }
});

test('Loader activates the exact service and disable removes it without fallback', async () => {
  const bootstrap = loadBootstrap();
  const loader = new LoaderV2(rendererDefinitions(), 'desktop-renderer');
  const generation = await loader.stage(bootstrap);
  const service = generation.resolve(
    DESKTOP_SESSION_PROJECTION_AUTHORITY_SERVICE_V2,
    { kind: 'root' },
    { version: DESKTOP_SESSION_PROJECTION_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindOperation']);
  assert.equal('config' in service, false);
  assert.equal('client' in service, false);
  assert.throws(
    () =>
      applyDesktopSessionProjectionAuthorityV2(
        {
          provide: () => assert.fail('invalid config must not provide a service'),
        },
        { strategy: 'legacy-client' },
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_session_projection_authority_config_invalid',
  );

  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-session-projection-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_SESSION_PROJECTION_AUTHORITY_SERVICE_V2,
        {
          kind: 'session',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          session_id: 'conversation-1',
        },
        { version: DESKTOP_SESSION_PROJECTION_AUTHORITY_VERSION_V2 },
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service',
  );

  const manager = new GenerationManagerV2();
  await manager.publish(generation);
  const wrongDefinitionLoader = new LoaderV2(
    rendererDefinitions().map((definition) =>
      definition.moduleRef === DESKTOP_SESSION_PROJECTION_AUTHORITY_MODULE_REF_V2
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

test('local transport preserves exact scope, credentials, signal and unknown response', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    return json(projection({ transport_extension: { retained: true } }));
  };

  try {
    const generation = await new LoaderV2(rendererDefinitions(), 'desktop-renderer').stage(
      loadBootstrap(),
    );
    const service = generation.resolve(
      DESKTOP_SESSION_PROJECTION_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: DESKTOP_SESSION_PROJECTION_AUTHORITY_VERSION_V2 },
    );
    const controller = new AbortController();
    const payload = await service
      .bindOperation(runtimeConfig())
      .getConversationSession(conversation(), controller.signal);

    assert.deepEqual(payload, projection({ transport_extension: { retained: true } }));
    assert.equal(calls.length, 1);
    const call = calls[0];
    const url = new URL(call.input);
    const headers = new Headers(call.init.headers);
    assert.equal(url.pathname, '/api/v1/agent/conversations/conversation-1/session');
    assert.equal(url.searchParams.get('tenant_id'), 'tenant-1');
    assert.equal(url.searchParams.get('project_id'), 'project-1');
    assert.equal(url.searchParams.get('workspace_id'), 'workspace-1');
    assert.equal(call.init.signal, controller.signal);
    assert.equal(headers.get('Authorization'), 'Bearer projection-session');
    assert.equal(headers.get('X-Agistack-Launch'), 'projection-launch');
    await generation.dispose();
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('vault-bound cloud transport stays behind DesktopApiClient and forwards AbortSignal', async () => {
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
  const controller = new AbortController();
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
              body: projection({ transport: 'vault-bound-cloud' }),
            };
          },
        },
      },
    },
  });

  try {
    let service;
    applyDesktopSessionProjectionAuthorityV2(
      {
        provide: (_key, provided) => {
          service = provided;
        },
      },
      { strategy: 'desktop-api-client' },
    );
    const payload = await service
      .bindOperation(runtimeConfig({ apiKey: '', localApiToken: '', mode: 'cloud' }))
      .getConversationSession(conversation(), controller.signal);

    assert.deepEqual(payload, projection({ transport: 'vault-bound-cloud' }));
    assert.equal(calls.length, 1);
    assert.equal(calls[0].command, 'cloud_request');
    assert.equal(calls[0].args.request.method, 'GET');
    const url = new URL(calls[0].args.request.path, 'https://desktop.invalid');
    assert.equal(url.pathname, '/api/v1/agent/conversations/conversation-1/session');
    assert.equal(url.searchParams.get('tenant_id'), 'tenant-1');
    assert.equal(url.searchParams.get('project_id'), 'project-1');
    assert.equal(url.searchParams.get('workspace_id'), 'workspace-1');
  } finally {
    if (originalWindow === undefined) delete globalThis.window;
    else Object.defineProperty(globalThis, 'window', originalWindow);
  }
});

test('operation freezes config and identity before the exact session lease', async () => {
  const lifecycle = [];
  const received = [];
  const service = Object.freeze({
    bindOperation(config) {
      received.push({ config });
      return Object.freeze({
        async getConversationSession(identity, signal) {
          received.push({ identity, signal });
          return projection();
        },
      });
    },
  });
  const operations = createDesktopSessionProjectionOperationsV2(() =>
    acceptedActions(service, 'sha256:generation-1', lifecycle),
  );
  const config = runtimeConfig();
  const currentConversation = conversation();
  const controller = new AbortController();
  const pending = operations.getConversationSession({
    config,
    conversation: currentConversation,
    signal: controller.signal,
  });
  config.apiBaseUrl = 'http://127.0.0.1:49999';
  currentConversation.id = 'mutated-conversation';

  assert.deepEqual(await pending, projection());
  assert.equal(Object.isFrozen(operations), true);
  assert.equal(Object.isFrozen(received[0].config), true);
  assert.equal(received[0].config.apiBaseUrl, 'http://127.0.0.1:46421');
  assert.equal(Object.isFrozen(received[1].identity), true);
  assert.equal(received[1].identity.id, 'conversation-1');
  assert.equal(received[1].identity.workspace_id, 'workspace-1');
  assert.equal(received[1].signal, controller.signal);
  assert.deepEqual(lifecycle[0].request, {
    service: DESKTOP_SESSION_PROJECTION_AUTHORITY_SERVICE_V2,
    version: DESKTOP_SESSION_PROJECTION_AUTHORITY_VERSION_V2,
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

test('invalid input and scope mismatch fail before acquiring a lease', () => {
  let acquireCount = 0;
  const operations = createDesktopSessionProjectionOperationsV2(() => ({
    acquireServiceOperationLease: async () => {
      acquireCount += 1;
      return {
        status: 'rejected',
        reasonCode: 'desktop_renderer_service_resolve_failed',
      };
    },
  }));
  const invoke = (overrides = {}) =>
    operations.getConversationSession({
      config: runtimeConfig(overrides.config),
      conversation: conversation(overrides.conversation),
      signal: overrides.signal ?? new AbortController().signal,
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
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_session_projection_scope_mismatch',
    );
  }
  for (const overrides of [
    { conversation: { id: '' } },
    { conversation: { tenant_id: ' tenant-1' } },
    { conversation: { workspace_id: '' } },
    { signal: {} },
  ]) {
    assert.throws(
      () => invoke(overrides),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_session_projection_input_invalid',
    );
  }
  assert.equal(acquireCount, 0);
});

test('non-2xx transport preserves the original DesktopApiError', async () => {
  const originalFetch = globalThis.fetch;
  const response = {
    detail: { reason_code: 'session_projection_unavailable' },
  };
  globalThis.fetch = async () => json(response, 503);

  try {
    let service;
    applyDesktopSessionProjectionAuthorityV2(
      {
        provide: (_key, provided) => {
          service = provided;
        },
      },
      { strategy: 'desktop-api-client' },
    );
    await assert.rejects(
      service
        .bindOperation(runtimeConfig())
        .getConversationSession(conversation(), new AbortController().signal),
      (error) => {
        assert.equal(error instanceof DesktopApiError, true);
        assert.equal(error.status, 503);
        assert.deepEqual(error.payload, response);
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('missing service is structured and escaped authority is revoked before release', async () => {
  let currentActions = null;
  const operations = createDesktopSessionProjectionOperationsV2(() => currentActions);
  const input = {
    config: runtimeConfig(),
    conversation: conversation(),
    signal: new AbortController().signal,
  };
  assert.throws(
    () => operations.getConversationSession(input),
    (error) =>
      error instanceof DesktopSessionProjectionAuthorityUnavailableErrorV2 &&
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
    operations.getConversationSession(input),
    (error) =>
      error instanceof DesktopSessionProjectionAuthorityUnavailableErrorV2 &&
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
  let escapedAuthority = null;
  let transportCalls = 0;
  const releasing = withDesktopSessionProjectionAuthorityOperationV2(
    {
      acquireServiceOperationLease: async () => ({
        status: 'accepted',
        digest: 'sha256:deferred',
        useService(operation) {
          return operation({
            bindOperation() {
              return Object.freeze({
                async getConversationSession() {
                  transportCalls += 1;
                  return projection();
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
      return projection();
    },
  );
  await releaseStarted;
  assert.throws(
    () => escapedAuthority.getConversationSession(conversation(), input.signal),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_session_projection_operation_released',
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
        getConversationSession(_identity, signal) {
          return new Promise((_resolve, reject) => {
            signal.addEventListener('abort', () => reject(signal.reason), {
              once: true,
            });
          });
        },
      });
    },
  });
  const abortOperations = createDesktopSessionProjectionOperationsV2(() => ({
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:abort',
      useService: (operation) => operation(abortService),
      async release() {
        releaseCount += 1;
      },
    }),
  }));
  const aborted = abortOperations.getConversationSession({
    config: runtimeConfig(),
    conversation: conversation(),
    signal: controller.signal,
  });
  await Promise.resolve();
  controller.abort();
  await assert.rejects(aborted, (error) => error?.name === 'AbortError');
  assert.equal(releaseCount, 1);

  const primary = new Error('projection_primary_failure');
  let failureReleaseCount = 0;
  const releaseFailureActions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:release-failure',
      useService(operation) {
        return operation({
          bindOperation() {
            return Object.freeze({
              async getConversationSession() {
                return projection();
              },
            });
          },
        });
      },
      async release() {
        failureReleaseCount += 1;
        throw new Error('projection_release_failure');
      },
    }),
  };
  const input = {
    config: runtimeConfig(),
    conversation: conversation(),
    signal: new AbortController().signal,
  };
  await assert.rejects(
    withDesktopSessionProjectionAuthorityOperationV2(releaseFailureActions, input, () => {
      throw primary;
    }),
    (error) => error === primary,
  );
  await assert.rejects(
    withDesktopSessionProjectionAuthorityOperationV2(releaseFailureActions, input, () =>
      projection(),
    ),
    /projection_release_failure/u,
  );
  assert.equal(failureReleaseCount, 2);
});

test('HMR pins an in-flight read to old generation and sends the next to new', async () => {
  const lifecycle = [];
  let resolveOld;
  const oldPending = new Promise((resolve) => {
    resolveOld = resolve;
  });
  const serviceFor = (label) =>
    Object.freeze({
      bindOperation() {
        return Object.freeze({
          async getConversationSession() {
            lifecycle.push('read:' + label);
            if (label === 'old') await oldPending;
            return projection({ source: label });
          },
        });
      },
    });
  let currentActions = acceptedActions(serviceFor('old'), 'sha256:old', lifecycle);
  const operations = createDesktopSessionProjectionOperationsV2(() => currentActions);
  const input = {
    config: runtimeConfig(),
    conversation: conversation(),
    signal: new AbortController().signal,
  };
  const oldRead = operations.getConversationSession(input);
  await Promise.resolve();
  currentActions = acceptedActions(serviceFor('next'), 'sha256:next', lifecycle);
  const nextRead = await operations.getConversationSession(input);
  resolveOld();
  const oldReadResult = await oldRead;

  assert.equal(oldReadResult.source, 'old');
  assert.equal(nextRead.source, 'next');
  assert.deepEqual(
    lifecycle.filter((event) => typeof event === 'string'),
    ['read:old', 'read:next'],
  );
  assert.deepEqual(
    lifecycle.filter((event) => event.type === 'release').map((event) => event.digest),
    ['sha256:next', 'sha256:old'],
  );
});
