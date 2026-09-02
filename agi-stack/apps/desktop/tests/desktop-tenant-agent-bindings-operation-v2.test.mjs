import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopTenantAgentBindingsAuthorityUnavailableErrorV2,
  createDesktopTenantAgentBindingsOperationsV2,
  withDesktopTenantAgentBindingsAuthorityOperationV2,
} = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantAgentBindingsAuthorityModuleV2.js',
);
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46942',
    apiKey: 'bindings-secret',
    localApiToken: 'bindings-launch',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: '',
    workspaceId: '',
    workspaceRoot: '',
    ...overrides,
  };
}

function scope(overrides = {}) {
  return { authority: 'local', tenantId: 'tenant-1', ...overrides };
}

function createInput(overrides = {}) {
  return {
    agentId: 'agent-1',
    channelType: 'slack',
    channelId: 'channel-1',
    accountId: null,
    peerId: null,
    groupId: null,
    priority: 0,
    ...overrides,
  };
}

function testInput(overrides = {}) {
  return {
    channelType: 'slack',
    channelId: 'channel-1',
    accountId: null,
    peerId: null,
    ...overrides,
  };
}

function binding(overrides = {}) {
  return {
    id: 'binding-1',
    tenantId: 'tenant-1',
    agentId: 'agent-1',
    agentName: 'Support',
    channelType: 'slack',
    channelId: 'channel-1',
    accountId: null,
    peerId: null,
    groupId: null,
    priority: 0,
    enabled: true,
    createdAt: '2026-09-03T00:00:00Z',
    specificityScore: 3,
    ...overrides,
  };
}

function snapshot(overrides = {}) {
  return {
    scope: scope(),
    authority: 'local',
    availability: 'unavailable',
    reasonCode: 'local_agent_binding_routing_authority_unavailable',
    serviceVersion: '0.1.0',
    contractVersion: '3.0.0',
    allowedActions: [],
    authorityRevision: 11,
    bindings: [],
    definitions: [],
    ...overrides,
  };
}

function testResult(overrides = {}) {
  return {
    agentId: 'agent-1',
    agentName: 'Support',
    bindingId: 'binding-1',
    specificityScore: 3,
    confidence: 1,
    matched: true,
    trace: [],
    ...overrides,
  };
}

function serviceFixture(received, overrides = {}) {
  return Object.freeze({
    bindOperation(config, operationScope) {
      received.push({ type: 'bind', config, scope: operationScope });
      return Object.freeze({
        async list(query, signal) {
          received.push({ type: 'list', query, signal });
          return overrides.list ?? snapshot();
        },
        async create(input, idempotencyKey, signal) {
          received.push({ type: 'create', input, idempotencyKey, signal });
          return overrides.create ?? binding();
        },
        async delete(bindingId, idempotencyKey, signal) {
          received.push({ type: 'delete', bindingId, idempotencyKey, signal });
          return overrides.delete;
        },
        async setEnabled(bindingId, enabled, idempotencyKey, signal) {
          received.push({
            type: 'set-enabled',
            bindingId,
            enabled,
            idempotencyKey,
            signal,
          });
          return overrides.setEnabled ?? binding({ id: bindingId, enabled });
        },
        async test(input, idempotencyKey, signal) {
          received.push({ type: 'test', input, idempotencyKey, signal });
          return overrides.test ?? testResult();
        },
      });
    },
  });
}

function acceptedActions(service, digest, lifecycle = [], releaseError = null) {
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
          if (releaseError) throw releaseError;
        },
      };
    },
  };
}

test('each bindings operation freezes inputs before one exact tenant lease', async () => {
  const lifecycle = [];
  const received = [];
  const controller = new AbortController();
  const config = runtimeConfig();
  const operationScope = scope();
  const query = { agentId: 'agent-1', enabledOnly: true };
  const create = createInput();
  const resolution = testInput();
  const operations = createDesktopTenantAgentBindingsOperationsV2(() =>
    acceptedActions(serviceFixture(received), 'digest-a', lifecycle),
  );

  const pendingList = operations.listTenantAgentBindings({
    config,
    scope: operationScope,
    query,
    signal: controller.signal,
  });
  config.tenantId = 'tenant-mutated';
  operationScope.tenantId = 'tenant-mutated';
  query.agentId = 'agent-mutated';
  await pendingList;

  const pendingCreate = operations.createTenantAgentBinding({
    config: runtimeConfig(),
    scope: scope(),
    input: create,
    idempotencyKey: 'binding-create-0001',
  });
  create.agentId = 'agent-mutated';
  await pendingCreate;
  await operations.deleteTenantAgentBinding({
    config: runtimeConfig(),
    scope: scope(),
    bindingId: 'binding-1',
    idempotencyKey: 'binding-delete-0001',
  });
  await operations.setTenantAgentBindingEnabled({
    config: runtimeConfig(),
    scope: scope(),
    bindingId: 'binding-1',
    enabled: false,
    idempotencyKey: 'binding-enabled-0001',
  });
  const pendingTest = operations.testTenantAgentBinding({
    config: runtimeConfig(),
    scope: scope(),
    input: resolution,
    idempotencyKey: 'binding-test-0001',
  });
  resolution.channelType = 'mutated';
  const result = await pendingTest;

  assert.equal(lifecycle.length, 10);
  for (const event of lifecycle.filter(({ type }) => type === 'acquire')) {
    assert.deepEqual(event.request, {
      service: 'service:desktop-renderer.tenant-agent-bindings-authority',
      version: '1.0.0',
      scope: { kind: 'tenant', tenant_id: 'tenant-1' },
    });
  }
  assert.equal(received[0].config.tenantId, 'tenant-1');
  assert.deepEqual(received[0].scope, { authority: 'local', tenantId: 'tenant-1' });
  assert.deepEqual(received[1].query, { agentId: 'agent-1', enabledOnly: true });
  assert.equal(Object.isFrozen(received[1].query), true);
  assert.equal(received[1].signal, controller.signal);
  assert.equal(received[3].input.agentId, 'agent-1');
  assert.equal(Object.isFrozen(received[3].input), true);
  assert.equal(received[9].input.channelType, 'slack');
  assert.equal(result.matched, true);
  assert.equal(Object.isFrozen(result.trace), true);
});

test('invalid scope, payload, identity and idempotency fail before acquisition', () => {
  let acquisitions = 0;
  const operations = createDesktopTenantAgentBindingsOperationsV2(() => ({
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      assert.fail('invalid input must not acquire a lease');
    },
  }));
  const invalidCalls = [
    () =>
      operations.listTenantAgentBindings({
        config: runtimeConfig(),
        scope: scope({ authority: 'cloud' }),
      }),
    () =>
      operations.createTenantAgentBinding({
        config: runtimeConfig(),
        scope: scope(),
        input: createInput({ agentId: ' agent-1' }),
      }),
    () =>
      operations.deleteTenantAgentBinding({
        config: runtimeConfig(),
        scope: scope(),
        bindingId: ' ',
      }),
    () =>
      operations.setTenantAgentBindingEnabled({
        config: runtimeConfig(),
        scope: scope(),
        bindingId: 'binding-1',
        enabled: 'false',
      }),
    () =>
      operations.testTenantAgentBinding({
        config: runtimeConfig(),
        scope: scope(),
        input: testInput({ channelType: ' slack' }),
      }),
    () =>
      operations.createTenantAgentBinding({
        config: runtimeConfig(),
        scope: scope(),
        input: createInput(),
        idempotencyKey: 'short',
      }),
  ];
  for (const invalidCall of invalidCalls) {
    assert.throws(
      invalidCall,
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_tenant_agent_bindings_operation_input_invalid',
    );
  }
  assert.equal(acquisitions, 0);
  assert.throws(
    () =>
      createDesktopTenantAgentBindingsOperationsV2(() => null).listTenantAgentBindings({
        config: runtimeConfig(),
        scope: scope(),
      }),
    (error) =>
      error instanceof DesktopTenantAgentBindingsAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
});

test('lease rejection and malformed service, authority or result shapes fail closed', async () => {
  const rejectedOperations = createDesktopTenantAgentBindingsOperationsV2(() => ({
    async acquireServiceOperationLease() {
      return {
        status: 'rejected',
        reasonCode: 'missing_service',
        runtimeCode: 'missing_service',
      };
    },
  }));
  await assert.rejects(
    rejectedOperations.listTenantAgentBindings({
      config: runtimeConfig(),
      scope: scope(),
    }),
    (error) =>
      error instanceof DesktopTenantAgentBindingsAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'missing_service' &&
      error.runtimeCode === 'missing_service',
  );

  for (const service of [
    Object.freeze({ bindOperation: null }),
    Object.freeze({
      bindOperation() {
        return Object.freeze({ list: async () => snapshot() });
      },
    }),
  ]) {
    const operations = createDesktopTenantAgentBindingsOperationsV2(() =>
      acceptedActions(service, 'invalid-shape'),
    );
    await assert.rejects(
      operations.listTenantAgentBindings({
        config: runtimeConfig(),
        scope: scope(),
      }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_tenant_agent_bindings_service_invalid',
    );
  }

  const malformed = createDesktopTenantAgentBindingsOperationsV2(() =>
    acceptedActions(serviceFixture([], { list: { ...snapshot(), authority: 'cloud' } }), 'bad'),
  );
  await assert.rejects(
    malformed.listTenantAgentBindings({ config: runtimeConfig(), scope: scope() }),
    /desktop_tenant_agent_bindings_service_contract_invalid/u,
  );
});

test('escaped authority is revoked and primary failure wins over disposer failure', async () => {
  let escaped;
  await withDesktopTenantAgentBindingsAuthorityOperationV2(
    acceptedActions(serviceFixture([]), 'digest-a'),
    { config: runtimeConfig(), scope: scope() },
    (authority) => {
      escaped = authority;
      return authority.list();
    },
  );
  await assert.rejects(
    escaped.list(),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_tenant_agent_bindings_operation_released',
  );

  const primary = new Error('primary_failure');
  const release = new Error('release_failure');
  await assert.rejects(
    withDesktopTenantAgentBindingsAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-failure', [], release),
      { config: runtimeConfig(), scope: scope() },
      async () => {
        throw primary;
      },
    ),
    (error) => error === primary,
  );
  await assert.rejects(
    withDesktopTenantAgentBindingsAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-release', [], release),
      { config: runtimeConfig(), scope: scope() },
      (authority) => authority.list(),
    ),
    (error) => error === release,
  );
});

test('old bindings request stays pinned while a new request uses replacement generation', async () => {
  let releaseOld;
  const gate = new Promise((resolve) => {
    releaseOld = resolve;
  });
  const oldService = serviceFixture([]);
  const originalBind = oldService.bindOperation;
  const gatedService = Object.freeze({
    bindOperation(...args) {
      const authority = originalBind(...args);
      return Object.freeze({
        ...authority,
        async list(query, signal) {
          await gate;
          await authority.list(query, signal);
          return snapshot({ serviceVersion: 'old' });
        },
      });
    },
  });
  let actions = acceptedActions(gatedService, 'old');
  const operations = createDesktopTenantAgentBindingsOperationsV2(() => actions);
  const oldRequest = operations.listTenantAgentBindings({
    config: runtimeConfig(),
    scope: scope(),
  });
  actions = acceptedActions(
    serviceFixture([], { list: snapshot({ serviceVersion: 'new' }) }),
    'new',
  );
  const newRequest = operations.listTenantAgentBindings({
    config: runtimeConfig(),
    scope: scope(),
  });
  releaseOld();

  assert.equal((await oldRequest).serviceVersion, 'old');
  assert.equal((await newRequest).serviceVersion, 'new');
});
