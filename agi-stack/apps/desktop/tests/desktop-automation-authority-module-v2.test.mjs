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
  DESKTOP_AUTOMATION_AUTHORITY_MODULE_REF_V2,
  DESKTOP_AUTOMATION_AUTHORITY_SERVICE_V2,
  DESKTOP_AUTOMATION_AUTHORITY_VERSION_V2,
  DesktopAutomationAuthorityUnavailableErrorV2,
  applyDesktopAutomationAuthorityV2,
  createDesktopAutomationOperationsV2,
  desktopAutomationAuthorityDefinitionV2,
  withDesktopAutomationAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopAutomationAuthorityModuleV2.js');
const { desktopArtifactContentAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopArtifactContentAuthorityModuleV2.js',
);
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
  desktopPluginMarketplaceCatalogDefinitionV2,
  desktopPluginMarketplaceManagementDefinitionV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopPluginMarketplaceAuthorityModulesV2.js');
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
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceExecutionSnapshotAuthorityModuleV2.js',
);
const { desktopWorkspaceMessageCatalogAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceMessageCatalogAuthorityModuleV2.js',
);
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

const REPOSITORY_ROOT = new URL('../../../../', import.meta.url);
const BOOTSTRAP_PATH = new URL('shared/profiles/memstack-default-bootstrap.v2.json', REPOSITORY_ROOT);
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
    apiBaseUrl: 'http://127.0.0.1:46651',
    apiKey: 'automation-session',
    localApiToken: 'automation-launch',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    workspaceRoot: '/workspace',
    ...overrides,
  };
}

function capabilities() {
  return {
    service_version: '0.1.0',
    contract_version: '2.0.0',
    schema_version: 2,
    read: true,
    revision_guarded: true,
    idempotency_guarded: true,
    durable_execution: true,
    supported_read_trigger_kinds: ['manual', 'schedule', 'event'],
    create: { allowed: true },
    edit: { allowed: true },
    toggle: { allowed: true },
    run_now: { allowed: true },
    delete: { allowed: true },
  };
}

function job(overrides = {}) {
  return {
    id: 'automation-1',
    project_id: 'project-1',
    tenant_id: 'tenant-1',
    name: 'Review automation',
    description: null,
    enabled: true,
    delete_after_run: false,
    revision: 7,
    schedule_revision: 2,
    schedule: { kind: 'every', config: { interval_seconds: 60 } },
    payload: { kind: 'agent_turn', config: { message: 'Review changes' } },
    delivery: { kind: 'inbox', config: {} },
    conversation_mode: 'reuse',
    workspace_id: 'workspace-1',
    conversation_id: 'conversation-1',
    timezone: 'UTC',
    stagger_seconds: 0,
    timeout_seconds: 600,
    max_retries: 1,
    state: {},
    created_at: '2026-09-02T00:00:00Z',
    updated_at: '2026-09-02T00:01:00Z',
    ...overrides,
  };
}

function automationRun(overrides = {}) {
  return {
    id: 'run-1',
    job_id: 'automation-1',
    project_id: 'project-1',
    status: 'queued',
    trigger_type: 'manual',
    started_at: '2026-09-02T00:02:00Z',
    result_summary: {},
    ...overrides,
  };
}

function createInput(overrides = {}) {
  return {
    idempotency_key: 'create-automation-1',
    name: 'Review automation',
    schedule: { kind: 'every', config: { interval_seconds: 60 } },
    payload: { kind: 'agent_turn', config: { message: 'Review changes' } },
    ...overrides,
  };
}

function responses() {
  return {
    capabilities: capabilities(),
    jobs: { items: [job()], total: 1 },
    job: job(),
    runs: { items: [automationRun()], total: 1 },
    receipt: {
      receipt_id: 'receipt-1',
      run_id: 'run-1',
      job_id: 'automation-1',
      status: 'queued',
      duplicate: false,
    },
  };
}

function serviceFixture(received = [], result = responses()) {
  return Object.freeze({
    bindOperation(config) {
      received.push({ kind: 'bind', config });
      return Object.freeze({
        async listAutomations(projectId, signal) {
          received.push({ kind: 'listAutomations', projectId, signal });
          return result.jobs;
        },
        async getAutomationCapabilities(projectId, signal) {
          received.push({ kind: 'getAutomationCapabilities', projectId, signal });
          return result.capabilities;
        },
        async createAutomation(input, projectId) {
          received.push({ kind: 'createAutomation', input, projectId });
          return result.job;
        },
        async updateAutomation(automationId, input, projectId) {
          received.push({ kind: 'updateAutomation', automationId, input, projectId });
          return result.job;
        },
        async toggleAutomation(automationId, input, projectId) {
          received.push({ kind: 'toggleAutomation', automationId, input, projectId });
          return result.job;
        },
        async deleteAutomation(automationId, input, projectId) {
          received.push({ kind: 'deleteAutomation', automationId, input, projectId });
        },
        async listAutomationRuns(automationId, projectId, signal) {
          received.push({ kind: 'listAutomationRuns', automationId, projectId, signal });
          return result.runs;
        },
        async runAutomation(automationId, input, projectId) {
          received.push({ kind: 'runAutomation', automationId, input, projectId });
          return result.receipt;
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

test('generated contract exposes one credential-free root Automation Provider', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const bootstrap = loadBootstrap();
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_AUTOMATION_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_AUTOMATION_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-automation-authority',
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_AUTOMATION_AUTHORITY_SERVICE_V2,
        version: DESKTOP_AUTOMATION_AUTHORITY_VERSION_V2,
      },
    ],
    requires: [],
  });
  assert.deepEqual(module.contract.events, { emits: [], handles: [] });
  assert.equal(module.contract.config_schema.additionalProperties, false);
  assert.deepEqual(module.contract.config_schema.required, ['strategy']);
  assert.equal(module.contract.config_schema.properties.strategy.const, 'desktop-api-client');
  assert.equal(module.contract_digest, catalog.contract_digest);
  assert.equal(module.contract_digest, desktopAutomationAuthorityDefinitionV2.contractDigest);
  assert.equal(catalog.entrypoint, 'applyDesktopAutomationAuthorityV2');
  assert.equal(
    catalog.artifact_source,
    'repo+typescript://agi-stack/apps/desktop/src/plugins/' +
      'desktopAutomationAuthorityModuleV2.ts',
  );
  assert.equal(entry.module_ref, DESKTOP_AUTOMATION_AUTHORITY_MODULE_REF_V2);
  assert.equal(entry.parent_entry_id, 'builtin-desktop-renderer-host');
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-client' });
  assert.deepEqual(entry.inject, {});
  assert.equal(entry.enabled, true);
  assert.match(profile, /entry_id: builtin-desktop-automation-authority/u);
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(JSON.stringify(value), /apiKey|localApiToken|Authorization/iu);
  }
});

test('Loader activates the exact service and Profile disable removes it without fallback', async () => {
  const bootstrap = loadBootstrap();
  const loader = new LoaderV2(rendererDefinitions(), 'desktop-renderer');
  const generation = await loader.stage(bootstrap);
  const service = generation.resolve(
    DESKTOP_AUTOMATION_AUTHORITY_SERVICE_V2,
    { kind: 'root' },
    { version: DESKTOP_AUTOMATION_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindOperation']);
  assert.equal('config' in service, false);
  assert.equal('client' in service, false);
  assert.throws(
    () =>
      applyDesktopAutomationAuthorityV2(
        { provide: () => assert.fail('invalid config must not provide a service') },
        { strategy: 'legacy-client' },
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_automation_authority_config_invalid',
  );

  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-automation-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_AUTOMATION_AUTHORITY_SERVICE_V2,
        { kind: 'project', tenant_id: 'tenant-1', project_id: 'project-1' },
        { version: DESKTOP_AUTOMATION_AUTHORITY_VERSION_V2 },
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service',
  );

  const manager = new GenerationManagerV2();
  await manager.publish(generation);
  const wrongDefinitionLoader = new LoaderV2(
    rendererDefinitions().map((definition) =>
      definition.moduleRef === DESKTOP_AUTOMATION_AUTHORITY_MODULE_REF_V2
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

test('local service owns all eight authenticated Automation transport contracts', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const result = responses();
  globalThis.fetch = async (input, init) => {
    const url = new URL(String(input));
    const method = init.method ?? 'GET';
    calls.push({ url, init, method });
    if (url.pathname.endsWith('/capabilities')) return json(result.capabilities);
    if (url.pathname.endsWith('/runs')) return json(result.runs);
    if (url.pathname.endsWith('/run')) return json(result.receipt, 202);
    if (url.pathname.endsWith('/toggle')) return json(result.job);
    if (url.pathname.endsWith('/automation-1') && method === 'DELETE') {
      return new Response(null, { status: 204 });
    }
    if (url.pathname.endsWith('/automation-1')) return json(result.job);
    if (url.pathname.endsWith('/cron-jobs') && method === 'POST') return json(result.job, 201);
    if (url.pathname.endsWith('/cron-jobs')) return json(result.jobs);
    return json({ detail: `unexpected route ${url.pathname}` }, 404);
  };

  try {
    const generation = await new LoaderV2(rendererDefinitions(), 'desktop-renderer').stage(
      loadBootstrap(),
    );
    const service = generation.resolve(
      DESKTOP_AUTOMATION_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: DESKTOP_AUTOMATION_AUTHORITY_VERSION_V2 },
    );
    const client = service.bindOperation(runtimeConfig());
    const controller = new AbortController();
    assert.deepEqual(await client.listAutomations(undefined, controller.signal), result.jobs);
    assert.deepEqual(
      await client.getAutomationCapabilities(undefined, controller.signal),
      result.capabilities,
    );
    assert.deepEqual(await client.createAutomation(createInput()), result.job);
    assert.deepEqual(
      await client.updateAutomation('automation-1', {
        idempotency_key: 'update-automation-1',
        expected_revision: 7,
        name: 'Updated automation',
      }),
      result.job,
    );
    assert.deepEqual(
      await client.toggleAutomation('automation-1', {
        idempotency_key: 'toggle-automation-1',
        expected_revision: 7,
        enabled: false,
      }),
      result.job,
    );
    await client.deleteAutomation('automation-1', {
      idempotency_key: 'delete-automation-1',
      expected_revision: 7,
    });
    assert.deepEqual(
      await client.listAutomationRuns('automation-1', undefined, controller.signal),
      result.runs,
    );
    assert.deepEqual(
      await client.runAutomation('automation-1', {
        idempotency_key: 'run-automation-1',
        expected_revision: 7,
        conversation_id: 'conversation-1',
      }),
      result.receipt,
    );

    assert.equal(calls.length, 8);
    for (const call of calls) {
      const headers = new Headers(call.init.headers);
      assert.equal(headers.get('Authorization'), 'Bearer automation-session');
      assert.equal(headers.get('X-Agistack-Launch'), 'automation-launch');
    }
    assert.deepEqual(
      calls.map(({ url, method }) => [url.pathname, method]),
      [
        ['/api/v1/projects/project-1/cron-jobs', 'GET'],
        ['/api/v1/projects/project-1/cron-jobs/capabilities', 'GET'],
        ['/api/v1/projects/project-1/cron-jobs', 'POST'],
        ['/api/v1/projects/project-1/cron-jobs/automation-1', 'PATCH'],
        ['/api/v1/projects/project-1/cron-jobs/automation-1/toggle', 'POST'],
        ['/api/v1/projects/project-1/cron-jobs/automation-1', 'DELETE'],
        ['/api/v1/projects/project-1/cron-jobs/automation-1/runs', 'GET'],
        ['/api/v1/projects/project-1/cron-jobs/automation-1/run', 'POST'],
      ],
    );
    assert.equal(JSON.parse(String(calls[2].init.body)).workspace_id, 'workspace-1');
    assert.equal(JSON.parse(String(calls[7].init.body)).contract_version, 2);
    await generation.dispose();
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Cloud service uses the vault broker for read, mutation and run without credentials', async () => {
  const originalWindow = globalThis.window;
  const calls = [];
  const result = responses();
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          calls.push({ command, args });
          const path = args.request.path;
          if (path.endsWith('/run')) return { status: 202, body: result.receipt };
          if (path.includes('/cron-jobs?')) return { status: 200, body: result.jobs };
          if (path.endsWith('/cron-jobs')) {
            return args.request.method === 'POST'
              ? { status: 201, body: result.job }
              : { status: 200, body: result.jobs };
          }
          return { status: 404, body: { detail: `unexpected route ${path}` } };
        },
      },
    },
  };

  try {
    const generation = await new LoaderV2(rendererDefinitions(), 'desktop-renderer').stage(
      loadBootstrap(),
    );
    const service = generation.resolve(
      DESKTOP_AUTOMATION_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: DESKTOP_AUTOMATION_AUTHORITY_VERSION_V2 },
    );
    const client = service.bindOperation(
      runtimeConfig({ mode: 'cloud', apiKey: '', localApiToken: '' }),
    );
    await client.listAutomations();
    await client.createAutomation(createInput());
    await client.runAutomation('automation-1', {
      idempotency_key: 'run-cloud-1',
      expected_revision: 7,
    });

    assert.deepEqual(calls.map(({ command }) => command), [
      'cloud_request',
      'cloud_request',
      'cloud_request',
    ]);
    assert.deepEqual(calls.map(({ args }) => args.request.method), ['GET', 'POST', 'POST']);
    assert.equal(calls[1].args.request.body.workspace_id, undefined);
    assert.equal(calls[2].args.request.body.contract_version, 2);
    assert.equal(JSON.stringify(calls).includes('automation-session'), false);
    assert.equal(JSON.stringify(calls).includes('automation-launch'), false);
    await generation.dispose();
  } finally {
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test('every facade call freezes config and input before one exact project lease', async () => {
  const lifecycle = [];
  const received = [];
  const config = runtimeConfig();
  const actions = acceptedActions(serviceFixture(received), 'sha256:generation-1', lifecycle);
  const operations = createDesktopAutomationOperationsV2(() => actions, () => config);
  const controller = new AbortController();
  const create = createInput();
  const update = {
    idempotency_key: 'update-automation-1',
    expected_revision: 7,
    name: 'Updated automation',
  };
  const pending = [
    operations.listAutomations(undefined, controller.signal),
    operations.getAutomationCapabilities(undefined, controller.signal),
    operations.createAutomation(create),
    operations.updateAutomation('automation-1', update),
    operations.toggleAutomation('automation-1', {
      idempotency_key: 'toggle-automation-1', expected_revision: 7, enabled: false,
    }),
    operations.deleteAutomation('automation-1', {
      idempotency_key: 'delete-automation-1', expected_revision: 7,
    }),
    operations.listAutomationRuns('automation-1', undefined, controller.signal),
    operations.runAutomation('automation-1', {
      idempotency_key: 'run-automation-1', expected_revision: 7,
    }),
  ];
  config.tenantId = 'mutated-tenant';
  config.projectId = 'mutated-project';
  create.name = 'mutated';
  update.name = 'mutated';
  await Promise.all(pending);

  assert.equal(Object.isFrozen(operations), true);
  const bindings = received.filter(({ kind }) => kind === 'bind');
  assert.equal(bindings.length, 8);
  for (const binding of bindings) {
    assert.equal(Object.isFrozen(binding.config), true);
    assert.equal(binding.config.tenantId, 'tenant-1');
    assert.equal(binding.config.projectId, 'project-1');
  }
  assert.equal(received.find(({ kind }) => kind === 'createAutomation').input.name, 'Review automation');
  assert.equal(received.find(({ kind }) => kind === 'updateAutomation').input.name, 'Updated automation');
  assert.deepEqual(
    lifecycle.filter(({ type }) => type === 'acquire').map(({ request }) => request.scope),
    Array.from({ length: 8 }, () => ({
      kind: 'project', tenant_id: 'tenant-1', project_id: 'project-1',
    })),
  );
  assert.equal(lifecycle.filter(({ type }) => type === 'release').length, 8);
});

test('malformed scope, request and response fail closed at the V2 boundary', async () => {
  let acquisitions = 0;
  const neverActions = {
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      throw new Error('unexpected_acquire');
    },
  };
  let config = runtimeConfig({ tenantId: '' });
  let operations = createDesktopAutomationOperationsV2(() => neverActions, () => config);
  await assert.rejects(
    operations.listAutomations(),
    (error) => error instanceof RuntimeV2Error && error.code === 'desktop_automation_input_invalid',
  );
  config = runtimeConfig();
  operations = createDesktopAutomationOperationsV2(() => neverActions, () => config);
  await assert.rejects(
    operations.createAutomation(createInput({ idempotency_key: 'bad key' })),
    (error) => error instanceof RuntimeV2Error && error.code === 'desktop_automation_input_invalid',
  );
  await assert.rejects(
    operations.runAutomation(
      'automation-1',
      { idempotency_key: 'run-automation-1', expected_revision: 7 },
      'other-project',
    ),
    (error) => error instanceof RuntimeV2Error && error.code === 'desktop_automation_scope_mismatch',
  );
  assert.equal(acquisitions, 0);

  const malformed = responses();
  malformed.job = job({ tenant_id: 'other-tenant' });
  const malformedOperations = createDesktopAutomationOperationsV2(
    () => acceptedActions(serviceFixture([], malformed), 'sha256:malformed'),
    () => runtimeConfig(),
  );
  await assert.rejects(
    malformedOperations.createAutomation(createInput()),
    (error) => error instanceof RuntimeV2Error && error.code === 'desktop_automation_response_invalid',
  );
});

test('missing service is structured and an escaped authority is revoked', async () => {
  const unavailable = createDesktopAutomationOperationsV2(() => null, () => runtimeConfig());
  await assert.rejects(
    unavailable.listAutomations(),
    (error) =>
      error instanceof DesktopAutomationAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
  const rejected = createDesktopAutomationOperationsV2(
    () => ({
      acquireServiceOperationLease: async () => ({
        status: 'rejected',
        reasonCode: 'desktop_renderer_service_resolve_failed',
        runtimeCode: 'missing_service',
      }),
    }),
    () => runtimeConfig(),
  );
  await assert.rejects(
    rejected.listAutomations(),
    (error) =>
      error instanceof DesktopAutomationAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_service_resolve_failed' &&
      error.runtimeCode === 'missing_service',
  );

  let escaped;
  await withDesktopAutomationAuthorityOperationV2(
    acceptedActions(serviceFixture(), 'sha256:revocation'),
    { kind: 'list-automations', config: runtimeConfig() },
    (authority) => {
      escaped = authority;
      return 'complete';
    },
  );
  assert.throws(
    () => escaped.listAutomations(),
    (error) =>
      error instanceof RuntimeV2Error && error.code === 'desktop_automation_operation_released',
  );
});

test('operation failure outranks release failure and successful release failure propagates', async () => {
  let failOperation = true;
  const fixture = serviceFixture();
  const service = {
    bindOperation(config) {
      const authority = fixture.bindOperation(config);
      return {
        ...authority,
        listAutomations: async () => {
          if (failOperation) throw new Error('automation_operation_failed');
          return responses().jobs;
        },
      };
    },
  };
  const actions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:release-failure',
      useService: (operation) => operation(service),
      release: async () => {
        throw new Error('automation_release_failed');
      },
    }),
  };
  const operations = createDesktopAutomationOperationsV2(() => actions, () => runtimeConfig());

  await assert.rejects(operations.listAutomations(), /automation_operation_failed/u);
  failOperation = false;
  await assert.rejects(operations.listAutomations(), /automation_release_failed/u);
});

test('HMR pins an in-flight Automation call and routes the next call to the new generation', async () => {
  const lifecycle = [];
  let resolveOld;
  const oldResponse = new Promise((resolve) => {
    resolveOld = resolve;
  });
  const oldFixture = serviceFixture();
  const oldService = {
    bindOperation(config) {
      return {
        ...oldFixture.bindOperation(config),
        listAutomations: async () => oldResponse,
      };
    },
  };
  const nextResponses = responses();
  nextResponses.jobs = { items: [job({ id: 'automation-new' })], total: 1 };
  let actions = acceptedActions(oldService, 'sha256:old', lifecycle);
  const operations = createDesktopAutomationOperationsV2(() => actions, () => runtimeConfig());
  const oldPending = operations.listAutomations();
  actions = acceptedActions(serviceFixture([], nextResponses), 'sha256:new', lifecycle);
  const next = await operations.listAutomations();
  resolveOld({ items: [job({ id: 'automation-old' })], total: 1 });
  const old = await oldPending;

  assert.equal(next.items[0].id, 'automation-new');
  assert.equal(old.items[0].id, 'automation-old');
  assert.deepEqual(
    lifecycle.map(({ type, digest }) => `${type}:${digest}`),
    [
      'acquire:sha256:old',
      'acquire:sha256:new',
      'release:sha256:new',
      'release:sha256:old',
    ],
  );
});
