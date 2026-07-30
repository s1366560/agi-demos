import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createBrowserDesktopHashLocationPort,
  createDesktopHashRouteHost,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/navigation/desktopHashRouteHost.js'
);
const { createDesktopRouteRegistry } = require(
  '/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteRegistry.js'
);

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function route(id, path, loader, overrides = {}) {
  return {
    id,
    path,
    scope: ['tenant'],
    navGroup: 'tenant-core',
    capability: id,
    requiredPermission: ['authenticated'],
    localPolicy: 'native_equivalent',
    loader,
    ...overrides,
  };
}

function capability(tenantId = 'tenant-1', overrides = {}) {
  return {
    availability: 'available',
    reason_code: null,
    service_version: '3.0.0',
    contract_version: '3.0.0',
    allowed_actions: ['view'],
    scope: {
      tenant_id: tenantId,
      project_id: null,
      workspace_id: null,
      instance_id: null,
    },
    authority_revision: 1,
    ...overrides,
  };
}

function hashLocation(initialHash) {
  let hash = initialHash;
  const listeners = new Set();
  return {
    port: {
      readHash: () => hash,
      subscribe: (listener) => {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
    },
    navigate(nextHash) {
      hash = nextHash;
      for (const listener of [...listeners]) listener();
    },
    listenerCount: () => listeners.size,
  };
}

function hostOptions({
  registry,
  location,
  mode = 'cloud',
  permissions = new Set(['authenticated']),
  resolvePermissions,
  resolveCapability = (_id, context) => capability(context.tenantId),
  switchScope = async () => {},
}) {
  return {
    registry,
    location,
    mode,
    permissions,
    ...(resolvePermissions ? { resolvePermissions } : {}),
    resolveCapability,
    switchScope,
  };
}

function waitForState(host, predicate) {
  const current = host.getState();
  if (predicate(current)) return Promise.resolve(current);
  return new Promise((resolve) => {
    const unsubscribe = host.subscribe((state) => {
      if (!predicate(state)) return;
      unsubscribe();
      resolve(state);
    });
  });
}

test('host exposes malformed and not-found hash states without loading modules', async () => {
  let loadCount = 0;
  const registry = createDesktopRouteRegistry([
    route('tenant-overview', '/tenant/:tenantId/overview', async () => {
      loadCount += 1;
      return { default: 'Overview' };
    }),
  ]);

  const malformedLocation = hashLocation('#/tenant/%E0%A4%A/overview');
  const malformedHost = createDesktopHashRouteHost(
    hostOptions({ registry, location: malformedLocation.port })
  );
  await malformedHost.start();
  assert.deepEqual(malformedHost.getState(), {
    status: 'malformed',
    location: '#/tenant/%E0%A4%A/overview',
    reasonCode: 'desktop_route_malformed',
  });
  malformedHost.stop();

  const missingLocation = hashLocation('#/tenant/tenant-1/missing');
  const missingHost = createDesktopHashRouteHost(
    hostOptions({ registry, location: missingLocation.port })
  );
  await missingHost.start();
  assert.deepEqual(missingHost.getState(), {
    status: 'not_found',
    location: '#/tenant/tenant-1/missing',
    reasonCode: 'desktop_route_not_found',
  });
  missingHost.stop();
  assert.equal(loadCount, 0);
});

test('forbidden and unavailable routes never switch scope or load', async () => {
  let loadCount = 0;
  let scopeCount = 0;
  let capabilityCount = 0;
  const registry = createDesktopRouteRegistry([
    route(
      'tenant-billing',
      '/tenant/:tenantId/billing',
      async () => {
        loadCount += 1;
        return { default: 'Billing' };
      },
      {
        requiredPermission: ['authenticated', 'tenant_admin'],
        localPolicy: 'cloud_only',
      }
    ),
  ]);
  const location = hashLocation('#/tenant/tenant-1/billing');

  const forbiddenHost = createDesktopHashRouteHost(
    hostOptions({
      registry,
      location: location.port,
      permissions: new Set(['authenticated']),
      resolveCapability: () => {
        capabilityCount += 1;
        return capability();
      },
      switchScope: async () => {
        scopeCount += 1;
      },
    })
  );
  await forbiddenHost.start();
  assert.equal(forbiddenHost.getState().status, 'forbidden');
  forbiddenHost.stop();

  const localHost = createDesktopHashRouteHost(
    hostOptions({
      registry,
      location: location.port,
      mode: 'local',
      permissions: new Set(['authenticated', 'tenant_admin']),
      resolveCapability: () => {
        capabilityCount += 1;
        return capability();
      },
      switchScope: async () => {
        scopeCount += 1;
      },
    })
  );
  await localHost.start();
  assert.deepEqual(localHost.getState(), {
    status: 'unavailable',
    match: localHost.getState().match,
    reasonCode: 'desktop_route_local_cloud_only',
    capability: null,
  });
  localHost.stop();

  assert.equal(loadCount, 0);
  assert.equal(scopeCount, 0);
  assert.equal(capabilityCount, 0);
});

test('context permission resolver authorizes the exact matched route context', async () => {
  const permissionContexts = [];
  const registry = createDesktopRouteRegistry([
    route(
      'project-overview',
      '/tenant/:tenantId/project/:projectId',
      async () => ({ default: 'Project Overview' }),
      {
        scope: ['tenant', 'project'],
        requiredPermission: ['authenticated', 'project_member'],
      }
    ),
  ]);
  const location = hashLocation(
    '#/tenant/tenant-2/project/project-2',
  );
  const host = createDesktopHashRouteHost(
    hostOptions({
      registry,
      location: location.port,
      permissions: new Set(['authenticated']),
      resolvePermissions: (context) => {
        permissionContexts.push(context);
        return new Set(['authenticated', 'project_member']);
      },
      resolveCapability: (_id, context) =>
        capability(context.tenantId, {
          scope: {
            tenant_id: context.tenantId,
            project_id: context.projectId,
            workspace_id: null,
            instance_id: null,
          },
        }),
    })
  );

  await host.start();

  assert.deepEqual(permissionContexts, [
    { tenantId: 'tenant-2', projectId: 'project-2' },
  ]);
  assert.equal(host.getState().status, 'ready');
  assert.deepEqual(host.getState().match.context, {
    tenantId: 'tenant-2',
    projectId: 'project-2',
  });
  host.stop();
});

test('permission resolver failures fail closed before capability or scope work and can retry', async () => {
  let permissionAttempts = 0;
  let capabilityCount = 0;
  let scopeCount = 0;
  let loadCount = 0;
  const registry = createDesktopRouteRegistry([
    route(
      'project-overview',
      '/tenant/:tenantId/project/:projectId',
      async () => {
        loadCount += 1;
        return { default: 'Project Overview' };
      },
      {
        scope: ['tenant', 'project'],
        requiredPermission: ['authenticated', 'project_member'],
      }
    ),
  ]);
  const location = hashLocation(
    '#/tenant/tenant-1/project/project-1',
  );
  const host = createDesktopHashRouteHost(
    hostOptions({
      registry,
      location: location.port,
      resolvePermissions: (context) => {
        permissionAttempts += 1;
        assert.deepEqual(context, {
          tenantId: 'tenant-1',
          projectId: 'project-1',
        });
        if (permissionAttempts === 1) {
          throw new Error('permission authority unavailable');
        }
        return new Set(['authenticated', 'project_member']);
      },
      resolveCapability: (_id, context) => {
        capabilityCount += 1;
        return capability(context.tenantId, {
          scope: {
            tenant_id: context.tenantId,
            project_id: context.projectId,
            workspace_id: null,
            instance_id: null,
          },
        });
      },
      switchScope: async () => {
        scopeCount += 1;
      },
    })
  );

  await host.start();
  assert.deepEqual(host.getState(), {
    status: 'error',
    match: host.getState().match,
    reasonCode: 'desktop_route_permission_resolution_failed',
    retryable: true,
  });
  assert.equal(capabilityCount, 0);
  assert.equal(scopeCount, 0);
  assert.equal(loadCount, 0);

  await host.retry();
  assert.equal(host.getState().status, 'ready');
  assert.equal(permissionAttempts, 2);
  assert.equal(capabilityCount, 1);
  assert.equal(scopeCount, 1);
  assert.equal(loadCount, 1);
  host.stop();
});

test('host emits loading then ready or degraded after scope and lazy module resolve', async () => {
  const loadingStates = [];
  const registry = createDesktopRouteRegistry([
    route('tenant-overview', '/tenant/:tenantId/overview', async () => ({
      default: 'Overview',
    })),
  ]);
  const location = hashLocation('#/tenant/tenant-1/overview');
  const scopeContexts = [];
  const host = createDesktopHashRouteHost(
    hostOptions({
      registry,
      location: location.port,
      resolveCapability: () =>
        capability('tenant-1', {
          availability: 'degraded',
          reason_code: 'tenant_overview_read_only',
        }),
      switchScope: async (context, signal) => {
        assert.equal(signal.aborted, false);
        scopeContexts.push(context);
      },
    })
  );
  const unsubscribe = host.subscribe((state) => loadingStates.push(state.status));

  await host.start();

  assert.deepEqual(scopeContexts, [{ tenantId: 'tenant-1' }]);
  assert.deepEqual(loadingStates, ['loading', 'degraded']);
  assert.deepEqual(host.getState(), {
    status: 'degraded',
    match: host.getState().match,
    capability: host.getState().capability,
    module: { default: 'Overview' },
  });
  unsubscribe();
  host.stop();
});

test('hash changes abort prior scope work and suppress stale loader completion', async () => {
  const firstModule = deferred();
  const firstScopeSignal = deferred();
  const registry = createDesktopRouteRegistry([
    route('tenant-one', '/tenant/:tenantId/one', () => firstModule.promise),
    route('tenant-two', '/tenant/:tenantId/two', async () => ({ default: 'Two' })),
  ]);
  const location = hashLocation('#/tenant/tenant-1/one');
  const signals = [];
  const host = createDesktopHashRouteHost(
    hostOptions({
      registry,
      location: location.port,
      switchScope: async (_context, signal) => {
        signals.push(signal);
        if (signals.length === 1) firstScopeSignal.resolve();
      },
    })
  );

  const startPromise = host.start();
  await firstScopeSignal.promise;
  const readyTwo = waitForState(
    host,
    (state) => state.status === 'ready' && state.match.definition.id === 'tenant-two'
  );
  location.navigate('#/tenant/tenant-1/two');
  await readyTwo;

  assert.equal(signals[0].aborted, true);
  assert.equal(signals[1].aborted, false);
  firstModule.resolve({ default: 'One' });
  await startPromise;
  await Promise.resolve();
  assert.equal(host.getState().status, 'ready');
  assert.equal(host.getState().match.definition.id, 'tenant-two');
  host.stop();
});

test('loader errors are retryable and stop removes the hash listener and aborts work', async () => {
  let attempts = 0;
  const activeScope = deferred();
  const registry = createDesktopRouteRegistry([
    route('tenant-overview', '/tenant/:tenantId/overview', async () => {
      attempts += 1;
      if (attempts === 1) throw new Error('module failed');
      return { default: 'Overview' };
    }),
  ]);
  const location = hashLocation('#/tenant/tenant-1/overview');
  let latestSignal;
  const host = createDesktopHashRouteHost(
    hostOptions({
      registry,
      location: location.port,
      switchScope: async (_context, signal) => {
        latestSignal = signal;
        activeScope.resolve();
      },
    })
  );

  await host.start();
  assert.deepEqual(host.getState(), {
    status: 'error',
    match: host.getState().match,
    reasonCode: 'desktop_route_module_load_failed',
    retryable: true,
  });
  await host.retry();
  assert.equal(host.getState().status, 'ready');
  assert.equal(attempts, 2);
  assert.equal(location.listenerCount(), 1);

  await activeScope.promise;
  host.stop();
  assert.equal(latestSignal.aborted, true);
  assert.equal(location.listenerCount(), 0);
  const stoppedState = host.getState();
  location.navigate('#/tenant/tenant-1/missing');
  await Promise.resolve();
  assert.equal(host.getState(), stoppedState);
});

test('capability and scope failures expose distinct retryable error states', async () => {
  let loadCount = 0;
  const registry = createDesktopRouteRegistry([
    route('tenant-overview', '/tenant/:tenantId/overview', async () => {
      loadCount += 1;
      return { default: 'Overview' };
    }),
  ]);
  const location = hashLocation('#/tenant/tenant-1/overview');
  const capabilityHost = createDesktopHashRouteHost(
    hostOptions({
      registry,
      location: location.port,
      resolveCapability: () => {
        throw new Error('capability failed');
      },
    })
  );
  await capabilityHost.start();
  assert.deepEqual(capabilityHost.getState(), {
    status: 'error',
    match: capabilityHost.getState().match,
    reasonCode: 'desktop_route_capability_resolution_failed',
    retryable: true,
  });
  capabilityHost.stop();

  const scopeHost = createDesktopHashRouteHost(
    hostOptions({
      registry,
      location: location.port,
      switchScope: async () => {
        throw new Error('scope failed');
      },
    })
  );
  await scopeHost.start();
  assert.deepEqual(scopeHost.getState(), {
    status: 'error',
    match: scopeHost.getState().match,
    reasonCode: 'desktop_route_scope_switch_failed',
    retryable: true,
  });
  scopeHost.stop();
  assert.equal(loadCount, 0);
});

test('browser location port reads hash and owns only the hashchange listener', () => {
  const listeners = new Map();
  const target = {
    location: { hash: '#/tenant/tenant-1/overview' },
    addEventListener(type, listener) {
      listeners.set(type, listener);
    },
    removeEventListener(type, listener) {
      if (listeners.get(type) === listener) listeners.delete(type);
    },
  };
  const port = createBrowserDesktopHashLocationPort(target);
  let changes = 0;
  const unsubscribe = port.subscribe(() => {
    changes += 1;
  });

  assert.equal(port.readHash(), '#/tenant/tenant-1/overview');
  assert.deepEqual([...listeners.keys()], ['hashchange']);
  listeners.get('hashchange')();
  assert.equal(changes, 1);
  unsubscribe();
  assert.equal(listeners.size, 0);
});
