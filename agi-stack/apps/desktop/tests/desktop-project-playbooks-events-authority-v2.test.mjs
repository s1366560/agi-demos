import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const {
  DESKTOP_PROJECT_PLAYBOOKS_EVENTS_AUTHORITY_SERVICE_V2,
  DESKTOP_PROJECT_PLAYBOOKS_EVENTS_AUTHORITY_VERSION_V2,
  createDesktopProjectPlaybooksEventsOperationsV2,
} = require(
  COMPILED_ROOT + '/src/plugins/desktopProjectPlaybooksEventsAuthorityModuleV2.js',
);
const { createDesktopProjectPlaybooksEventsSocketAuthorityV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopProjectPlaybooksEventsSocketProjectionV2.js',
);
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function config(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'https://cloud.memstack.test',
    deviceAuthorizationBaseUrl: 'https://cloud.memstack.test',
    apiKey: 'session',
    localApiToken: 'launch',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: '',
    mode: 'cloud',
    workspaceRoot: '',
    ...overrides,
  };
}

const scope = (authority = 'cloud') => ({
  authority,
  tenantId: 'tenant-1',
  projectId: 'project-1',
});

function service(events, overrides = {}) {
  return Object.freeze({
    bindOperation(operationConfig, operationScope) {
      events.push(['bind', operationConfig, operationScope]);
      return Object.freeze({
        subscribe(listener) {
          events.push(['subscribe', listener]);
          if (overrides.subscribe) return overrides.subscribe(listener);
          return () => events.push(['disconnect']);
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
        digest: 'digest-playbooks-events',
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

test('subscription pins one project generation lease until synchronous idempotent unsubscribe', async () => {
  const events = [];
  const lifecycle = [];
  let currentActions = actions(service(events), lifecycle);
  const operations = createDesktopProjectPlaybooksEventsOperationsV2(
    () => currentActions,
  );
  let refreshes = 0;
  const mutableConfig = config();
  const mutableScope = scope();
  const unsubscribe = operations.subscribeProjectPlaybooksEvents({
    config: mutableConfig,
    scope: mutableScope,
    listener: () => {
      refreshes += 1;
    },
  });
  mutableConfig.tenantId = 'tenant-mutated';
  mutableScope.projectId = 'project-mutated';

  await waitFor(() => events.some(([kind]) => kind === 'subscribe'));
  const listener = events.find(([kind]) => kind === 'subscribe')[1];
  currentActions = actions(service([], { subscribe: () => () => {} }), []);
  listener();
  assert.equal(refreshes, 1);
  assert.deepEqual(lifecycle[0], [
    'acquire',
    {
      service: DESKTOP_PROJECT_PLAYBOOKS_EVENTS_AUTHORITY_SERVICE_V2,
      version: DESKTOP_PROJECT_PLAYBOOKS_EVENTS_AUTHORITY_VERSION_V2,
      scope: { kind: 'project', tenant_id: 'tenant-1', project_id: 'project-1' },
    },
  ]);
  assert.equal(lifecycle.some(([kind]) => kind === 'release'), false);
  assert.equal(events[0][1].tenantId, 'tenant-1');
  assert.equal(events[0][2].projectId, 'project-1');

  unsubscribe();
  unsubscribe();
  await waitFor(() => lifecycle.some(([kind]) => kind === 'release'));
  assert.equal(events.filter(([kind]) => kind === 'disconnect').length, 1);
  assert.equal(lifecycle.filter(([kind]) => kind === 'release').length, 1);
  listener();
  assert.equal(refreshes, 1);
});

test('unsubscribe wins an acquire race and releases without activating the authority', async () => {
  let resolveAdmission;
  let binds = 0;
  let releases = 0;
  const operations = createDesktopProjectPlaybooksEventsOperationsV2(() => ({
    acquireServiceOperationLease() {
      return new Promise((resolve) => {
        resolveAdmission = resolve;
      });
    },
  }));
  const unsubscribe = operations.subscribeProjectPlaybooksEvents({
    config: config(),
    scope: scope(),
    listener: () => {},
  });
  unsubscribe();
  resolveAdmission({
    status: 'accepted',
    digest: 'digest-playbooks-events',
    useService() {
      binds += 1;
    },
    async release() {
      releases += 1;
    },
  });
  await waitFor(() => releases === 1);
  assert.equal(binds, 0);
});

test('disconnect failure remains authoritative over asynchronous lease release failure', async () => {
  const primary = new Error('disconnect_failed');
  const operations = createDesktopProjectPlaybooksEventsOperationsV2(() =>
    actions(
      service([], {
        subscribe: () => () => {
          throw primary;
        },
      }),
      [],
      new Error('release_failed'),
    ),
  );
  const unsubscribe = operations.subscribeProjectPlaybooksEvents({
    config: config(),
    scope: scope(),
    listener: () => {},
  });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.throws(unsubscribe, (error) => error === primary);
});

test('Local authority is explicitly inert and never loads projection or socket transport', () => {
  let projectionLoads = 0;
  let transportLoads = 0;
  const authority = createDesktopProjectPlaybooksEventsSocketAuthorityV2(
    config({ mode: 'local' }),
    scope('local'),
    {
      projectionClient: {
        async load() {
          projectionLoads += 1;
          return { apiBaseUrl: 'https://must-not-load.invalid' };
        },
      },
      transport() {
        transportLoads += 1;
        return null;
      },
      sessionId: () => 'must-not-load',
    },
  );
  const unsubscribe = authority.subscribe(() => {
    throw new Error('must_not_refresh');
  });
  unsubscribe();
  unsubscribe();
  assert.equal(projectionLoads, 0);
  assert.equal(transportLoads, 0);
});

test('Cloud unsubscribe aborts a pending projection before opening socket transport', async () => {
  let projectionSignal = null;
  let transportLoads = 0;
  const authority = createDesktopProjectPlaybooksEventsSocketAuthorityV2(
    config(),
    scope(),
    {
      projectionClient: {
        load(signal) {
          projectionSignal = signal;
          return new Promise(() => {});
        },
      },
      transport() {
        transportLoads += 1;
        return null;
      },
      sessionId: () => 'playbooks_cloud_session_pending',
    },
  );
  const unsubscribe = authority.subscribe(() => {});
  await waitFor(() => projectionSignal !== null);
  unsubscribe();
  assert.equal(projectionSignal.aborted, true);
  assert.equal(transportLoads, 0);
});

test('Cloud authority opens a vault-bound projected socket and filters reflection events', async () => {
  const opened = [];
  const sent = [];
  const closed = [];
  let transportListener = null;
  let refreshes = 0;
  const transport = {
    subscribe(listener) {
      transportListener = listener;
      return () => {
        transportListener = null;
      };
    },
    async open(input) {
      opened.push(input);
      queueMicrotask(() => {
        transportListener?.({
          socketId: input.socketId,
          type: 'open',
          protocol: 'memstack.auth',
        });
      });
    },
    async send(input) {
      sent.push(input);
    },
    async close(input) {
      closed.push(input);
    },
  };
  const authority = createDesktopProjectPlaybooksEventsSocketAuthorityV2(
    config(),
    scope(),
    {
      projectionClient: {
        async load(signal) {
          assert.equal(signal.aborted, false);
          return { apiBaseUrl: 'https://projected.memstack.test' };
        },
      },
      transport: () => transport,
      sessionId: () => 'playbooks_cloud_session_1',
    },
  );
  const unsubscribe = authority.subscribe(() => {
    refreshes += 1;
  });
  await waitFor(() => sent.length === 1);
  assert.equal(new URL(opened[0].request.url).origin, 'wss://projected.memstack.test');
  assert.deepEqual(opened[0].request.scope, {
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    workspace_id: null,
    conversation_id: null,
  });
  assert.deepEqual(JSON.parse(sent[0].frame.text), {
    type: 'subscribe_project_events',
    project_id: 'project-1',
  });
  transportListener({
    socketId: opened[0].socketId,
    type: 'message',
    frame: {
      binary: false,
      text: JSON.stringify({ type: 'reflection_complete', project_id: 'project-1' }),
    },
  });
  assert.equal(refreshes, 1);
  unsubscribe();
  await waitFor(() => closed.length === 1);
  assert.equal(closed[0].reason, 'project_playbooks_unsubscribe');
});

async function waitFor(predicate, attempts = 100) {
  for (let index = 0; index < attempts; index += 1) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  assert.fail('condition_not_observed');
}
