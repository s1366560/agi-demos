import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  createDeadLetterQueueRouteModuleLoader,
} = require('/tmp/agistack-desktop-test-dist/src/features/governance/deadLetterQueueRouteModule.js');
const {
  DEAD_LETTER_QUEUE_REFRESH_INTERVAL_MS,
  deadLetterQueueAutoRefreshAllowed,
} = require('/tmp/agistack-desktop-test-dist/src/features/governance/useDeadLetterQueueController.js');

test('DLQ refreshes every 30 seconds only while visible and settled', () => {
  assert.equal(DEAD_LETTER_QUEUE_REFRESH_INTERVAL_MS, 30_000);
  assert.equal(deadLetterQueueAutoRefreshAllowed('visible', null), true);
  assert.equal(deadLetterQueueAutoRefreshAllowed('hidden', null), false);
  assert.equal(deadLetterQueueAutoRefreshAllowed('visible', 'retry-selected'), false);
});

test('Cloud DLQ loader is lazy and renders native queue authority', async () => {
  let bindingCalls = 0;
  const module = await createDeadLetterQueueRouteModuleLoader({
    createBinding(context) {
      bindingCalls += 1;
      assert.equal(context.tenantId, 'tenant-1');
      return { controller: controller(), scope: scope() };
    },
  })();
  assert.equal(bindingCalls, 0);
  assert.equal(module.routeId, 'tenant-tenant-dead-letter-queue');
  assert.equal(module.disposition, 'implemented');

  const markup = renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(module.Surface, { context: { tenantId: 'tenant-1' }, module }),
    ),
  );
  assert.equal(bindingCalls, 1);
  assert.match(markup, /Dead letter queue/i);
  assert.match(markup, /episode.created/);
  assert.match(markup, /Retry selected/);
  assert.match(markup, /Discard selected/);
  assert.match(markup, /Cleanup expired/);
  assert.doesNotMatch(markup, /iframe|webview|Open in browser/iu);
});

test('Local DLQ renders stable native not-applicable state', async () => {
  const module = await createDeadLetterQueueRouteModuleLoader({
    createBinding() {
      return {
        controller: controller({ authority: 'local' }),
        scope: { authority: 'local', tenantId: 'tenant-1' },
      };
    },
  })();
  const markup = renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(module.Surface, { context: { tenantId: 'tenant-1' }, module }),
    ),
  );
  assert.match(markup, /cloud_message_bus_dlq_not_applicable/);
  assert.doesNotMatch(markup, /Retry selected|Discard selected/);
});

function scope() {
  return { authority: 'cloud', tenantId: 'tenant-1' };
}

function controller(overrides = {}) {
  const authority = overrides.authority ?? 'cloud';
  return {
    subscribe() {
      return () => {};
    },
    getSnapshot() {
      if (authority === 'local') {
        return {
          ...model(),
          scope: { authority, tenantId: 'tenant-1' },
          authority,
          messagesState: 'unavailable',
          statsState: 'unavailable',
          messagesReasonCode: 'cloud_message_bus_dlq_not_applicable',
          statsReasonCode: 'cloud_message_bus_dlq_not_applicable',
          allowedActions: [],
          messages: [],
          stats: null,
          lastUpdatedAt: null,
        };
      }
      return model();
    },
    async load() {},
    async retry() {},
    async retryMessage() {},
    async retryMessages() {},
    async retrySelected() {},
    async discardMessages() {},
    async discardMessage() {},
    async discardSelected() {},
    async cleanup() {},
    async setQuery() {},
    async openDetail() {},
    closeDetail() {},
    toggleSelection() {},
    clearSelection() {},
    cancel() {},
    stop() {},
  };
}

function model() {
  return {
    scope: scope(),
    authority: 'cloud',
    messagesState: 'ready',
    statsState: 'ready',
    messagesReasonCode: null,
    statsReasonCode: null,
    mutationState: 'idle',
    mutationReasonCode: null,
    retryMessagesVisible: false,
    retryStatsVisible: false,
    busyAction: null,
    allowedActions: [
      'view',
      'list',
      'inspect-stats',
      'inspect-message',
      'filter',
      'paginate',
      'refresh',
      'retry-message',
      'retry-batch',
      'discard',
      'cleanup',
    ],
    messages: [
      {
        id: 'message-1',
        eventId: 'event-1',
        eventType: 'episode.created',
        eventData: '{}',
        routingKey: 'memory.episode',
        error: 'timed out',
        errorType: 'TimeoutError',
        errorTraceback: null,
        retryCount: 1,
        maxRetries: 3,
        firstFailedAt: '2026-08-01T00:00:00Z',
        lastFailedAt: '2026-08-01T00:01:00Z',
        nextRetryAt: null,
        status: 'pending',
        metadata: {},
        canRetry: true,
        ageSeconds: 60,
      },
    ],
    stats: {
      totalMessages: 1,
      pendingCount: 1,
      retryingCount: 0,
      discardedCount: 0,
      expiredCount: 0,
      resolvedCount: 0,
      oldestMessageAgeSeconds: 60,
      errorTypeCounts: { TimeoutError: 1 },
      eventTypeCounts: { 'episode.created': 1 },
    },
    total: 1,
    limit: 50,
    offset: 0,
    hasMore: false,
    selectedIds: [],
    detail: null,
    detailState: 'idle',
    query: { status: 'all', eventType: '', errorType: '', routingKey: '', limit: 50, offset: 0 },
    lastUpdatedAt: '2026-08-01T00:00:00Z',
  };
}
