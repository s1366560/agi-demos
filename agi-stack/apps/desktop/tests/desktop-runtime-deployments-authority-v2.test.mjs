import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
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
  DESKTOP_RUNTIME_DEPLOYMENTS_AUTHORITY_MODULE_REF_V2,
  DESKTOP_RUNTIME_DEPLOYMENTS_AUTHORITY_SERVICE_V2,
  DESKTOP_RUNTIME_DEPLOYMENTS_AUTHORITY_VERSION_V2,
  applyDesktopRuntimeDeploymentsAuthorityV2,
  createDesktopRuntimeDeploymentsOperationsV2,
  desktopRuntimeDeploymentsAuthorityDefinitionV2,
  withDesktopRuntimeDeploymentsAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopRuntimeDeploymentsAuthorityModuleV2.js');
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

const pluginRoot = `${COMPILED_ROOT}/src/plugins`;
const authorityModules = readdirSync(pluginRoot)
  .filter((name) => /AuthorityModules?V2\.js$/u.test(name))
  .flatMap((name) =>
    Object.values(require(`${pluginRoot}/${name}`)).filter(
      (value) => value?.moduleRef && typeof value?.apply === 'function',
    ),
  );
const REPOSITORY_ROOT = new URL('../../../../', import.meta.url);
const BOOTSTRAP_PATH = new URL(
  'shared/profiles/memstack-default-bootstrap.v2.json',
  REPOSITORY_ROOT,
);
const MANIFEST_PATH = new URL(
  'config/plugin-manifests-v2/memstack-renderer-target-hosts.v2.json',
  REPOSITORY_ROOT,
);
const PRODUCTION_PROFILE_PATH = new URL(
  'config/plugin-profiles/memstack-production-target-hosts.v2.yaml',
  REPOSITORY_ROOT,
);

function bootstrap() {
  return JSON.parse(readFileSync(BOOTSTRAP_PATH, 'utf8'));
}

function config(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'https://cloud.memstack.test',
    deviceAuthorizationBaseUrl: 'https://cloud.memstack.test',
    apiKey: 'session',
    localApiToken: 'launch',
    mode: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: '',
    workspaceRoot: '',
    ...overrides,
  };
}

const scope = (authority = 'cloud', instanceId = 'instance-1') => ({
  authority,
  tenantId: 'tenant-1',
  instanceId,
});

const deployment = (id = 'deploy-1') => ({
  id,
  instanceId: 'instance-1',
  action: 'update',
  revision: 7,
  status: 'running',
  imageVersion: 'v1.2.3',
  replicas: 3,
  startedAt: '2026-08-02T08:00:00Z',
  finishedAt: null,
  createdAt: '2026-08-02T07:59:00Z',
});

const page = (id = 'deploy-1') => ({
  deployments: [deployment(id)],
  total: 1,
  page: 1,
  pageSize: 10,
});

const capability = (operationScope = scope()) => {
  const local = operationScope.authority === 'local';
  return {
    availability: local ? 'not_applicable' : 'degraded',
    reason_code: local
      ? 'cloud_deployment_authority_not_applicable'
      : 'runtime_deployments_mutations_and_instance_discovery_partial',
    service_version: local ? null : '0.1.0',
    contract_version: local ? null : '3.0.0',
    allowed_actions: local
      ? []
      : ['view', 'list', 'refresh', 'paginate', 'inspect-progress', 'reconnect-progress'],
    scope: {
      tenant_id: operationScope.tenantId,
      project_id: null,
      workspace_id: null,
      instance_id: null,
    },
    authority_revision: null,
  };
};

function service(events, overrides = {}) {
  return Object.freeze({
    bindOperation(operationConfig, operationScope) {
      events.push(['bind', operationConfig, operationScope]);
      return Object.freeze({
        async list(query, signal) {
          events.push(['list', query, signal]);
          if (overrides.list) return overrides.list(query, signal);
          return page();
        },
        async get(id, signal) {
          events.push(['get', id, signal]);
          if (overrides.get) return overrides.get(id, signal);
          return deployment(id);
        },
        async streamProgress(id, onEvent, signal) {
          events.push(['stream', id, onEvent, signal]);
          if (overrides.streamProgress) return overrides.streamProgress(id, onEvent, signal);
          await onEvent({ type: 'done', status: 'success', deployId: id });
        },
        async probe(signal) {
          events.push(['probe', signal]);
          if (overrides.probe) return overrides.probe(signal);
          return capability(operationScope);
        },
      });
    },
  });
}

function actions(authorityService, lifecycle = [], releaseError = null) {
  return {
    async acquireServiceOperationLease(request) {
      lifecycle.push(['acquire', request]);
      let released = false;
      return {
        status: 'accepted',
        digest: 'digest-runtime-deployments',
        useService(operation) {
          if (released) throw new Error('lease_released');
          return operation(authorityService);
        },
        async release() {
          if (released) return;
          released = true;
          lifecycle.push(['release']);
          if (releaseError) throw releaseError;
        },
      };
    },
  };
}

test('generated contract declares one credential-free root Runtime Deployments Provider', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_RUNTIME_DEPLOYMENTS_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_RUNTIME_DEPLOYMENTS_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap().entries.find(
    ({ entry_id: entryId }) =>
      entryId === 'builtin-desktop-runtime-deployments-authority',
  );
  const productionProfile = readFileSync(PRODUCTION_PROFILE_PATH, 'utf8');

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_RUNTIME_DEPLOYMENTS_AUTHORITY_SERVICE_V2,
        version: DESKTOP_RUNTIME_DEPLOYMENTS_AUTHORITY_VERSION_V2,
      },
    ],
    requires: [],
  });
  assert.deepEqual(module.contract.events, { emits: [], handles: [] });
  assert.equal(module.contract.config_schema.additionalProperties, false);
  assert.deepEqual(module.contract.config_schema.required, ['strategy']);
  assert.equal(module.contract.config_schema.properties.strategy.const, 'desktop-api-fetch');
  assert.equal(module.contract_digest, catalog.contract_digest);
  assert.equal(module.contract_digest, desktopRuntimeDeploymentsAuthorityDefinitionV2.contractDigest);
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-fetch' });
  assert.deepEqual(entry.inject, {});
  assert.match(productionProfile, /builtin-desktop-runtime-deployments-authority/u);
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(JSON.stringify(value), /apiKey|localApiToken|Authorization|secret/iu);
  }
});

test('Loader activates the exact Runtime Deployments service and disabled Profile fails closed', async () => {
  const loader = new LoaderV2(
    [...createDesktopRendererDefinitionsV2(), ...authorityModules],
    'desktop-renderer',
  );
  const generation = await loader.stage(bootstrap());
  const service = generation.resolve(
    DESKTOP_RUNTIME_DEPLOYMENTS_AUTHORITY_SERVICE_V2,
    { kind: 'root' },
    { version: DESKTOP_RUNTIME_DEPLOYMENTS_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindOperation']);
  const disabled = structuredClone(bootstrap());
  disabled.entries.find(
    ({ entry_id: entryId }) =>
      entryId === 'builtin-desktop-runtime-deployments-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_RUNTIME_DEPLOYMENTS_AUTHORITY_SERVICE_V2,
        { kind: 'root' },
        { version: DESKTOP_RUNTIME_DEPLOYMENTS_AUTHORITY_VERSION_V2 },
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service',
  );
});

test('Runtime Deployments Provider publishes one exact root service and rejects invalid config', () => {
  const provided = [];
  applyDesktopRuntimeDeploymentsAuthorityV2(
    { provide: (key, value) => provided.push([key, value]) },
    { strategy: 'desktop-api-fetch' },
  );
  assert.equal(provided.length, 1);
  assert.equal(provided[0][0], DESKTOP_RUNTIME_DEPLOYMENTS_AUTHORITY_SERVICE_V2);
  assert.equal(Object.isFrozen(provided[0][1]), true);
  assert.deepEqual(Object.keys(provided[0][1]), ['bindOperation']);
  assert.throws(
    () =>
      applyDesktopRuntimeDeploymentsAuthorityV2(
        { provide: () => assert.fail('invalid config must not publish') },
        { strategy: 'legacy-client' },
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_runtime_deployments_authority_config_invalid',
  );
});

test('operations freeze inputs before admission and acquire one tenant lease each', async () => {
  const events = [];
  const lifecycle = [];
  const runtimeConfig = config();
  const operationScope = scope();
  const query = { page: 2, pageSize: 10 };
  const callbackEvents = [];
  const callback = (event) => callbackEvents.push(event);
  const controller = new AbortController();
  const operations = createDesktopRuntimeDeploymentsOperationsV2(() =>
    actions(service(events), lifecycle),
  );

  const listPending = operations.listRuntimeDeployments({
    config: runtimeConfig,
    scope: operationScope,
    query,
    signal: controller.signal,
  });
  runtimeConfig.tenantId = 'changed';
  operationScope.tenantId = 'changed';
  operationScope.instanceId = 'changed';
  query.page = 99;
  const listResult = await listPending;
  const getResult = await operations.getRuntimeDeployment({
    config: config(),
    scope: scope(),
    deploymentId: 'deploy-1',
  });
  const replacementEvents = [];
  const streamInput = {
    config: config(),
    scope: scope(),
    deploymentId: 'deploy-1',
    onEvent: callback,
    signal: controller.signal,
  };
  const streamPending = operations.streamRuntimeDeploymentProgress(streamInput);
  streamInput.config.tenantId = 'changed';
  streamInput.scope.tenantId = 'changed';
  streamInput.deploymentId = 'changed';
  streamInput.onEvent = (event) => replacementEvents.push(event);
  streamInput.signal = new AbortController().signal;
  await streamPending;
  await operations.probeRuntimeDeployments({ config: config(), scope: scope() });

  assert.equal(Object.isFrozen(listResult), true);
  assert.equal(Object.isFrozen(listResult.deployments), true);
  assert.equal(Object.isFrozen(listResult.deployments[0]), true);
  assert.equal(Object.isFrozen(getResult), true);
  assert.equal(callbackEvents.length, 1);
  assert.deepEqual(replacementEvents, []);
  assert.equal(Object.isFrozen(callbackEvents[0]), true);
  assert.deepEqual(events.find(([kind]) => kind === 'list').slice(1), [
    { page: 2, pageSize: 10 },
    controller.signal,
  ]);
  assert.equal(lifecycle.filter(([kind]) => kind === 'acquire').length, 4);
  assert.equal(lifecycle.filter(([kind]) => kind === 'release').length, 4);
  for (const [, request] of lifecycle.filter(([kind]) => kind === 'acquire')) {
    assert.deepEqual(request, {
      service: DESKTOP_RUNTIME_DEPLOYMENTS_AUTHORITY_SERVICE_V2,
      version: DESKTOP_RUNTIME_DEPLOYMENTS_AUTHORITY_VERSION_V2,
      scope: { kind: 'tenant', tenant_id: 'tenant-1' },
    });
  }
});

test('invalid inputs fail before lease acquisition', () => {
  let acquisitions = 0;
  const operations = createDesktopRuntimeDeploymentsOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      assert.fail('invalid input must not acquire');
    },
  }));
  const invalidLists = [
    { config: config({ mode: 'remote' }), scope: scope() },
    { config: config(), scope: scope('local') },
    { config: config(), scope: scope('cloud', ' bad') },
    { config: config(), scope: scope(), query: { pageSize: 101 } },
    { config: config(), scope: scope(), extra: true },
  ];
  for (const input of invalidLists) {
    assert.throws(
      () => operations.listRuntimeDeployments(input),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_runtime_deployments_operation_input_invalid',
    );
  }
  for (const input of [
    { config: config(), scope: scope(), deploymentId: ' bad' },
    { config: config(), scope: scope(), deploymentId: 'deploy-1', onEvent: 'nope' },
  ]) {
    const operation = Object.hasOwn(input, 'onEvent')
      ? operations.streamRuntimeDeploymentProgress
      : operations.getRuntimeDeployment;
    assert.throws(
      () => operation(input),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_runtime_deployments_operation_input_invalid',
    );
  }
  assert.equal(acquisitions, 0);
});

test('missing generation actions and rejected admission fail closed', async () => {
  const unavailable = createDesktopRuntimeDeploymentsOperationsV2(() => null);
  assert.throws(
    () => unavailable.probeRuntimeDeployments({ config: config(), scope: scope() }),
    (error) =>
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable' &&
      error.runtimeCode === undefined,
  );

  const rejected = createDesktopRuntimeDeploymentsOperationsV2(() => ({
    async acquireServiceOperationLease() {
      return {
        status: 'rejected',
        reasonCode: 'desktop_renderer_generation_service_unavailable',
        runtimeCode: 'missing_service',
      };
    },
  }));
  await assert.rejects(
    rejected.probeRuntimeDeployments({ config: config(), scope: scope() }),
    (error) =>
      error.reasonCode === 'desktop_renderer_generation_service_unavailable' &&
      error.runtimeCode === 'missing_service',
  );
});

test('service, authority and return shapes fail closed', async () => {
  const malformedLifecycle = [];
  const malformedService = createDesktopRuntimeDeploymentsOperationsV2(() =>
    actions(
      Object.freeze({
        bindOperation: () => service([]).bindOperation(config(), scope()),
        fallback: true,
      }),
      malformedLifecycle,
    ),
  );
  await assert.rejects(
    malformedService.listRuntimeDeployments({ config: config(), scope: scope() }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_runtime_deployments_service_invalid',
  );
  assert.equal(malformedLifecycle.filter(([kind]) => kind === 'release').length, 1);

  const malformedAuthorityLifecycle = [];
  const malformedAuthority = createDesktopRuntimeDeploymentsOperationsV2(() =>
    actions(
      Object.freeze({ bindOperation: () => Object.freeze({ list: async () => page() }) }),
      malformedAuthorityLifecycle,
    ),
  );
  await assert.rejects(
    malformedAuthority.listRuntimeDeployments({ config: config(), scope: scope() }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_runtime_deployments_service_invalid',
  );
  assert.equal(malformedAuthorityLifecycle.filter(([kind]) => kind === 'release').length, 1);

  const malformedOutputs = [
    ['listRuntimeDeployments', { config: config(), scope: scope() }, { list: async () => ({ ...page(), secret: true }) }],
    ['getRuntimeDeployment', { config: config(), scope: scope(), deploymentId: 'deploy-1' }, { get: async () => ({ ...deployment(), status: 'mystery' }) }],
    ['probeRuntimeDeployments', { config: config(), scope: scope() }, { probe: async () => ({ ...capability(), authority_revision: 1 }) }],
  ];
  for (const [method, input, overrides] of malformedOutputs) {
    const operations = createDesktopRuntimeDeploymentsOperationsV2(() =>
      actions(service([], overrides)),
    );
    await assert.rejects(
      operations[method](input),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_runtime_deployments_service_contract_invalid',
    );
  }

  const malformedEvent = createDesktopRuntimeDeploymentsOperationsV2(() =>
    actions(service([], {
      streamProgress: async (_id, onEvent) => onEvent({ type: '', status: null, deployId: null }),
    })),
  );
  await assert.rejects(
    malformedEvent.streamRuntimeDeploymentProgress({
      config: config(),
      scope: scope(),
      deploymentId: 'deploy-1',
      onEvent: () => {},
    }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_runtime_deployments_service_contract_invalid',
  );
});

test('stream holds the old generation through callbacks while the next request uses HMR replacement', async () => {
  const oldLifecycle = [];
  const newLifecycle = [];
  let streamStarted;
  let finishStream;
  const started = new Promise((resolve) => { streamStarted = resolve; });
  const finish = new Promise((resolve) => { finishStream = resolve; });
  const oldService = service([], {
    async streamProgress(id, onEvent) {
      await onEvent({ type: 'status', status: 'running', deployId: id });
      streamStarted();
      await finish;
      await onEvent({ type: 'done', status: 'success', deployId: id });
    },
  });
  let current = actions(oldService, oldLifecycle);
  const operations = createDesktopRuntimeDeploymentsOperationsV2(() => current);
  const oldEvents = [];
  const oldRequest = operations.streamRuntimeDeploymentProgress({
    config: config(),
    scope: scope(),
    deploymentId: 'deploy-old',
    onEvent: (event) => oldEvents.push(event),
  });
  await started;
  assert.equal(oldLifecycle.some(([kind]) => kind === 'release'), false);

  current = actions(service([], { get: async () => deployment('deploy-new') }), newLifecycle);
  const newResult = await operations.getRuntimeDeployment({
    config: config(),
    scope: scope(),
    deploymentId: 'deploy-new',
  });
  assert.equal(newResult.id, 'deploy-new');
  assert.equal(newLifecycle.filter(([kind]) => kind === 'release').length, 1);

  finishStream();
  await oldRequest;
  assert.deepEqual(oldEvents.map(({ type }) => type), ['status', 'done']);
  assert.equal(oldLifecycle.filter(([kind]) => kind === 'release').length, 1);
});

test('escaped authority is revoked after release', async () => {
  let escaped;
  await withDesktopRuntimeDeploymentsAuthorityOperationV2(
    actions(service([])),
    { kind: 'probe', config: config(), scope: scope() },
    async (authority) => {
      escaped = authority;
      await authority.probe();
    },
  );
  await assert.rejects(
    escaped.probe(),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_runtime_deployments_operation_released',
  );
});

test('primary operation or callback errors outrank release failure on every path', async () => {
  const primary = new Error('primary-operation');
  const release = new Error('release-failure');
  const operations = createDesktopRuntimeDeploymentsOperationsV2(() =>
    actions(service([], { get: async () => { throw primary; } }), [], release),
  );
  await assert.rejects(
    operations.getRuntimeDeployment({
      config: config(),
      scope: scope(),
      deploymentId: 'deploy-1',
    }),
    primary,
  );

  const callbackFailure = new Error('callback-failure');
  const streamOperations = createDesktopRuntimeDeploymentsOperationsV2(() =>
    actions(service([]), [], release),
  );
  await assert.rejects(
    streamOperations.streamRuntimeDeploymentProgress({
      config: config(),
      scope: scope(),
      deploymentId: 'deploy-1',
      onEvent: async () => { throw callbackFailure; },
    }),
    callbackFailure,
  );
});
