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
  DESKTOP_TERMINAL_LIFECYCLE_AUTHORITY_MODULE_REF_V2,
  DESKTOP_TERMINAL_LIFECYCLE_AUTHORITY_SERVICE_V2,
  DESKTOP_TERMINAL_LIFECYCLE_AUTHORITY_VERSION_V2,
  DesktopTerminalLifecycleAuthorityUnavailableErrorV2,
  acquireDesktopTerminalLifecycleAuthorityV2,
  createDesktopTerminalLifecycleAuthorityServiceV2,
  desktopTerminalLifecycleAuthorityDefinitionV2,
} = require(
  `${COMPILED_ROOT}/src/plugins/desktopTerminalLifecycleAuthorityModuleV2.js`,
);
const {
  desktopPluginMarketplaceCatalogDefinitionV2,
  desktopPluginMarketplaceManagementDefinitionV2,
} = require(`${COMPILED_ROOT}/src/plugins/desktopPluginMarketplaceAuthorityModulesV2.js`);
const { desktopConversationConfigAuthorityDefinitionV2 } = require(
  `${COMPILED_ROOT}/src/plugins/desktopConversationConfigAuthorityModuleV2.js`,
);
const { desktopConversationLifecycleAuthorityDefinitionV2 } = require(
  `${COMPILED_ROOT}/src/plugins/desktopConversationLifecycleAuthorityModuleV2.js`,
);
const { desktopHitlResponseAuthorityDefinitionV2 } = require(
  `${COMPILED_ROOT}/src/plugins/desktopHitlResponseAuthorityModuleV2.js`,
);
const { desktopMyWorkAuthorityDefinitionV2 } = require(
  `${COMPILED_ROOT}/src/plugins/desktopMyWorkAuthorityModuleV2.js`,
);
const { desktopSessionProjectionAuthorityDefinitionV2 } = require(
  `${COMPILED_ROOT}/src/plugins/desktopSessionProjectionAuthorityModuleV2.js`,
);
const { desktopSessionRunChangesAuthorityDefinitionV2 } = require(
  `${COMPILED_ROOT}/src/plugins/desktopSessionRunChangesAuthorityModuleV2.js`,
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
const { desktopWorkspaceContextAuthorityDefinitionV2 } = require(
  `${COMPILED_ROOT}/src/plugins/desktopWorkspaceContextAuthorityModuleV2.js`,
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
    apiBaseUrl: 'http://127.0.0.1:46301',
    apiKey: 'terminal-session-credential',
    localApiToken: 'terminal-launch-capability',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    workspaceRoot: '/workspace',
    ...overrides,
  };
}

function runAuthority(overrides = {}) {
  return {
    id: 'run-1',
    conversation_id: 'conversation-1',
    project_id: 'project-1',
    plan_version_id: null,
    idempotency_key: 'run-idempotency-1',
    message_id: 'message-1',
    request_message: 'Open a terminal',
    status: 'running',
    revision: 7,
    created_at: '2026-08-31T01:00:00.000Z',
    updated_at: '2026-08-31T01:01:00.000Z',
    authorization_snapshot: {},
    environment: {
      id: 'environment-1',
      kind: 'local',
      label: 'Workspace',
      workspace_path: '/workspace',
      created_at: '2026-08-31T01:00:00.000Z',
    },
    ...overrides,
  };
}

function terminalSession(overrides = {}) {
  return {
    contract_version: 2,
    session_id: 'terminal-session-1',
    resume_token: 'terminal-resume-1',
    project_id: 'project-1',
    conversation_id: 'conversation-1',
    run_id: 'run-1',
    run_revision: 7,
    environment_id: 'environment-1',
    cwd: '/workspace',
    created_at: new Date(Date.now() - 1_000).toISOString(),
    expires_at: new Date(Date.now() + 300_000).toISOString(),
    resumable: true,
    ...overrides,
  };
}

function localTerminal(overrides = {}) {
  return {
    success: true,
    session_id: 'local-terminal-1',
    project_id: 'project-1',
    conversation_id: 'conversation-1',
    run_id: 'run-1',
    run_revision: 7,
    environment_id: 'environment-1',
    cwd: '/workspace',
    ...overrides,
  };
}

function availableCapabilities() {
  return {
    terminal_interactive: {
      availability: 'available',
      contract_version: 1,
      reason_code: null,
    },
    terminal_resume: {
      availability: 'available',
      contract_version: 2,
      reason_code: null,
    },
    files: {
      availability: 'unavailable',
      contract_version: 1,
      reason_code: 'not-used',
    },
    kasm_vnc: {
      availability: 'unavailable',
      contract_version: 1,
      reason_code: 'not-used',
    },
  };
}

function bindingInput(overrides = {}) {
  return {
    config: runtimeConfig(),
    run: runAuthority(),
    capabilities: availableCapabilities(),
    ...overrides,
  };
}

function acceptedActions(service, digest = 'sha256:terminal-generation-1', lifecycle = []) {
  return {
    acquireServiceOperationLease: async (request) => {
      lifecycle.push({ type: 'acquire', request });
      let released = false;
      return {
        status: 'accepted',
        digest,
        useService(operation) {
          if (released) throw new Error('lease released');
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

test('generated manifest, catalog and Profile expose one credential-free root Provider', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const bootstrap = loadBootstrap();
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_TERMINAL_LIFECYCLE_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_TERMINAL_LIFECYCLE_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-terminal-lifecycle-authority',
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_TERMINAL_LIFECYCLE_AUTHORITY_SERVICE_V2,
        version: DESKTOP_TERMINAL_LIFECYCLE_AUTHORITY_VERSION_V2,
      },
    ],
    requires: [],
  });
  assert.deepEqual(module.contract.events, { emits: [], handles: [] });
  assert.equal(module.contract.config_schema.additionalProperties, false);
  assert.deepEqual(module.contract.config_schema.required, ['strategy']);
  assert.equal(module.contract.config_schema.properties.strategy.const, 'desktop-terminal-v2');
  assert.equal(module.contract_digest, catalog.contract_digest);
  assert.equal(
    module.contract_digest,
    desktopTerminalLifecycleAuthorityDefinitionV2.contractDigest,
  );
  assert.equal(catalog.entrypoint, 'applyDesktopTerminalLifecycleAuthorityV2');
  assert.equal(
    catalog.artifact_source,
    'repo+typescript://agi-stack/apps/desktop/src/plugins/' +
      'desktopTerminalLifecycleAuthorityModuleV2.ts',
  );
  assert.equal(entry.module_ref, DESKTOP_TERMINAL_LIFECYCLE_AUTHORITY_MODULE_REF_V2);
  assert.equal(entry.parent_entry_id, 'builtin-desktop-renderer-host');
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-terminal-v2' });
  assert.deepEqual(entry.inject, {});
  assert.equal(entry.enabled, true);
  assert.match(profile, /entry_id: builtin-desktop-terminal-lifecycle-authority/u);
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(
      JSON.stringify(value),
      /apiKey|localApiToken|Authorization|launch-capability|resume-token/iu,
    );
  }
});

test('Loader activates the exact service and preserves last-good on missing or bad definitions', async () => {
  const bootstrap = loadBootstrap();
  const loader = new LoaderV2(rendererDefinitions(), 'desktop-renderer');
  const generation = await loader.stage(bootstrap);
  const sessionScope = {
    kind: 'session',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    session_id: 'conversation-1',
  };
  const service = generation.resolve(
    DESKTOP_TERMINAL_LIFECYCLE_AUTHORITY_SERVICE_V2,
    sessionScope,
    { version: DESKTOP_TERMINAL_LIFECYCLE_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindLifecycle']);
  assert.equal('config' in service, false);
  assert.equal('client' in service, false);
  assert.equal('credential' in service, false);

  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-terminal-lifecycle-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_TERMINAL_LIFECYCLE_AUTHORITY_SERVICE_V2,
        sessionScope,
        { version: DESKTOP_TERMINAL_LIFECYCLE_AUTHORITY_VERSION_V2 },
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service',
  );

  const manager = new GenerationManagerV2();
  await manager.publish(generation);
  const wrongLoader = new LoaderV2(
    rendererDefinitions().map((definition) =>
      definition.moduleRef === DESKTOP_TERMINAL_LIFECYCLE_AUTHORITY_MODULE_REF_V2
        ? { ...definition, contractDigest: `sha256:${'0'.repeat(64)}` }
        : definition,
    ),
    'desktop-renderer',
  );
  await assert.rejects(
    wrongLoader.stage(bootstrap),
    (error) => error instanceof RuntimeV2Error && error.code === 'contract_digest_mismatch',
  );
  assert.equal(manager.current, generation);
  await disabledGeneration.dispose();
  await manager.close();
});

test('local lifecycle holds one session lease across cookie, start, socket and release', async () => {
  const lifecycle = [];
  const port = {
    async seedLocalProxyAuthCookie({ config }) {
      lifecycle.push(`cookie:${config.apiBaseUrl}:${config.apiKey}`);
    },
    async createLocalSession({ config, run }) {
      lifecycle.push(`start:${config.projectId}:${run.id}:${run.revision}`);
      return localTerminal();
    },
    openLocalSocket({ config, terminal, afterSequence }) {
      lifecycle.push(`socket:${config.localApiToken}:${terminal.session_id}:${afterSequence}`);
      return { close() { lifecycle.push('socket-close'); } };
    },
    async createCloudSession() {
      throw new Error('cloud create must not run');
    },
    async resumeCloudSession() {
      throw new Error('cloud resume must not run');
    },
    openCloudSocket() {
      throw new Error('cloud socket must not run');
    },
  };
  const service = createDesktopTerminalLifecycleAuthorityServiceV2(port);
  const config = runtimeConfig();
  const run = runAuthority();
  const handle = await acquireDesktopTerminalLifecycleAuthorityV2(
    acceptedActions(service, 'sha256:local-generation', lifecycle),
    { config, run, capabilities: null },
  );

  config.apiBaseUrl = 'http://mutated.invalid';
  config.apiKey = 'mutated-credential';
  config.localApiToken = 'mutated-launch';
  config.projectId = 'mutated-project';
  run.id = 'mutated-run';
  run.revision = 99;

  const started = await handle.start();
  const socket = await handle.openSocket({ reconnect: false, afterSequence: 0 });
  assert.equal(handle.digest, 'sha256:local-generation');
  assert.equal(handle.mode, 'local');
  assert.equal(started.session, null);
  assert.equal(started.terminal.session_id, 'local-terminal-1');
  assert.equal(handle.currentSession(), null);
  assert.deepEqual(lifecycle.slice(1, 4), [
    'cookie:http://127.0.0.1:46301:terminal-session-credential',
    'start:project-1:run-1:7',
    'socket:terminal-launch-capability:local-terminal-1:0',
  ]);
  assert.deepEqual(lifecycle[0].request, {
    service: DESKTOP_TERMINAL_LIFECYCLE_AUTHORITY_SERVICE_V2,
    version: DESKTOP_TERMINAL_LIFECYCLE_AUTHORITY_VERSION_V2,
    scope: {
      kind: 'session',
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      session_id: 'conversation-1',
    },
  });

  socket.close();
  await Promise.all([handle.release(), handle.release()]);
  assert.equal(lifecycle.filter((event) => event.type === 'release').length, 1);
  await assert.rejects(handle.start(), (error) => {
    return error instanceof RuntimeV2Error && error.code === 'desktop_terminal_lifecycle_released';
  });
  await assert.rejects(handle.openSocket({ reconnect: false, afterSequence: 0 }), (error) => {
    return error instanceof RuntimeV2Error && error.code === 'desktop_terminal_lifecycle_released';
  });

  const mismatchedService = createDesktopTerminalLifecycleAuthorityServiceV2({
    ...port,
    async createLocalSession() {
      return localTerminal({ cwd: '/wrong-workspace' });
    },
  });
  const mismatched = await acquireDesktopTerminalLifecycleAuthorityV2(
    acceptedActions(mismatchedService),
    { config: runtimeConfig(), run: runAuthority(), capabilities: null },
  );
  await assert.rejects(
    mismatched.start(),
    (error) =>
      error instanceof RuntimeV2Error && error.code === 'desktop_terminal_authority_mismatch',
  );
  await mismatched.release();
});

test('cloud lifecycle resumes before reconnect and validates complete run authority', async () => {
  const lifecycle = [];
  const created = terminalSession();
  const resumed = terminalSession({
    resume_token: 'terminal-resume-2',
    expires_at: new Date(Date.now() + 600_000).toISOString(),
  });
  const port = {
    async seedLocalProxyAuthCookie() {
      throw new Error('local cookie must not run');
    },
    async createLocalSession() {
      throw new Error('local create must not run');
    },
    openLocalSocket() {
      throw new Error('local socket must not run');
    },
    async createCloudSession({ config, run }) {
      lifecycle.push(`create:${config.projectId}:${run.id}:${run.revision}`);
      return created;
    },
    async resumeCloudSession({ config, session }) {
      lifecycle.push(`resume:${config.projectId}:${session.session_id}:${session.resume_token}`);
      return resumed;
    },
    openCloudSocket({ config, session, afterSequence }) {
      lifecycle.push(`socket:${config.tenantId}:${session.resume_token}:${afterSequence}`);
      return { close() {} };
    },
  };
  const service = createDesktopTerminalLifecycleAuthorityServiceV2(port);
  const handle = await acquireDesktopTerminalLifecycleAuthorityV2(
    acceptedActions(service, 'sha256:cloud-generation', lifecycle),
    bindingInput({ config: runtimeConfig({ mode: 'cloud', localApiToken: '' }) }),
  );

  const started = await handle.start();
  await handle.openSocket({ reconnect: false, afterSequence: 0 });
  await handle.openSocket({ reconnect: true, afterSequence: 41 });
  assert.equal(started.session.resume_token, 'terminal-resume-1');
  assert.equal(started.terminal.session_id, 'terminal-session-1');
  assert.equal(handle.currentSession().resume_token, 'terminal-resume-2');
  assert.deepEqual(lifecycle.slice(1), [
    'create:project-1:run-1:7',
    'socket:tenant-1:terminal-resume-1:0',
    'resume:project-1:terminal-session-1:terminal-resume-1',
    'socket:tenant-1:terminal-resume-2:41',
  ]);
  await handle.release();

  const mismatchedService = createDesktopTerminalLifecycleAuthorityServiceV2({
    ...port,
    async createCloudSession() {
      return terminalSession({ conversation_id: 'wrong-conversation' });
    },
  });
  const mismatched = await acquireDesktopTerminalLifecycleAuthorityV2(
    acceptedActions(mismatchedService),
    bindingInput({ config: runtimeConfig({ mode: 'cloud', localApiToken: '' }) }),
  );
  await assert.rejects(
    mismatched.start(),
    (error) =>
      error instanceof RuntimeV2Error && error.code === 'desktop_terminal_authority_mismatch',
  );
  await mismatched.release();
});

test('old and new generation handles never mix and each releases exactly once', async () => {
  const lifecycle = [];
  const serviceFor = (label) =>
    createDesktopTerminalLifecycleAuthorityServiceV2({
      async seedLocalProxyAuthCookie() {},
      async createLocalSession() {
        return localTerminal({ session_id: `terminal-${label}` });
      },
      openLocalSocket() {
        lifecycle.push(`socket:${label}`);
        return { close() {} };
      },
      async createCloudSession() {
        throw new Error('cloud create must not run');
      },
      async resumeCloudSession() {
        throw new Error('cloud resume must not run');
      },
      openCloudSocket() {
        throw new Error('cloud socket must not run');
      },
    });
  const oldHandle = await acquireDesktopTerminalLifecycleAuthorityV2(
    acceptedActions(serviceFor('old'), 'sha256:old', lifecycle),
    bindingInput({ capabilities: null }),
  );
  await oldHandle.start();
  const nextHandle = await acquireDesktopTerminalLifecycleAuthorityV2(
    acceptedActions(serviceFor('next'), 'sha256:next', lifecycle),
    bindingInput({ capabilities: null }),
  );
  await nextHandle.start();

  await oldHandle.openSocket({ reconnect: false, afterSequence: 0 });
  await nextHandle.openSocket({ reconnect: false, afterSequence: 0 });
  await Promise.all([
    oldHandle.release(),
    oldHandle.release(),
    nextHandle.release(),
    nextHandle.release(),
  ]);
  assert.deepEqual(
    lifecycle.filter((event) => typeof event === 'string'),
    ['socket:old', 'socket:next'],
  );
  assert.deepEqual(
    lifecycle.filter((event) => event.type === 'release').map((event) => event.digest),
    ['sha256:old', 'sha256:next'],
  );
});

test('missing service fails closed and bind failures preserve the primary error', async () => {
  await assert.rejects(
    acquireDesktopTerminalLifecycleAuthorityV2(
      {
        acquireServiceOperationLease: async () => ({
          status: 'rejected',
          reasonCode: 'desktop_renderer_service_resolve_failed',
          runtimeCode: 'missing_service',
        }),
      },
      bindingInput(),
    ),
    (error) =>
      error instanceof DesktopTerminalLifecycleAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_service_resolve_failed' &&
      error.runtimeCode === 'missing_service',
  );

  let releases = 0;
  const primary = new Error('bind-primary');
  await assert.rejects(
    acquireDesktopTerminalLifecycleAuthorityV2(
      {
        acquireServiceOperationLease: async () => ({
          status: 'accepted',
          digest: 'sha256:bind-failure',
          useService() {
            throw primary;
          },
          async release() {
            releases += 1;
            throw new Error('release-secondary');
          },
        }),
      },
      bindingInput(),
    ),
    (error) => error === primary,
  );
  assert.equal(releases, 1);
});

test('production wiring removes raw transport choice from App and useTerminalProxy', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
  const hook = readFileSync(new URL('../src/hooks/useTerminalProxy.ts', import.meta.url), 'utf8');
  const generation = readFileSync(
    new URL('../src/plugins/useDesktopPluginGenerationV2.ts', import.meta.url),
    'utf8',
  );

  for (const pattern of [
    /api\.seedProxyAuthCookie\(/u,
    /api\.startTerminal\(/u,
    /api\.terminalProxyUrl\(/u,
    /runtimeClient\.createTerminalSession\(/u,
    /terminalSessionV2SocketUrl\(/u,
  ]) {
    assert.doesNotMatch(app, pattern);
  }
  assert.match(app, /acquireDesktopTerminalLifecycleAuthorityV2/u);
  assert.match(app, /useTerminalProxy\(terminalLifecycle/u);
  assert.doesNotMatch(hook, /desktopApiCredential|desktopLaunchCapability/u);
  assert.doesNotMatch(hook, /desktopCloudSocketTransport|createCloudSocketBridge/u);
  assert.doesNotMatch(hook, /new WebSocket|openTerminalSocket\(/u);
  assert.match(hook, /lifecycle\.openSocket/u);
  assert.match(
    hook,
    /controller\.abort\(\);[\s\S]*socket\?\.close\(\);[\s\S]*lifecycle\.release\(\)/u,
  );
  assert.match(generation, /desktopTerminalLifecycleAuthorityDefinitionV2/u);
});
