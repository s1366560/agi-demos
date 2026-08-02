import assert from 'node:assert/strict';
import { test } from 'node:test';

const { DesktopApiError } = await import(
  '/tmp/agistack-desktop-test-dist/src/api/client.js'
);
const {
  createTenantAgentBindingsController,
} = await import(
  '/tmp/agistack-desktop-test-dist/src/features/tenant/tenantAgentBindingsController.js'
);

test('Agent Bindings controller suppresses stale completion after tenant scope switch', async () => {
  const pending = new Map();
  const controller = createTenantAgentBindingsController({
    authority: 'cloud',
    client: {
      list(scope, _query, options) {
        const request = deferred();
        pending.set(scope.tenantId, { ...request, signal: options.signal });
        return request.promise;
      },
    },
    initialScope: scope('tenant-1'),
  });

  const first = controller.load(scope('tenant-1'));
  const second = controller.load(scope('tenant-2'));
  assert.equal(pending.get('tenant-1').signal.aborted, true);
  assert.equal(controller.getSnapshot().state, 'scope_switch');
  assert.deepEqual(controller.getSnapshot().bindings, []);

  pending.get('tenant-1').resolve(snapshot('tenant-1'));
  await first;
  assert.equal(controller.getSnapshot().scope.tenantId, 'tenant-2');

  pending.get('tenant-2').resolve(snapshot('tenant-2'));
  await second;
  assert.equal(controller.getSnapshot().state, 'ready');
  assert.equal(controller.getSnapshot().bindings[0].tenantId, 'tenant-2');
});

test('Agent Bindings controller filters structurally and exposes an empty result state', async () => {
  const controller = readyController([
    binding('tenant-1', {
      agentName: 'Support',
      channelType: 'slack',
      enabled: true,
    }),
    binding('tenant-1', {
      id: 'binding-2',
      agentId: 'agent-2',
      agentName: 'Research',
      channelType: null,
      channelId: null,
      enabled: false,
    }),
  ]);
  await controller.load(scope('tenant-1'));

  controller.setFilters({ search: 'support', channelType: 'slack' });
  assert.equal(controller.getSnapshot().visibleBindings.length, 1);
  assert.equal(controller.getSnapshot().visibleBindings[0].agentName, 'Support');

  controller.setFilters({ search: '', channelType: 'any', enabled: false });
  assert.equal(controller.getSnapshot().visibleBindings[0].agentName, 'Research');

  controller.setFilters({ search: 'missing' });
  assert.equal(controller.getSnapshot().state, 'empty');
  assert.equal(controller.getSnapshot().emptyReason, 'filter');
});

test('Agent Bindings controller binds production mutations, resolution test and stable retry keys', async () => {
  const calls = [];
  const controller = createTenantAgentBindingsController({
    authority: 'cloud',
    client: {
      async list(scopeValue) {
        return snapshot(scopeValue.tenantId);
      },
      async create(_scope, input, options) {
        calls.push(['create', input, options]);
        return binding('tenant-1', { id: 'binding-created' });
      },
      async delete(_scope, bindingId) {
        calls.push(['delete', bindingId]);
      },
      async setEnabled(_scope, bindingId, enabled) {
        calls.push(['set-enabled', bindingId, enabled]);
        return binding('tenant-1', { id: bindingId, enabled });
      },
      async test(_scope, input) {
        calls.push(['test', input]);
        return {
          agentId: 'agent-1',
          agentName: 'Support',
          bindingId: 'binding-1',
          specificityScore: 3,
          confidence: 1,
          matched: true,
          trace: [],
        };
      },
    },
    initialScope: scope('tenant-1'),
  });
  await controller.load(scope('tenant-1'));

  await controller.create(
    {
      agentId: 'agent-1',
      channelType: 'slack',
      channelId: null,
      accountId: null,
      peerId: null,
      groupId: null,
      priority: 0,
    },
    'desktop-binding-create-stable',
  );
  await controller.setEnabled('binding-1', false);
  await controller.delete('binding-1');
  await controller.test({
    channelType: 'slack',
    channelId: null,
    accountId: null,
    peerId: null,
  });

  assert.deepEqual(calls.map(([action]) => action), [
    'create',
    'set-enabled',
    'delete',
    'test',
  ]);
  assert.equal(calls[0][2].idempotencyKey, 'desktop-binding-create-stable');
  assert.equal(controller.getSnapshot().testResult.matched, true);
});

test('Agent Bindings controller covers stale, conflict, forbidden, unavailable and retry', async () => {
  let loadCalls = 0;
  const controller = createTenantAgentBindingsController({
    authority: 'cloud',
    client: {
      async list(scopeValue) {
        loadCalls += 1;
        if (loadCalls === 1) return snapshot(scopeValue.tenantId);
        throw new DesktopApiError('temporarily unavailable', 503, {
          reason_code: 'tenant_agent_bindings_temporarily_unavailable',
        });
      },
      async setEnabled() {
        throw new DesktopApiError('conflict', 409, {
          reason_code: 'tenant_agent_binding_conflict',
        });
      },
    },
    initialScope: scope('tenant-1'),
  });
  await controller.load(scope('tenant-1'));
  await controller.load(scope('tenant-1'));
  assert.equal(controller.getSnapshot().state, 'stale');
  assert.equal(controller.getSnapshot().bindings.length, 1);
  assert.equal(controller.getSnapshot().retryVisible, true);

  await assert.rejects(controller.setEnabled('binding-1', false), /conflict/u);
  assert.equal(controller.getSnapshot().state, 'conflict');

  const forbidden = errorController(403, 'tenant_agent_bindings_forbidden');
  await forbidden.load(scope('tenant-1'));
  assert.equal(forbidden.getSnapshot().state, 'forbidden');

  const unavailable = errorController(
    503,
    'tenant_agent_bindings_authority_unavailable',
  );
  await unavailable.load(scope('tenant-1'));
  assert.equal(unavailable.getSnapshot().state, 'unavailable');
  assert.equal(unavailable.getSnapshot().retryVisible, true);
  await unavailable.retry();
});

test('Local unavailable snapshot disables every authority action', async () => {
  const controller = createTenantAgentBindingsController({
    authority: 'local',
    client: {
      async list() {
        return {
          ...snapshot('tenant-local', 'local'),
          availability: 'unavailable',
          reasonCode: 'local_agent_binding_routing_authority_unavailable',
          allowedActions: [],
          bindings: [],
          definitions: [],
        };
      },
    },
    initialScope: scope('tenant-local', 'local'),
  });
  await controller.load(scope('tenant-local', 'local'));

  assert.equal(controller.getSnapshot().state, 'unavailable');
  assert.deepEqual(controller.getSnapshot().allowedActions, []);
  await assert.rejects(
    controller.test({
      channelType: 'slack',
      channelId: null,
      accountId: null,
      peerId: null,
    }),
    /tenant_agent_bindings_action_unavailable:test/u,
  );
});

function readyController(bindings) {
  return createTenantAgentBindingsController({
    authority: 'cloud',
    client: {
      async list(scopeValue) {
        return { ...snapshot(scopeValue.tenantId), bindings };
      },
    },
    initialScope: scope('tenant-1'),
  });
}

function errorController(status, reasonCode) {
  return createTenantAgentBindingsController({
    authority: 'cloud',
    client: {
      async list() {
        throw new DesktopApiError(reasonCode, status, {
          reason_code: reasonCode,
        });
      },
    },
    initialScope: scope('tenant-1'),
  });
}

function scope(tenantId, authority = 'cloud') {
  return { authority, tenantId };
}

function snapshot(tenantId, authority = 'cloud') {
  return {
    scope: scope(tenantId, authority),
    authority,
    availability: 'available',
    reasonCode: null,
    serviceVersion: authority === 'cloud' ? 'cloud' : '0.1.0',
    contractVersion: '3.0.0',
    allowedActions: [
      'view',
      'list',
      'create',
      'delete',
      'set-enabled',
      'test',
    ],
    authorityRevision: 7,
    bindings: [binding(tenantId)],
    definitions: [
      {
        id: 'agent-1',
        name: 'support',
        displayName: 'Support',
      },
    ],
  };
}

function binding(tenantId, overrides = {}) {
  return {
    id: 'binding-1',
    tenantId,
    agentId: 'agent-1',
    agentName: 'Support',
    channelType: 'slack',
    channelId: 'channel-1',
    accountId: null,
    peerId: null,
    groupId: null,
    priority: 0,
    enabled: true,
    createdAt: '2026-08-03T00:00:00Z',
    specificityScore: 3,
    ...overrides,
  };
}

function deferred() {
  let resolve;
  const promise = new Promise((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
}
