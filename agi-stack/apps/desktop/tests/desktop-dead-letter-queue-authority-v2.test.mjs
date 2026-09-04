import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const {
  DESKTOP_DEAD_LETTER_QUEUE_AUTHORITY_SERVICE_V2,
  createDesktopDeadLetterQueueOperationsV2,
  withDesktopDeadLetterQueueAuthorityOperationV2,
} = require(`${ROOT}/src/plugins/desktopDeadLetterQueueAuthorityModuleV2.js`);

const config = (mode = 'cloud') => ({
  apiBaseUrl: 'https://cloud.test',
  deviceAuthorizationBaseUrl: 'https://cloud.test',
  apiKey: 'secret',
  localApiToken: 'launch',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: '',
  workspaceRoot: '',
  mode,
});
const scope = (authority = 'cloud') => ({ authority, tenantId: 'tenant-1' });
const page = () => ({
  scope: scope(),
  authority: 'cloud',
  availability: 'available',
  reasonCode: null,
  contractVersion: '3.0.0',
  allowedActions: ['view'],
  authorityRevision: 2,
  messages: [],
  total: 0,
  limit: 25,
  offset: 0,
});
function service(events, pending) {
  return Object.freeze({
    bindOperation(runtime, operationScope) {
      events.push(['bind', runtime, operationScope]);
      return Object.freeze({
        list: async (query, signal) => {
          events.push(['list', query, signal]);
          return pending ? pending() : page();
        },
        get: async (id) => ({
          id,
          eventId: 'e',
          eventType: 't',
          payload: {},
          errorType: 'x',
          errorMessage: 'x',
          retryCount: 0,
          status: 'pending',
          createdAt: null,
          lastRetryAt: null,
          resolvedAt: null,
        }),
        stats: async () => ({
          total: 0,
          pending: 0,
          retrying: 0,
          discarded: 0,
          expired: 0,
          resolved: 0,
          oldestMessageAt: null,
          newestMessageAt: null,
        }),
        retry: async () => {},
        retryBatch: async (ids) => ({
          results: Object.fromEntries(ids.map((id) => [id, true])),
          successCount: ids.length,
          failureCount: 0,
        }),
        discard: async () => {},
        discardBatch: async (ids) => ({
          results: Object.fromEntries(ids.map((id) => [id, true])),
          successCount: ids.length,
          failureCount: 0,
        }),
        cleanupExpired: async () => ({ cleanedCount: 1 }),
        cleanupResolved: async () => ({ cleanedCount: 1 }),
        probe: async () => ({
          availability: 'available',
          reasonCode: null,
          allowedActions: ['view'],
          authorityRevision: 2,
        }),
      });
    },
  });
}
function actions(authority, lifecycle = [], releaseError) {
  return {
    async acquireServiceOperationLease(request) {
      lifecycle.push(['acquire', request]);
      return {
        status: 'accepted',
        digest: 'd',
        useService: (operation) => operation(authority),
        async release() {
          lifecycle.push(['release']);
          if (releaseError) throw releaseError;
        },
      };
    },
  };
}

test('all DLQ operations use tenant generation leases and freeze inputs before acquire', async () => {
  const events = [],
    lifecycle = [];
  const operations = createDesktopDeadLetterQueueOperationsV2(() =>
    actions(service(events), lifecycle),
  );
  const runtime = config(),
    operationScope = scope(),
    query = { limit: 25, offset: 0 };
  const first = operations.list({ config: runtime, scope: operationScope, query });
  runtime.tenantId = operationScope.tenantId = 'changed';
  query.limit = 99;
  await first;
  await operations.get({ config: config(), scope: scope(), id: 'm1' });
  await operations.stats({ config: config(), scope: scope() });
  await operations.retry({ config: config(), scope: scope(), id: 'm1' });
  await operations.retryBatch({ config: config(), scope: scope(), ids: ['m1'] });
  await operations.discard({ config: config(), scope: scope(), id: 'm1', reason: 'done' });
  await operations.discardBatch({ config: config(), scope: scope(), ids: ['m1'], reason: 'done' });
  await operations.cleanupExpired({ config: config(), scope: scope(), hours: 24 });
  await operations.cleanupResolved({ config: config(), scope: scope(), hours: 24 });
  await operations.probe({ config: config(), scope: scope() });
  assert.equal(events[0][1].tenantId, 'tenant-1');
  assert.equal(events[1][1].limit, 25);
  assert.equal(lifecycle.filter(([kind]) => kind === 'acquire').length, 10);
  assert.equal(lifecycle[0][1].service, DESKTOP_DEAD_LETTER_QUEUE_AUTHORITY_SERVICE_V2);
  assert.deepEqual(lifecycle[0][1].scope, { kind: 'tenant', tenant_id: 'tenant-1' });
});

test('validation precedes acquisition', () => {
  let acquired = false;
  const operations = createDesktopDeadLetterQueueOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquired = true;
    },
  }));
  assert.throws(() => operations.retryBatch({ config: config(), scope: scope(), ids: [] }));
  assert.throws(() => operations.cleanupExpired({ config: config(), scope: scope(), hours: -1 }));
  assert.equal(acquired, false);
});

test('HMR pins inflight generation and escaped authority is revoked', async () => {
  let finish, escaped;
  const oldEvents = [],
    newEvents = [];
  let current = actions(
    service(
      oldEvents,
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    ),
  );
  const operations = createDesktopDeadLetterQueueOperationsV2(() => current);
  const first = operations.list({ config: config(), scope: scope() });
  while (!finish) await new Promise((resolve) => setImmediate(resolve));
  current = actions(service(newEvents));
  finish(page());
  await first;
  await operations.list({ config: config(), scope: scope() });
  await withDesktopDeadLetterQueueAuthorityOperationV2(
    actions(service([])),
    { config: config(), scope: scope() },
    async (authority) => {
      escaped = authority;
      return page();
    },
  );
  await assert.rejects(
    () => escaped.stats(),
    (error) => error.code === 'desktop_dead_letter_queue_operation_released',
  );
  assert.equal(
    oldEvents.some(([kind]) => kind === 'list'),
    true,
  );
  assert.equal(
    newEvents.some(([kind]) => kind === 'list'),
    true,
  );
});

test('operation error outranks release failure and successful release failure propagates', async () => {
  const operationError = new Error('operation'),
    releaseError = new Error('release');
  await assert.rejects(
    () =>
      withDesktopDeadLetterQueueAuthorityOperationV2(
        actions(
          service([], async () => {
            throw operationError;
          }),
          [],
          releaseError,
        ),
        { config: config(), scope: scope() },
        (authority) =>
          authority.list({
            limit: 25,
            offset: 0,
            status: 'all',
            eventType: '',
            errorType: '',
            routingKey: '',
          }),
      ),
    operationError,
  );
  await assert.rejects(
    () =>
      withDesktopDeadLetterQueueAuthorityOperationV2(
        actions(service([]), [], releaseError),
        { config: config(), scope: scope() },
        (authority) =>
          authority.list({
            limit: 25,
            offset: 0,
            status: 'all',
            eventType: '',
            errorType: '',
            routingKey: '',
          }),
      ),
    releaseError,
  );
});
