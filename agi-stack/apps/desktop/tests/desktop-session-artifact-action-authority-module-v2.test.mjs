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
  DESKTOP_SESSION_ARTIFACT_ACTION_AUTHORITY_MODULE_REF_V2,
  DESKTOP_SESSION_ARTIFACT_ACTION_AUTHORITY_SERVICE_V2,
  DESKTOP_SESSION_ARTIFACT_ACTION_AUTHORITY_VERSION_V2,
  applyDesktopSessionArtifactActionAuthorityV2,
  desktopSessionArtifactActionAuthorityDefinitionV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopSessionArtifactActionAuthorityModuleV2.js');
const authorityModules = [
  'desktopArtifactContentAuthorityModuleV2',
  'desktopAutomationAuthorityModuleV2',
  'desktopConversationConfigAuthorityModuleV2',
  'desktopConversationLifecycleAuthorityModuleV2',
  'desktopHitlResponseAuthorityModuleV2',
  'desktopMyWorkAuthorityModuleV2',
  'desktopNewTaskFlowAuthorityModuleV2',
  'desktopNewThreadCreationAuthorityModuleV2',
  'desktopProjectSearchAuthorityModuleV2',
  'desktopSessionProjectionAuthorityModuleV2',
  'desktopSessionRunControlAuthorityModuleV2',
  'desktopSessionRunChangesAuthorityModuleV2',
  'desktopSessionTimelineAuthorityModuleV2',
  'desktopTenantAgentBindingsAuthorityModuleV2',
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
    require(COMPILED_ROOT + '/src/plugins/desktopSessionRunInputAuthorityModuleV2.js')
      .desktopSessionRunInputAuthorityDefinitionV2,
    ...authorityModules,
    marketplace.desktopPluginMarketplaceCatalogDefinitionV2,
    marketplace.desktopPluginMarketplaceManagementDefinitionV2,
    desktopSessionArtifactActionAuthorityDefinitionV2,
  ];
}

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46852',
    apiKey: 'artifact-action-session',
    localApiToken: 'artifact-action-launch',
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

function artifactVersion(overrides = {}) {
  return {
    id: 'artifact-version-2',
    artifact_id: 'artifact-1',
    source_artifact_id: 'source-artifact-1',
    conversation_id: 'conversation-1',
    run_id: 'run-1',
    version: 2,
    status: 'approved',
    revision: 4,
    filename: 'report.md',
    mime_type: 'text/markdown',
    path: '/workspace/project-1/report.md',
    relative_path: 'report.md',
    bytes: 128,
    sources: [{ kind: 'file', path: 'source.md' }],
    checks: [{ kind: 'hash', status: 'passed' }],
    created_at: '2026-09-02T00:00:00Z',
    updated_at: '2026-09-02T00:01:00Z',
    approved_at: '2026-09-02T00:01:00Z',
    delivered_at: null,
    superseded_at: null,
    feedback: null,
    ...overrides,
  };
}

function reviewOutcome(overrides = {}) {
  return {
    accepted: true,
    status: 'approved',
    artifact_version: artifactVersion(),
    run: null,
    ...overrides,
  };
}

function deliveryOutcome(overrides = {}) {
  return {
    accepted: true,
    status: 'delivered',
    artifact_version: artifactVersion({
      status: 'delivered',
      revision: 5,
      delivered_at: '2026-09-02T00:02:00Z',
    }),
    delivery: {
      id: 'delivery-1',
      artifact_version_id: 'artifact-version-2',
      artifact_id: 'artifact-1',
      conversation_id: 'conversation-1',
      run_id: 'run-1',
      destination: 'local_workspace',
      receipt: { artifact_version_id: 'artifact-version-2', bytes: 128 },
      idempotency_key: 'artifact-version-2:4:deliver',
      created_at: '2026-09-02T00:02:00Z',
    },
    ...overrides,
  };
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

test('generated contract declares one credential-free root Artifact Action Provider', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const bootstrap = loadBootstrap();
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_SESSION_ARTIFACT_ACTION_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_SESSION_ARTIFACT_ACTION_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-session-artifact-action-authority',
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_SESSION_ARTIFACT_ACTION_AUTHORITY_SERVICE_V2,
        version: DESKTOP_SESSION_ARTIFACT_ACTION_AUTHORITY_VERSION_V2,
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
    desktopSessionArtifactActionAuthorityDefinitionV2.contractDigest,
  );
  assert.equal(catalog.entrypoint, 'applyDesktopSessionArtifactActionAuthorityV2');
  assert.equal(
    catalog.artifact_source,
    'repo+typescript://agi-stack/apps/desktop/src/plugins/' +
      'desktopSessionArtifactActionAuthorityModuleV2.ts',
  );
  assert.equal(entry.module_ref, DESKTOP_SESSION_ARTIFACT_ACTION_AUTHORITY_MODULE_REF_V2);
  assert.equal(entry.parent_entry_id, 'builtin-desktop-renderer-host');
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-client' });
  assert.deepEqual(entry.inject, {});
  assert.equal(entry.enabled, true);
  assert.match(profile, /entry_id: builtin-desktop-session-artifact-action-authority/u);
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(JSON.stringify(value), /apiKey|localApiToken|Authorization/iu);
  }
});

test('Loader activation and Profile disable remove Artifact Action without fallback', async () => {
  const bootstrap = loadBootstrap();
  const loader = new LoaderV2(rendererDefinitions(), 'desktop-renderer');
  const generation = await loader.stage(bootstrap);
  const service = generation.resolve(
    DESKTOP_SESSION_ARTIFACT_ACTION_AUTHORITY_SERVICE_V2,
    { kind: 'root' },
    { version: DESKTOP_SESSION_ARTIFACT_ACTION_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindOperation']);
  assert.throws(
    () =>
      service.bindOperation(
        runtimeConfig(),
        identity({ tenant_id: 'tenant-2' }),
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_session_artifact_action_scope_mismatch',
  );
  assert.throws(
    () =>
      applyDesktopSessionArtifactActionAuthorityV2(
        { provide: () => assert.fail('invalid config must not provide') },
        { strategy: 'legacy-client' },
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_session_artifact_action_authority_config_invalid',
  );

  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-session-artifact-action-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_SESSION_ARTIFACT_ACTION_AUTHORITY_SERVICE_V2,
        {
          kind: 'session',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          session_id: 'conversation-1',
        },
        { version: DESKTOP_SESSION_ARTIFACT_ACTION_AUTHORITY_VERSION_V2 },
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service',
  );
  await disabledGeneration.dispose();
  await generation.dispose();
});

test('Local and Cloud transports preserve action contracts and vault secrecy', async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const localCalls = [];
  globalThis.fetch = async (input, init) => {
    localCalls.push({ input, init });
    return json(String(input).endsWith('/review') ? reviewOutcome() : deliveryOutcome());
  };

  try {
    const generation = await new LoaderV2(rendererDefinitions(), 'desktop-renderer').stage(
      loadBootstrap(),
    );
    const service = generation.resolve(
      DESKTOP_SESSION_ARTIFACT_ACTION_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: DESKTOP_SESSION_ARTIFACT_ACTION_AUTHORITY_VERSION_V2 },
    );
    const local = service.bindOperation(runtimeConfig(), identity());
    await local.reviewArtifactVersion('artifact-version-2', {
      action: 'approve',
      expectedRevision: 3,
    });
    await local.deliverArtifactVersion('artifact-version-2', {
      expectedRevision: 4,
      idempotencyKey: 'artifact-version-2:4:deliver',
      destination: 'local_workspace',
    });
    assert.deepEqual(
      localCalls.map(({ input }) => new URL(String(input)).pathname),
      [
        '/api/v1/agent/artifact-versions/artifact-version-2/review',
        '/api/v1/agent/artifact-versions/artifact-version-2/deliver',
      ],
    );
    assert.deepEqual(
      localCalls.map(({ init }) => JSON.parse(String(init.body))),
      [
        { action: 'approve', expected_revision: 3 },
        {
          expected_revision: 4,
          idempotency_key: 'artifact-version-2:4:deliver',
          destination: 'local_workspace',
        },
      ],
    );
    assert.equal(
      new Headers(localCalls[0].init.headers).get('Authorization'),
      'Bearer artifact-action-session',
    );

    const cloudCalls = [];
    globalThis.window = {
      __MEMSTACK_DESKTOP__: {
        core: {
          async invoke(command, args) {
            cloudCalls.push({ command, args });
            return {
              status: 200,
              body: args.request.path.endsWith('/review') ? reviewOutcome() : deliveryOutcome(),
            };
          },
        },
      },
    };
    const cloud = service.bindOperation(
      runtimeConfig({ mode: 'cloud', apiKey: '', localApiToken: '' }),
      identity(),
    );
    await cloud.reviewArtifactVersion('artifact-version-2', {
      action: 'approve',
      expectedRevision: 3,
    });
    await cloud.deliverArtifactVersion('artifact-version-2', {
      expectedRevision: 4,
      idempotencyKey: 'artifact-version-2:4:deliver',
      destination: 'local_workspace',
    });
    assert.deepEqual(
      cloudCalls.map(({ command, args }) => [command, args.request.path]),
      [
        ['cloud_request', '/api/v1/agent/artifact-versions/artifact-version-2/review'],
        ['cloud_request', '/api/v1/agent/artifact-versions/artifact-version-2/deliver'],
      ],
    );
    assert.equal(JSON.stringify(cloudCalls).includes('artifact-action-session'), false);
    assert.equal(JSON.stringify(cloudCalls).includes('artifact-action-launch'), false);
    await generation.dispose();
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});
