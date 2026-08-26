import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
const {
  createDesktopHashRouteHostReactAdapter,
  useDesktopHashRouteHost,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/useDesktopHashRouteHost.js');
const {
  createDesktopRouteRegistry,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteRegistry.js');

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function route(id, suffix, loader) {
  return {
    id,
    path: `/tenant/:tenantId/${suffix}`,
    scope: ['tenant'],
    navGroup: 'tenant-core',
    capability: id,
    requiredPermission: [['authenticated']],
    localPolicy: 'native_equivalent',
    loader,
  };
}

function capability(tenantId) {
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
    authority_source: 'cloud_service',
    provenance: 'observed',
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

function options({
  registry,
  location,
  switchScope = async () => {},
  acquireOperationLease,
}) {
  return Object.freeze({
    registry,
    location,
    mode: 'cloud',
    permissions: new Set(['authenticated']),
    resolveCapability: (_id, context) => capability(context.tenantId),
    switchScope,
    ...(acquireOperationLease ? { acquireOperationLease } : {}),
  });
}

function waitForState(adapter, predicate) {
  const current = adapter.getSnapshot();
  if (predicate(current)) return Promise.resolve(current);
  return new Promise((resolve) => {
    const unsubscribe = adapter.subscribe(() => {
      const state = adapter.getSnapshot();
      if (!predicate(state)) return;
      unsubscribe();
      resolve(state);
    });
  });
}

test('React hook exposes external-store state and owns start/stop without session state', () => {
  const registry = createDesktopRouteRegistry([
    route('tenant-overview', 'overview', async () => ({ default: 'Overview' })),
  ]);
  const location = hashLocation('#/tenant/tenant-1/overview');
  const stableOptions = options({ registry, location: location.port });
  const markup = renderToStaticMarkup(
    React.createElement(function RouteHostProbe() {
      const { state, retry } = useDesktopHashRouteHost(stableOptions);
      return React.createElement('output', {
        'data-retry': typeof retry,
        'data-state': state.status,
      });
    }),
  );
  const source = readFileSync(
    new URL(
      '../src/features/navigation/useDesktopHashRouteHost.ts',
      import.meta.url,
    ),
    'utf8',
  );

  assert.match(markup, /data-retry="function" data-state="idle"/u);
  assert.match(source, /useSyncExternalStore\(/u);
  assert.match(source, /void adapter\.start\(\)/u);
  assert.match(source, /return adapter\.stop/u);
  assert.doesNotMatch(source, /useState|features\/session|stores\//u);
});

test('StrictMode-like start/stop cycles keep one hash subscription and clean listeners', async () => {
  const registry = createDesktopRouteRegistry([
    route('tenant-overview', 'overview', async () => ({ default: 'Overview' })),
  ]);
  const location = hashLocation('#/tenant/tenant-1/overview');
  const adapter = createDesktopHashRouteHostReactAdapter(
    options({ registry, location: location.port }),
  );
  let notifications = 0;
  const unsubscribe = adapter.subscribe(() => {
    notifications += 1;
  });

  await adapter.start();
  assert.equal(location.listenerCount(), 1);
  assert.equal(adapter.getSnapshot().status, 'ready');
  adapter.stop();
  assert.equal(location.listenerCount(), 0);
  await adapter.start();
  assert.equal(location.listenerCount(), 1);

  const beforeUnsubscribe = notifications;
  unsubscribe();
  location.navigate('#/tenant/tenant-1/overview');
  await Promise.resolve();
  assert.equal(notifications, beforeUnsubscribe);
  adapter.stop();
  assert.equal(location.listenerCount(), 0);
});

test('hash changes publish the current route through the React adapter', async () => {
  const registry = createDesktopRouteRegistry([
    route('tenant-one', 'one', async () => ({ default: 'One' })),
    route('tenant-two', 'two', async () => ({ default: 'Two' })),
  ]);
  const location = hashLocation('#/tenant/tenant-1/one');
  const adapter = createDesktopHashRouteHostReactAdapter(
    options({ registry, location: location.port }),
  );
  await adapter.start();
  assert.equal(adapter.getSnapshot().match.definition.id, 'tenant-one');

  const readyTwo = waitForState(
    adapter,
    (state) =>
      state.status === 'ready' && state.match.definition.id === 'tenant-two',
  );
  location.navigate('#/tenant/tenant-1/two');
  await readyTwo;
  assert.equal(adapter.getSnapshot().match.definition.id, 'tenant-two');
  adapter.stop();
});

test('options recreation aborts the old host and stale work cannot replace the new state', async () => {
  const oldScope = deferred();
  const oldScopeStarted = deferred();
  const oldRegistry = createDesktopRouteRegistry([
    route('tenant-old', 'old', async () => ({ default: 'Old' })),
  ]);
  const oldLocation = hashLocation('#/tenant/tenant-1/old');
  let oldSignal;
  const oldAdapter = createDesktopHashRouteHostReactAdapter(
    options({
      registry: oldRegistry,
      location: oldLocation.port,
      switchScope: async (_context, signal) => {
        oldSignal = signal;
        oldScopeStarted.resolve();
        await oldScope.promise;
      },
    }),
  );
  const oldStart = oldAdapter.start();
  await oldScopeStarted.promise;

  const nextRegistry = createDesktopRouteRegistry([
    route('tenant-next', 'next', async () => ({ default: 'Next' })),
  ]);
  const nextLocation = hashLocation('#/tenant/tenant-2/next');
  const nextAdapter = createDesktopHashRouteHostReactAdapter(
    options({ registry: nextRegistry, location: nextLocation.port }),
  );
  oldAdapter.stop();
  await nextAdapter.start();

  assert.equal(oldSignal.aborted, true);
  assert.equal(oldLocation.listenerCount(), 0);
  assert.equal(nextAdapter.getSnapshot().status, 'ready');
  assert.equal(nextAdapter.getSnapshot().match.definition.id, 'tenant-next');

  oldScope.resolve();
  await oldStart;
  await Promise.resolve();
  assert.notEqual(oldAdapter.getSnapshot().status, 'ready');
  assert.equal(nextAdapter.getSnapshot().match.definition.id, 'tenant-next');
  nextAdapter.stop();
});

test('a route transition holds its operation lease until all asynchronous work settles', async () => {
  const scope = deferred();
  const scopeStarted = deferred();
  const registry = createDesktopRouteRegistry([
    route('tenant-leased', 'leased', async () => ({ default: 'Leased' })),
  ]);
  const location = hashLocation('#/tenant/tenant-1/leased');
  let acquired = 0;
  let released = 0;
  const adapter = createDesktopHashRouteHostReactAdapter(
    options({
      registry,
      location: location.port,
      acquireOperationLease: () => {
        acquired += 1;
        return Object.freeze({
          release: async () => {
            released += 1;
          },
        });
      },
      switchScope: async () => {
        scopeStarted.resolve();
        await scope.promise;
      },
    }),
  );

  const start = adapter.start();
  await scopeStarted.promise;
  assert.equal(acquired, 1);
  assert.equal(released, 0);

  scope.resolve();
  await start;
  assert.equal(adapter.getSnapshot().status, 'ready');
  assert.equal(released, 1);
  adapter.stop();
});

test('an aborted stale route transition releases its operation lease exactly once', async () => {
  const firstScope = deferred();
  const firstScopeStarted = deferred();
  const secondReleased = deferred();
  const registry = createDesktopRouteRegistry([
    route('tenant-first', 'first', async () => ({ default: 'First' })),
    route('tenant-second', 'second', async () => ({ default: 'Second' })),
  ]);
  const location = hashLocation('#/tenant/tenant-1/first');
  const releaseCounts = new Map();
  let acquisition = 0;
  let scopeAttempt = 0;
  const adapter = createDesktopHashRouteHostReactAdapter(
    options({
      registry,
      location: location.port,
      acquireOperationLease: () => {
        const leaseId = ++acquisition;
        return Object.freeze({
          release: async () => {
            releaseCounts.set(leaseId, (releaseCounts.get(leaseId) ?? 0) + 1);
            if (leaseId === 2) secondReleased.resolve();
          },
        });
      },
      switchScope: async (_context, signal) => {
        scopeAttempt += 1;
        if (scopeAttempt !== 1) return;
        firstScopeStarted.resolve(signal);
        await firstScope.promise;
      },
    }),
  );

  const firstStart = adapter.start();
  const firstSignal = await firstScopeStarted.promise;
  const secondReady = waitForState(
    adapter,
    (state) => state.status === 'ready' && state.match.definition.id === 'tenant-second',
  );
  location.navigate('#/tenant/tenant-1/second');
  await secondReady;
  await secondReleased.promise;

  assert.equal(firstSignal.aborted, true);
  assert.equal(releaseCounts.get(1), undefined);
  assert.equal(releaseCounts.get(2), 1);

  firstScope.resolve();
  await firstStart;
  assert.equal(releaseCounts.get(1), 1);
  assert.equal(releaseCounts.get(2), 1);
  adapter.stop();
});

test('retry delegates to the current host and unmount cleanup aborts active scope work', async () => {
  let loaderAttempts = 0;
  const activeScope = deferred();
  const scopeStarted = deferred();
  const registry = createDesktopRouteRegistry([
    route('tenant-retry', 'retry', async () => {
      loaderAttempts += 1;
      if (loaderAttempts === 1) throw new Error('load failed');
      return { default: 'Retry' };
    }),
    route('tenant-pending', 'pending', async () => ({ default: 'Pending' })),
  ]);
  const location = hashLocation('#/tenant/tenant-1/retry');
  let pendingSignal;
  const adapter = createDesktopHashRouteHostReactAdapter(
    options({
      registry,
      location: location.port,
      switchScope: async (context, signal) => {
        if (context.tenantId !== 'tenant-2') return;
        pendingSignal = signal;
        scopeStarted.resolve();
        await activeScope.promise;
      },
    }),
  );

  await adapter.start();
  assert.equal(adapter.getSnapshot().status, 'error');
  await adapter.retry();
  assert.equal(adapter.getSnapshot().status, 'ready');
  assert.equal(loaderAttempts, 2);

  location.navigate('#/tenant/tenant-2/pending');
  await scopeStarted.promise;
  adapter.stop();
  assert.equal(pendingSignal.aborted, true);
  assert.equal(location.listenerCount(), 0);
  activeScope.resolve();
});
