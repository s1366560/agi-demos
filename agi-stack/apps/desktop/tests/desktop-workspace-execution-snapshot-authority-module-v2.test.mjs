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
  DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_MODULE_REF_V2,
  DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_SERVICE_V2,
  DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_VERSION_V2,
  DesktopWorkspaceExecutionSnapshotAuthorityUnavailableErrorV2,
  applyDesktopWorkspaceExecutionSnapshotAuthorityV2,
  createDesktopWorkspaceExecutionSnapshotOperationsV2,
  desktopWorkspaceExecutionSnapshotAuthorityDefinitionV2,
  withDesktopWorkspaceExecutionSnapshotAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopWorkspaceExecutionSnapshotAuthorityModuleV2.js');
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
const { desktopSessionTimelineAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopSessionTimelineAuthorityModuleV2.js'
);
const { desktopTenantCatalogAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantCatalogAuthorityModuleV2.js'
);
const { desktopTerminalLifecycleAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTerminalLifecycleAuthorityModuleV2.js'
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
    desktopArtifactContentAuthorityDefinitionV2,
    desktopAutomationAuthorityDefinitionV2,
    desktopNewTaskFlowAuthorityDefinitionV2,
    desktopNewThreadCreationAuthorityDefinitionV2,
    desktopProjectSearchAuthorityDefinitionV2,
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
    desktopTenantCatalogAuthorityDefinitionV2,
    desktopWorkspaceContextAuthorityDefinitionV2,
    desktopWorkspaceCatalogAuthorityDefinitionV2,
    desktopWorkspaceExecutionSnapshotAuthorityDefinitionV2,
    desktopWorkspaceMessageCatalogAuthorityDefinitionV2,
  ];
}

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46601',
    apiKey: 'execution-snapshot-session',
    localApiToken: 'execution-snapshot-launch',
    mode: 'local',
    tenantId: 'tenant / one',
    projectId: 'project / one',
    workspaceId: 'workspace / one',
    workspaceRoot: '/workspace',
    ...overrides,
  };
}

function identity(overrides = {}) {
  return {
    tenant_id: 'tenant / one',
    project_id: 'project / one',
    workspace_id: 'workspace / one',
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

test('generated contract exposes one credential-free root execution snapshot Provider', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const bootstrap = loadBootstrap();
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_MODULE_REF_V2
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_MODULE_REF_V2
  );
  const entry = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-workspace-execution-snapshot-authority'
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_SERVICE_V2,
        version: DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_VERSION_V2,
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
    desktopWorkspaceExecutionSnapshotAuthorityDefinitionV2.contractDigest
  );
  assert.equal(catalog.entrypoint, 'applyDesktopWorkspaceExecutionSnapshotAuthorityV2');
  assert.equal(
    catalog.artifact_source,
    'repo+typescript://agi-stack/apps/desktop/src/plugins/' +
      'desktopWorkspaceExecutionSnapshotAuthorityModuleV2.ts'
  );
  assert.equal(entry.module_ref, DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_MODULE_REF_V2);
  assert.equal(entry.parent_entry_id, 'builtin-desktop-renderer-host');
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-client' });
  assert.deepEqual(entry.inject, {});
  assert.equal(entry.enabled, true);
  assert.match(profile, /entry_id: builtin-desktop-workspace-execution-snapshot-authority/u);
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(
      JSON.stringify(value),
      /apiKey|localApiToken|Authorization|execution-snapshot-session/iu
    );
  }
});

test('Loader activates the exact service and disable removes it without fallback', async () => {
  const bootstrap = loadBootstrap();
  const loader = new LoaderV2(rendererDefinitions(), 'desktop-renderer');
  const generation = await loader.stage(bootstrap);
  const service = generation.resolve(
    DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_SERVICE_V2,
    { kind: 'project', tenant_id: 'tenant / one', project_id: 'project / one' },
    { version: DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_VERSION_V2 }
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindOperation']);
  assert.equal('config' in service, false);
  assert.equal('client' in service, false);
  assert.throws(
    () =>
      applyDesktopWorkspaceExecutionSnapshotAuthorityV2(
        { provide: () => assert.fail('invalid config must not provide') },
        { strategy: 'legacy-client' }
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_execution_snapshot_authority_config_invalid'
  );

  const invalid = structuredClone(bootstrap);
  invalid.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-workspace-execution-snapshot-authority'
  ).config.strategy = 'legacy-client';
  await assert.rejects(
    loader.stage(invalid),
    (error) => error instanceof RuntimeV2Error && error.code === 'invalid_module_config'
  );

  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-workspace-execution-snapshot-authority'
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_SERVICE_V2,
        { kind: 'project', tenant_id: 'tenant / one', project_id: 'project / one' },
        { version: DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_VERSION_V2 }
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service'
  );

  const manager = new GenerationManagerV2();
  await manager.publish(generation);
  const wrongDefinitionLoader = new LoaderV2(
    rendererDefinitions().map((definition) =>
      definition.moduleRef === DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_MODULE_REF_V2
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

test('local and vault-bound cloud transports derive exact paths from verified identity', async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const fetchCalls = [];
  const cloudCommands = [];
  globalThis.fetch = async (input, init) => {
    const url = new URL(String(input));
    fetchCalls.push({ url, init });
    return url.pathname.endsWith('/tasks')
      ? json({ tasks: [{ id: 'task-local', workspace_id: 'workspace / one' }] })
      : json({
          workspace_id: 'workspace / one',
          project_id: 'project / one',
          plan: null,
        });
  };
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          cloudCommands.push({ command, args });
          return args.request.path.endsWith('/tasks')
            ? {
                status: 200,
                body: { tasks: [{ id: 'task-cloud', workspace_id: 'workspace / one' }] },
              }
            : {
                status: 200,
                body: {
                  workspace_id: 'workspace / one',
                  project_id: 'project / one',
                  plan: null,
                },
              };
        },
      },
    },
  };

  try {
    const generation = await new LoaderV2(rendererDefinitions(), 'desktop-renderer').stage(
      loadBootstrap()
    );
    const service = generation.resolve(
      DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_SERVICE_V2,
      { kind: 'project', tenant_id: 'tenant / one', project_id: 'project / one' },
      { version: DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_VERSION_V2 }
    );
    const controller = new AbortController();
    const localConfig = runtimeConfig();
    const local = service.bindOperation(localConfig);
    localConfig.apiBaseUrl = 'http://127.0.0.1:46999';
    localConfig.workspaceId = 'mutated-workspace';
    const cloud = service.bindOperation(
      runtimeConfig({
        apiBaseUrl: 'https://cloud.example.test',
        apiKey: '',
        localApiToken: '',
        mode: 'cloud',
      })
    );

    assert.equal((await local.listTasks(identity(), controller.signal))[0].id, 'task-local');
    assert.equal((await local.getPlanSnapshot(identity(), controller.signal)).plan, null);
    assert.equal((await cloud.listTasks(identity(), controller.signal))[0].id, 'task-cloud');
    assert.equal((await cloud.getPlanSnapshot(identity(), controller.signal)).plan, null);
    assert.equal(Object.isFrozen(local), true);
    assert.deepEqual(Object.keys(local), ['listTasks', 'getPlanSnapshot']);
    assert.deepEqual(fetchCalls.map(({ url }) => url.pathname).sort(), [
      '/api/v1/workspaces/workspace%20%2F%20one/plan',
      '/api/v1/workspaces/workspace%20%2F%20one/tasks',
    ]);
    for (const call of fetchCalls) {
      assert.equal(call.url.origin, 'http://127.0.0.1:46601');
      assert.equal(call.init.signal, controller.signal);
      const headers = new Headers(call.init.headers);
      assert.equal(headers.get('Authorization'), 'Bearer execution-snapshot-session');
      assert.equal(headers.get('X-Agistack-Launch'), 'execution-snapshot-launch');
    }
    assert.deepEqual(cloudCommands.map(({ args }) => args.request.path).sort(), [
      '/api/v1/workspaces/workspace%20%2F%20one/plan',
      '/api/v1/workspaces/workspace%20%2F%20one/tasks',
    ]);
    assert.equal(JSON.stringify(cloudCommands).includes('Bearer'), false);
    await generation.dispose();
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test('task and plan operations freeze identity before independent exact project leases', async () => {
  const lifecycle = [];
  const boundConfigs = [];
  const observedIdentities = [];
  const signals = [];
  const service = Object.freeze({
    bindOperation(config) {
      boundConfigs.push(config);
      return Object.freeze({
        async listTasks(operationIdentity, signal) {
          observedIdentities.push(operationIdentity);
          signals.push(signal);
          lifecycle.push('tasks');
          return [{ id: 'task-1', workspace_id: operationIdentity.workspace_id }];
        },
        async getPlanSnapshot(operationIdentity, signal) {
          observedIdentities.push(operationIdentity);
          signals.push(signal);
          lifecycle.push('plan');
          return {
            workspace_id: operationIdentity.workspace_id,
            project_id: operationIdentity.project_id,
            plan: null,
          };
        },
      });
    },
  });
  const actions = acceptedActions(service, 'sha256:generation-1', lifecycle);
  const operations = createDesktopWorkspaceExecutionSnapshotOperationsV2(() => actions);
  const controller = new AbortController();
  const config = runtimeConfig();
  const tasksPending = operations.listTasks({ config, signal: controller.signal });
  const planPending = operations.getPlanSnapshot({ config, signal: controller.signal });
  config.tenantId = 'mutated-tenant';
  config.projectId = 'mutated-project';
  config.workspaceId = 'mutated-workspace';

  const [tasks, plan] = await Promise.all([tasksPending, planPending]);

  assert.equal(tasks[0].id, 'task-1');
  assert.equal(plan.plan, null);
  assert.equal(Object.isFrozen(operations), true);
  assert.equal(Object.isFrozen(boundConfigs[0]), true);
  assert.equal(Object.isFrozen(observedIdentities[0]), true);
  assert.deepEqual(observedIdentities, [identity(), identity()]);
  assert.deepEqual(signals, [controller.signal, controller.signal]);
  assert.deepEqual(
    lifecycle.filter((event) => event.type === 'acquire').map((event) => event.request),
    [
      {
        service: DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_SERVICE_V2,
        version: DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_VERSION_V2,
        scope: {
          kind: 'project',
          tenant_id: 'tenant / one',
          project_id: 'project / one',
        },
      },
      {
        service: DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_SERVICE_V2,
        version: DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_VERSION_V2,
        scope: {
          kind: 'project',
          tenant_id: 'tenant / one',
          project_id: 'project / one',
        },
      },
    ]
  );
  assert.deepEqual(
    lifecycle.filter((event) => typeof event === 'string'),
    ['tasks', 'plan']
  );
  assert.equal(lifecycle.filter((event) => event.type === 'release').length, 2);
});

test('invalid scope, signal and response identity fail closed at their boundaries', async () => {
  let acquisitions = 0;
  const operations = createDesktopWorkspaceExecutionSnapshotOperationsV2(() => ({
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      throw new Error('must_not_acquire');
    },
  }));
  for (const config of [
    runtimeConfig({ tenantId: '' }),
    runtimeConfig({ projectId: ' project-1' }),
    runtimeConfig({ workspaceId: '' }),
  ]) {
    assert.throws(
      () => operations.listTasks({ config }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_execution_snapshot_input_invalid'
    );
  }
  assert.throws(
    () => operations.getPlanSnapshot({ config: runtimeConfig(), signal: {} }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_execution_snapshot_input_invalid'
  );
  assert.equal(acquisitions, 0);

  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return String(input).endsWith('/tasks')
      ? json({ tasks: [{ id: 'cross-scope', workspace_id: 'workspace-other' }] })
      : json({ workspace_id: 'workspace-other', project_id: 'project / one' });
  };
  try {
    const context = {
      provided: null,
      provide(_key, service) {
        this.provided = service;
      },
    };
    applyDesktopWorkspaceExecutionSnapshotAuthorityV2(context, {
      strategy: 'desktop-api-client',
    });
    const authority = context.provided.bindOperation(runtimeConfig());
    await assert.rejects(
      authority.listTasks(identity()),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_execution_snapshot_response_scope_mismatch'
    );
    await assert.rejects(
      authority.getPlanSnapshot(identity()),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_execution_snapshot_response_scope_mismatch'
    );
    assert.throws(
      () => authority.listTasks(identity({ project_id: 'project-other' })),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_execution_snapshot_scope_mismatch'
    );
    assert.equal(calls.length, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('missing or wrong service fails closed and release preserves the primary error', async () => {
  let currentActions = null;
  const operations = createDesktopWorkspaceExecutionSnapshotOperationsV2(() => currentActions);
  assert.throws(
    () => operations.listTasks({ config: runtimeConfig() }),
    (error) =>
      error instanceof DesktopWorkspaceExecutionSnapshotAuthorityUnavailableErrorV2 &&
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
    operations.getPlanSnapshot({ config: runtimeConfig() }),
    (error) =>
      error instanceof DesktopWorkspaceExecutionSnapshotAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_service_resolve_failed' &&
      error.runtimeCode === 'missing_service'
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
    operations.listTasks({ config: runtimeConfig() }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_execution_snapshot_service_invalid'
  );
  assert.equal(wrongReleaseCount, 1);

  const primary = new Error('execution_snapshot_primary_failure');
  let escapedAuthority = null;
  let releaseCount = 0;
  const releaseFailingActions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:accepted',
      useService(operation) {
        return operation({
          bindOperation() {
            return Object.freeze({
              async listTasks() {
                return [];
              },
              async getPlanSnapshot() {
                return {};
              },
            });
          },
        });
      },
      async release() {
        releaseCount += 1;
        throw new Error('execution_snapshot_release_failure');
      },
    }),
  };
  await assert.rejects(
    withDesktopWorkspaceExecutionSnapshotAuthorityOperationV2(
      releaseFailingActions,
      { config: runtimeConfig() },
      (authority) => {
        escapedAuthority = authority;
        throw primary;
      }
    ),
    (error) => error === primary
  );
  assert.throws(
    () => escapedAuthority.listTasks(identity()),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_execution_snapshot_operation_released'
  );
  assert.equal(releaseCount, 1);
  await assert.rejects(
    withDesktopWorkspaceExecutionSnapshotAuthorityOperationV2(
      releaseFailingActions,
      { config: runtimeConfig() },
      () => []
    ),
    /execution_snapshot_release_failure/u
  );
  assert.equal(releaseCount, 2);
});

test('independent operations pin old and next generations through HMR', async () => {
  const lifecycle = [];
  let resolveOld;
  const oldPending = new Promise((resolve) => {
    resolveOld = resolve;
  });
  const serviceFor = (label) =>
    Object.freeze({
      bindOperation() {
        return Object.freeze({
          async listTasks(operationIdentity) {
            lifecycle.push('tasks:' + label);
            if (label === 'old') await oldPending;
            return [{ id: 'task-' + label, workspace_id: operationIdentity.workspace_id }];
          },
          async getPlanSnapshot(operationIdentity) {
            lifecycle.push('plan:' + label);
            return {
              workspace_id: operationIdentity.workspace_id,
              project_id: operationIdentity.project_id,
              plan: label,
            };
          },
        });
      },
    });
  let currentActions = acceptedActions(serviceFor('old'), 'sha256:old', lifecycle);
  const operations = createDesktopWorkspaceExecutionSnapshotOperationsV2(() => currentActions);
  const oldRead = operations.listTasks({ config: runtimeConfig() });
  await Promise.resolve();
  currentActions = acceptedActions(serviceFor('next'), 'sha256:next', lifecycle);
  const nextRead = await operations.getPlanSnapshot({ config: runtimeConfig() });
  resolveOld();
  const oldReadResult = await oldRead;

  assert.equal(oldReadResult[0].id, 'task-old');
  assert.equal(nextRead.plan, 'next');
  assert.deepEqual(
    lifecycle.filter((event) => typeof event === 'string'),
    ['tasks:old', 'plan:next']
  );
  assert.deepEqual(
    lifecycle.filter((event) => event.type === 'release').map((event) => event.digest),
    ['sha256:next', 'sha256:old']
  );
});
