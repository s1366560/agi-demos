import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const REPOSITORY_ROOT = new URL('../../../../', import.meta.url);
const require = createRequire(import.meta.url);
const {
  createDesktopRendererDefinitionsV2,
  LoaderV2,
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
} = require('@agistack/plugin-runtime');
const {
  DESKTOP_PROJECT_BLACKBOARD_AUTHORITY_MODULE_REF_V2,
  DESKTOP_PROJECT_BLACKBOARD_AUTHORITY_SERVICE_V2,
  DESKTOP_PROJECT_BLACKBOARD_AUTHORITY_VERSION_V2,
  DesktopProjectBlackboardAuthorityUnavailableErrorV2,
  applyDesktopProjectBlackboardAuthorityV2,
  createDesktopProjectBlackboardOperationsV2,
  createDesktopWorkspaceCollaborationClientV2,
  desktopProjectBlackboardAuthorityDefinitionV2,
  withDesktopProjectBlackboardAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopProjectBlackboardAuthorityModuleV2.js');
const {
  createDesktopProjectBlackboardAuthorityV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopProjectBlackboardTransportV2.js');

const { requireCapabilityV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopProjectBlackboardOperationContractV2.js',
);

const authorityDefinitions = readdirSync(`${COMPILED_ROOT}/src/plugins`)
  .filter((name) => /AuthorityModules?V2\.js$/u.test(name))
  .flatMap((name) =>
    Object.values(require(`${COMPILED_ROOT}/src/plugins/${name}`)).filter(
      (value) => value?.moduleRef && typeof value?.apply === 'function',
    ),
  );

const MANIFEST_PATH = new URL(
  'config/plugin-manifests-v2/memstack-renderer-target-hosts.v2.json',
  REPOSITORY_ROOT,
);
const PROFILE_PATH = new URL(
  'config/plugin-profiles/memstack-production-target-hosts.v2.yaml',
  REPOSITORY_ROOT,
);
const BOOTSTRAP_PATH = new URL(
  'shared/profiles/memstack-default-bootstrap.v2.json',
  REPOSITORY_ROOT,
);

function source(relativePath) {
  return readFileSync(new URL(`../${relativePath}`, import.meta.url), 'utf8');
}

function runtimeConfig(overrides = {}) {
  return Object.freeze({
    apiBaseUrl: 'http://127.0.0.1:47771',
    deviceAuthorizationBaseUrl: 'https://auth.example.test',
    apiKey: 'project-blackboard-session',
    localApiToken: 'project-blackboard-launch',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    mode: 'local',
    workspaceRoot: '/workspace',
    ...overrides,
  });
}

function scope(authority = 'local') {
  return Object.freeze({
    authority,
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
  });
}

function surfaceState(overrides = {}) {
  return Object.freeze({
    workspace_id: 'workspace-1',
    surface: 'status',
    authority: 'local',
    status: 'ready',
    revision: 7,
    cursor: 'cursor-7',
    data: Object.freeze({ tasks: Object.freeze([]) }),
    reason_code: null,
    ...overrides,
  });
}

function projectBlackboardSnapshot(overrides = {}) {
  return Object.freeze({
    scope: scope(),
    authority: 'local',
    availability: 'degraded',
    reasonCode: 'local_workspace_plan_read_only',
    initialSurface: 'status',
    allowedActions: Object.freeze(['view', 'select-workspace', 'review-plan']),
    authorityRevision: null,
    ...overrides,
  });
}

function collaborationCapability(overrides = {}) {
  return Object.freeze({
    availability: 'degraded',
    reason_code: 'workspace_collaboration_mutation_guards_unavailable',
    service_version: '1.0.0',
    contract_version: '4.0.0',
    allowed_actions: Object.freeze(['status:view']),
    scope: Object.freeze({
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      workspace_id: 'workspace-1',
      instance_id: null,
    }),
    authority_revision: 7,
    ...overrides,
  });
}

function service(label = 'generation-a', lifecycle = [], overrides = {}) {
  return Object.freeze({
    bindOperation(config) {
      lifecycle.push({ type: 'bind', label, config });
      const authority = {
        async probeWorkspaceCollaborationCapability(operationScope) {
          lifecycle.push({
            type: 'probe-collaboration',
            label,
            scope: operationScope,
          });
          return collaborationCapability();
        },
        async probeProjectBlackboard(operationScope) {
          lifecycle.push({
            type: 'probe-blackboard',
            label,
            scope: operationScope,
          });
          return projectBlackboardSnapshot();
        },
        async getWorkspaceSurface(_projection, workspaceId, surface) {
          lifecycle.push({ type: 'get', label, workspaceId, surface });
          return surfaceState({ workspace_id: workspaceId, surface });
        },
        async refetchWorkspaceSurface(_projection, workspaceId, surface) {
          lifecycle.push({ type: 'refetch', label, workspaceId, surface });
          return surfaceState({ workspace_id: workspaceId, surface });
        },
        async mutateWorkspaceSurface(_projection, workspaceId, surface, mutation) {
          lifecycle.push({
            type: 'mutate',
            label,
            workspaceId,
            surface,
            mutation,
          });
          return surfaceState({
            workspace_id: workspaceId,
            surface,
            revision: 8,
            cursor: 'cursor-8',
          });
        },
      };
      return Object.freeze({ ...authority, ...overrides });
    },
  });
}

function acceptedActions(authorityService, digest, lifecycle = [], releaseError = null) {
  return Object.freeze({
    async acquireServiceOperationLease(request) {
      lifecycle.push({ type: 'acquire', digest, request });
      let released = false;
      return {
        status: 'accepted',
        digest,
        useService(operation) {
          if (released) throw new Error('lease_released');
          return operation(authorityService);
        },
        async release() {
          if (released) return;
          released = true;
          lifecycle.push({ type: 'release', digest });
          if (releaseError) throw releaseError;
        },
      };
    },
  });
}

test('generated contract exposes one credential-free root Project Blackboard Provider', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const bootstrap = JSON.parse(readFileSync(BOOTSTRAP_PATH, 'utf8'));
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_PROJECT_BLACKBOARD_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_PROJECT_BLACKBOARD_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-project-blackboard-authority',
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_PROJECT_BLACKBOARD_AUTHORITY_SERVICE_V2,
        version: DESKTOP_PROJECT_BLACKBOARD_AUTHORITY_VERSION_V2,
      },
    ],
    requires: [],
  });
  assert.deepEqual(module.contract.events, { emits: [], handles: [] });
  assert.equal(module.contract.config_schema.additionalProperties, false);
  assert.deepEqual(module.contract.config_schema.required, ['strategy']);
  assert.equal(module.contract.config_schema.properties.strategy.const, 'desktop-api-fetch');
  assert.equal(module.contract_digest, catalog.contract_digest);
  assert.equal(
    module.contract_digest,
    desktopProjectBlackboardAuthorityDefinitionV2.contractDigest,
  );
  assert.equal(catalog.entrypoint, 'applyDesktopProjectBlackboardAuthorityV2');
  assert.equal(entry.module_ref, DESKTOP_PROJECT_BLACKBOARD_AUTHORITY_MODULE_REF_V2);
  assert.equal(entry.parent_entry_id, 'builtin-desktop-renderer-host');
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-fetch' });
  assert.deepEqual(entry.inject, {});
  assert.equal(entry.enabled, true);
  assert.match(profile, /entry_id: builtin-desktop-project-blackboard-authority/u);
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(JSON.stringify(value), /apiKey|localApiToken|Authorization/iu);
  }
});

test('Provider rejects invalid config and exposes only bindOperation', () => {
  let provided = null;
  applyDesktopProjectBlackboardAuthorityV2(
    {
      provide(_serviceKey, value) {
        provided = value;
      },
    },
    { strategy: 'desktop-api-fetch' },
  );
  assert.equal(Object.isFrozen(provided), true);
  assert.deepEqual(Object.keys(provided), ['bindOperation']);
  assert.throws(
    () =>
      applyDesktopProjectBlackboardAuthorityV2(
        { provide: () => assert.fail('invalid config must not provide') },
        { strategy: 'legacy-client' },
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_project_blackboard_authority_config_invalid',
  );
  assert.throws(
    () =>
      applyDesktopProjectBlackboardAuthorityV2(
        { provide: () => assert.fail('extra config must not provide') },
        { strategy: 'desktop-api-fetch', fallback: true },
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_project_blackboard_authority_config_invalid',
  );
});

test('Loader activates the exact service and Profile disable removes it without fallback', async () => {
  const bootstrap = JSON.parse(readFileSync(BOOTSTRAP_PATH, 'utf8'));
  const loader = new LoaderV2(
    [...createDesktopRendererDefinitionsV2(), ...authorityDefinitions],
    'desktop-renderer',
  );
  const generation = await loader.stage(bootstrap);
  const authorityService = generation.resolve(
    DESKTOP_PROJECT_BLACKBOARD_AUTHORITY_SERVICE_V2,
    { kind: 'root' },
    { version: DESKTOP_PROJECT_BLACKBOARD_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(authorityService), true);
  assert.deepEqual(Object.keys(authorityService), ['bindOperation']);
  assert.equal('client' in authorityService, false);
  assert.equal('config' in authorityService, false);

  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-project-blackboard-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_PROJECT_BLACKBOARD_AUTHORITY_SERVICE_V2,
        { kind: 'project', tenant_id: 'tenant-1', project_id: 'project-1' },
        { version: DESKTOP_PROJECT_BLACKBOARD_AUTHORITY_VERSION_V2 },
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service',
  );
  await disabledGeneration.dispose();
  await generation.dispose();
});

test('Cloud transport stays vault-bound without exposing a renderer credential', async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const commands = [];
  globalThis.fetch = async () => assert.fail('vault-bound Cloud transport must not use fetch');
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          commands.push({ command, args });
          const path = args?.request?.path;
          if (path?.endsWith('/collaboration/capabilities')) {
            return {
              status: 200,
              body: {
                service_version: '0.1.0',
                contract_version: '2.0.0',
                authority: 'cloud',
                tenant_id: 'tenant-1',
                project_id: 'project-1',
                workspace_id: 'workspace-1',
                status: 'degraded',
                reason_code: 'workspace_collaboration_mutation_guards_unavailable',
                canonical_read: true,
                read_surfaces: [
                  'goals',
                  'discussion',
                  'status',
                  'collaboration',
                  'members',
                  'genes',
                  'files',
                  'notes',
                  'topology',
                  'settings',
                ],
                mutations: {
                  allowed: false,
                  revision_guarded: false,
                  idempotency_guarded: false,
                },
                allowed_actions: {},
              },
            };
          }
          if (path?.endsWith('/collaboration/authority')) {
            return {
              status: 200,
              body: {
                contract_version: '2.0.0',
                tenant_id: 'tenant-1',
                project_id: 'project-1',
                workspace_id: 'workspace-1',
                revision: 7,
                cursor: 'workspace:workspace-1:revision:7',
              },
            };
          }
          return { status: 404, body: { reason_code: 'unexpected_path' } };
        },
      },
    },
  };

  try {
    const authority = createDesktopProjectBlackboardAuthorityV2(
      runtimeConfig({ mode: 'cloud', apiKey: '', localApiToken: '' }),
    );
    const capability = await authority.probeWorkspaceCollaborationCapability({
      tenantId: 'tenant-1',
      projectId: 'project-1',
      workspaceId: 'workspace-1',
    });

    assert.equal(capability.availability, 'degraded');
    assert.equal(capability.authority_revision, 7);
    assert.deepEqual(capability.scope, {
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      workspace_id: 'workspace-1',
      instance_id: null,
    });
    assert.deepEqual(
      requireCapabilityV2(capability, runtimeConfig({ mode: 'cloud' })),
      capability,
    );
    assert.throws(() =>
      requireCapabilityV2(capability, runtimeConfig({ mode: 'cloud', workspaceId: 'other' })),
    );
    assert.equal(commands.length, 2);
    assert.deepEqual(
      commands.map(({ command, args }) => ({ command, request: args.request })),
      [
        {
          command: 'cloud_request',
          request: {
            path:
              '/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/' +
              'collaboration/capabilities',
            method: 'GET',
          },
        },
        {
          command: 'cloud_request',
          request: {
            path:
              '/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/' +
              'collaboration/authority',
            method: 'GET',
          },
        },
      ],
    );
    assert.doesNotMatch(JSON.stringify(commands), /Authorization|project-blackboard-session/iu);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test('every public operation acquires and releases one exact project generation lease', async () => {
  const lifecycle = [];
  const actions = acceptedActions(service('generation-a', lifecycle), 'digest-a', lifecycle);
  const operations = createDesktopProjectBlackboardOperationsV2(() => actions);
  const config = runtimeConfig();
  const mutation = Object.freeze({
    action: 'update_task',
    expected_revision: 7,
    idempotency_key: 'blackboard-mutation-7',
    payload: Object.freeze({ task_id: 'task-1' }),
  });

  await operations.probeWorkspaceCollaborationCapability({ config });
  await operations.probeProjectBlackboard({ config, scope: scope() });
  await operations.getWorkspaceSurface({
    config,
    projection: 'workspace-collaboration',
    workspaceId: 'workspace-1',
    surface: 'status',
    cursor: null,
  });
  await operations.refetchWorkspaceSurface({
    config,
    projection: 'project-blackboard',
    workspaceId: 'workspace-1',
    surface: 'status',
  });
  await operations.mutateWorkspaceSurface({
    config,
    projection: 'workspace-collaboration',
    workspaceId: 'workspace-1',
    surface: 'status',
    mutation,
  });

  const acquisitions = lifecycle.filter(({ type }) => type === 'acquire');
  const releases = lifecycle.filter(({ type }) => type === 'release');
  assert.equal(acquisitions.length, 5);
  assert.equal(releases.length, 5);
  for (const acquisition of acquisitions) {
    assert.deepEqual(acquisition.request, {
      service: DESKTOP_PROJECT_BLACKBOARD_AUTHORITY_SERVICE_V2,
      version: DESKTOP_PROJECT_BLACKBOARD_AUTHORITY_VERSION_V2,
      scope: {
        kind: 'project',
        tenant_id: 'tenant-1',
        project_id: 'project-1',
      },
    });
  }
});

test('operation input is frozen before admission and malformed input never acquires a lease', async () => {
  const lifecycle = [];
  const actions = acceptedActions(service('generation-a', lifecycle), 'digest-a', lifecycle);
  const operations = createDesktopProjectBlackboardOperationsV2(() => actions);
  const config = { ...runtimeConfig() };
  const mutation = {
    action: 'update_task',
    expected_revision: 7,
    idempotency_key: 'blackboard-mutation-7',
    payload: { task_id: 'task-1' },
  };
  const pending = operations.mutateWorkspaceSurface({
    config,
    projection: 'project-blackboard',
    workspaceId: 'workspace-1',
    surface: 'status',
    mutation,
  });
  config.tenantId = 'mutated-tenant';
  mutation.expected_revision = 99;
  mutation.payload.task_id = 'mutated-task';
  await pending;

  const bind = lifecycle.find(({ type }) => type === 'bind');
  const mutate = lifecycle.find(({ type }) => type === 'mutate');
  assert.equal(Object.isFrozen(bind.config), true);
  assert.equal(bind.config.tenantId, 'tenant-1');
  assert.equal(Object.isFrozen(mutate.mutation), true);
  assert.deepEqual(mutate.mutation, {
    action: 'update_task',
    expected_revision: 7,
    idempotency_key: 'blackboard-mutation-7',
    payload: { task_id: 'task-1' },
  });

  let acquisitions = 0;
  const rejectingOperations = createDesktopProjectBlackboardOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      throw new Error('unexpected_acquire');
    },
  }));
  for (const invoke of [
    () =>
      rejectingOperations.probeProjectBlackboard({
        config: runtimeConfig(),
        scope: { ...scope(), workspaceId: 'other-workspace' },
      }),
    () =>
      rejectingOperations.getWorkspaceSurface({
        config: runtimeConfig(),
        projection: 'project-blackboard',
        workspaceId: 'other-workspace',
        surface: 'status',
      }),
    () =>
      rejectingOperations.mutateWorkspaceSurface({
        config: runtimeConfig(),
        projection: 'project-blackboard',
        workspaceId: 'workspace-1',
        surface: 'status',
        mutation: { ...mutation, idempotency_key: 'short' },
      }),
    () =>
      rejectingOperations.probeWorkspaceCollaborationCapability({
        config: runtimeConfig(),
        signal: {},
      }),
    () =>
      rejectingOperations.probeWorkspaceCollaborationCapability({
        config: runtimeConfig(),
        unexpected: true,
      }),
  ]) {
    assert.throws(
      invoke,
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_blackboard_input_invalid',
    );
  }
  assert.equal(acquisitions, 0);
});

test('stable collaboration facade resolves a fresh generation for every method', async () => {
  const lifecycle = [];
  let actions = acceptedActions(service('generation-a', lifecycle), 'digest-a', lifecycle);
  const operations = createDesktopProjectBlackboardOperationsV2(() => actions);
  const client = createDesktopWorkspaceCollaborationClientV2(
    operations,
    () => runtimeConfig(),
    'workspace-collaboration',
  );

  const first = await client.getSurface('workspace-1', 'status');
  actions = acceptedActions(service('generation-b', lifecycle), 'digest-b', lifecycle);
  const second = await client.refetchAuthority('workspace-1', 'status');

  assert.equal(first.revision, 7);
  assert.equal(second.revision, 7);
  assert.deepEqual(
    lifecycle.filter(({ type }) => type === 'acquire').map(({ digest }) => digest),
    ['digest-a', 'digest-b'],
  );
});

test('captured Provider authority revokes after release and operation errors beat disposer errors', async () => {
  let escaped = null;
  const releaseFailure = new Error('release_failed');
  const operationFailure = new Error('operation_failed');
  await assert.rejects(
    withDesktopProjectBlackboardAuthorityOperationV2(
      acceptedActions(service(), 'digest-a', [], releaseFailure),
      {
        kind: 'probe-project-blackboard',
        config: runtimeConfig(),
        scope: scope(),
      },
      async (authority) => {
        escaped = authority;
        throw operationFailure;
      },
    ),
    (error) => error === operationFailure,
  );
  assert.throws(
    () => escaped.probeProjectBlackboard(scope()),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_project_blackboard_operation_released',
  );

  const successfulReleaseFailure = new Error('successful_release_failed');
  await assert.rejects(
    createDesktopProjectBlackboardOperationsV2(() =>
      acceptedActions(service(), 'digest-a', [], successfulReleaseFailure),
    ).probeProjectBlackboard({ config: runtimeConfig(), scope: scope() }),
    (error) => error === successfulReleaseFailure,
  );
});

test('missing, rejected and malformed services fail closed with structured authority errors', async () => {
  const missing = createDesktopProjectBlackboardOperationsV2(() => null);
  assert.throws(
    () =>
      missing.probeProjectBlackboard({
        config: runtimeConfig(),
        scope: scope(),
      }),
    (error) =>
      error instanceof DesktopProjectBlackboardAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );

  const rejected = createDesktopProjectBlackboardOperationsV2(() => ({
    async acquireServiceOperationLease() {
      return {
        status: 'rejected',
        reasonCode: 'desktop_renderer_service_unavailable',
        runtimeCode: 'missing_service',
      };
    },
  }));
  await assert.rejects(
    rejected.probeProjectBlackboard({
      config: runtimeConfig(),
      scope: scope(),
    }),
    (error) =>
      error instanceof DesktopProjectBlackboardAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_service_unavailable' &&
      error.runtimeCode === 'missing_service',
  );

  const malformedService = createDesktopProjectBlackboardOperationsV2(() =>
    acceptedActions(Object.freeze({}), 'digest-malformed'),
  );
  await assert.rejects(
    malformedService.probeProjectBlackboard({
      config: runtimeConfig(),
      scope: scope(),
    }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_project_blackboard_service_invalid',
  );

  const malformedResult = createDesktopProjectBlackboardOperationsV2(() =>
    acceptedActions(
      service('malformed-result', [], {
        async probeProjectBlackboard() {
          return projectBlackboardSnapshot({
            scope: { ...scope(), workspaceId: 'other' },
          });
        },
      }),
      'digest-malformed-result',
    ),
  );
  await assert.rejects(
    malformedResult.probeProjectBlackboard({
      config: runtimeConfig(),
      scope: scope(),
    }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_project_blackboard_service_invalid',
  );
});

test('HMR pins an in-flight surface operation and sends the next call to the new generation', async () => {
  const lifecycle = [];
  let resolveOld;
  const oldResponse = new Promise((resolve) => {
    resolveOld = resolve;
  });
  const oldService = service('generation-old', lifecycle, {
    async getWorkspaceSurface(_projection, workspaceId, surface) {
      lifecycle.push({
        type: 'get',
        label: 'generation-old',
        workspaceId,
        surface,
      });
      return oldResponse;
    },
  });
  const newService = service('generation-new', lifecycle, {
    async refetchWorkspaceSurface(_projection, workspaceId, surface) {
      lifecycle.push({
        type: 'refetch',
        label: 'generation-new',
        workspaceId,
        surface,
      });
      return surfaceState({
        workspace_id: workspaceId,
        surface,
        revision: 9,
        cursor: 'cursor-9',
      });
    },
  });
  let actions = acceptedActions(oldService, 'digest-old', lifecycle);
  const operations = createDesktopProjectBlackboardOperationsV2(() => actions);
  const client = createDesktopWorkspaceCollaborationClientV2(
    operations,
    () => runtimeConfig(),
    'workspace-collaboration',
  );

  const oldPending = client.getSurface('workspace-1', 'status');
  actions = acceptedActions(newService, 'digest-new', lifecycle);
  const next = await client.refetchAuthority('workspace-1', 'status');
  resolveOld(surfaceState({ revision: 7, cursor: 'cursor-7' }));
  const old = await oldPending;

  assert.equal(next.revision, 9);
  assert.equal(old.revision, 7);
  assert.deepEqual(
    lifecycle
      .filter(({ type }) => type === 'acquire' || type === 'release')
      .map(({ type, digest }) => `${type}:${digest}`),
    ['acquire:digest-old', 'acquire:digest-new', 'release:digest-new', 'release:digest-old'],
  );
});

test('all production consumers use the V2 operations facade with no parallel client authority', () => {
  const app = source('src/App.tsx');
  const routeRegistry = source('src/features/navigation/appRouteRegistry.ts');
  const workbench = source('src/features/runtime/workbenchCapabilityClient.ts');
  const provider = source('src/features/runtime/desktopWorkbenchCapabilityClientProviderV2.ts');
  const blackboardClient = source('src/features/project-blackboard/projectBlackboardClient.ts');
  const presentation = source(
    'src/features/project-blackboard/projectBlackboardPresentationModel.ts',
  );
  const generation = source('src/plugins/useDesktopPluginGenerationV2.ts');

  assert.match(app, /createDesktopProjectBlackboardOperationsV2/u);
  assert.match(app, /createDesktopWorkspaceCollaborationClientV2/u);
  assert.match(routeRegistry, /projectBlackboardOperationsV2/u);
  assert.match(workbench, /projectBlackboardOperationsV2/u);
  const dependencies = source('src/features/runtime/desktopWorkbenchSnapshotDependenciesV2.ts');
  const snapshotAuthority = source('src/plugins/desktopWorkbenchSnapshotAuthorityModuleV2.ts');
  assert.match(provider, /snapshotOperationsV2: DesktopWorkbenchSnapshotOperationsV2/u);
  assert.match(provider, /desktop_workbench_snapshot_operations_required/u);
  assert.match(provider, /operations\.loadSnapshot/u);
  assert.match(app, /snapshotOperationsV2:\s*desktopWorkbenchSnapshotOperationsV2/u);
  assert.match(snapshotAuthority, /createDesktopWorkbenchSnapshotDependenciesV2\(operationConfig, \(\) => actions\)/u);
  assert.match(dependencies, /createDesktopProjectBlackboardOperationsV2\(resolveActions\)/u);
  assert.match(dependencies, /const resolveActions = \(\) => parentActions/u);
  assert.match(dependencies, /projectBlackboardOperationsV2,/u);
  assert.doesNotMatch(dependencies, /GenerationActionsRefV2|new DesktopApiClient/u);
  assert.match(generation, /desktopProjectBlackboardAuthorityDefinitionV2/u);
  assert.doesNotMatch(app, /workspaceCollaborationClientProviderV2/u);
  assert.doesNotMatch(routeRegistry, /createProjectBlackboard(?:Cloud|Local)Client/u);
  assert.doesNotMatch(workbench, /createProjectBlackboard(?:Cloud|Local)Client/u);
  assert.doesNotMatch(workbench, /projectBlackboardClient\?:/u);
  assert.doesNotMatch(blackboardClient, /createProjectBlackboard(?:Cloud|Local)Client/u);
  assert.doesNotMatch(blackboardClient, /createHttpWorkspaceCollaborationClient/u);
  assert.doesNotMatch(presentation, /snapshot\.collaborationClient/u);
});
