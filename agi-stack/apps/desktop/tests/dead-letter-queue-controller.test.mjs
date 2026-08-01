import assert from 'node:assert/strict';
import { test } from 'node:test';

const { DesktopApiError } = await import('/tmp/agistack-desktop-test-dist/src/api/client.js');
const { createDeadLetterQueueController } =
  await import('/tmp/agistack-desktop-test-dist/src/features/governance/deadLetterQueueController.js');

test('DLQ controller keeps message and stats loading/error states independent', async () => {
  const controller = createDeadLetterQueueController({
    authority: 'cloud',
    client: {
      async listMessages() {
        return page();
      },
      async getStats() {
        throw new DesktopApiError('unavailable', 503, { reason_code: 'dlq_stats_unavailable' });
      },
    },
    initialScope: scope(),
  });

  await controller.load(scope());
  const model = controller.getSnapshot();
  assert.equal(model.messagesState, 'ready');
  assert.equal(model.statsState, 'error');
  assert.equal(model.statsReasonCode, 'dlq_stats_unavailable');
  assert.equal(model.messages.length, 1);
  assert.equal(model.retryMessagesVisible, false);
  assert.equal(model.retryStatsVisible, true);
});

test('DLQ controller retains each last verified resource as stale on refresh failure', async () => {
  let fail = false;
  const controller = createDeadLetterQueueController({
    authority: 'cloud',
    client: {
      async listMessages() {
        if (fail) throw new DesktopApiError('offline', 503, {});
        return page();
      },
      async getStats() {
        if (fail) throw new DesktopApiError('offline', 503, {});
        return stats();
      },
    },
    initialScope: scope(),
  });

  await controller.load(scope());
  fail = true;
  await controller.retry();

  assert.equal(controller.getSnapshot().messagesState, 'stale');
  assert.equal(controller.getSnapshot().statsState, 'stale');
  assert.equal(controller.getSnapshot().messages.length, 1);
  assert.equal(controller.getSnapshot().stats?.totalMessages, 1);
});

test('DLQ controller supports detail, selection, filters, pagination and mutations', async () => {
  const calls = [];
  const controller = createDeadLetterQueueController({
    authority: 'cloud',
    client: {
      async listMessages(_scope, query) {
        calls.push(['list', query]);
        return page({ offset: query.offset ?? 0 });
      },
      async getMessage(_scope, id) {
        calls.push(['detail', id]);
        return message();
      },
      async getStats() {
        calls.push(['stats']);
        return stats();
      },
      async retryMessages(_scope, ids) {
        calls.push(['retry', ids]);
        return { results: { 'message-1': true }, successCount: 1, failureCount: 0 };
      },
      async discardMessages(_scope, ids, reason) {
        calls.push(['discard', ids, reason]);
        return { results: { 'message-1': true }, successCount: 1, failureCount: 0 };
      },
      async cleanupExpired(_scope, hours) {
        calls.push(['cleanup-expired', hours]);
        return { cleanedCount: 1 };
      },
      async cleanupResolved(_scope, hours) {
        calls.push(['cleanup-resolved', hours]);
        return { cleanedCount: 1 };
      },
    },
    initialScope: scope(),
  });

  await controller.load(scope());
  controller.toggleSelection('message-1');
  await controller.openDetail('message-1');
  await controller.setQuery({
    status: 'pending',
    eventType: 'episode.created',
    errorType: 'TimeoutError',
    routingKey: 'memory.episode',
    offset: 50,
  });
  controller.toggleSelection('message-1');
  await controller.retrySelected();
  controller.toggleSelection('message-1');
  await controller.discardSelected('operator reviewed');
  await controller.cleanup('expired', 168);
  await controller.cleanup('resolved', 24);

  assert.equal(controller.getSnapshot().detail?.id, 'message-1');
  assert.equal(controller.getSnapshot().query.offset, 50);
  assert.deepEqual(
    calls.filter(([kind]) => kind !== 'list' && kind !== 'stats'),
    [
      ['detail', 'message-1'],
      ['retry', ['message-1']],
      ['discard', ['message-1'], 'operator reviewed'],
      ['cleanup-expired', 168],
      ['cleanup-resolved', 24],
    ],
  );
});

test('DLQ controller maps forbidden/conflict and rejects empty discard reasons', async () => {
  const forbidden = controllerWithMutationError(
    new DesktopApiError('forbidden', 403, { reason_code: 'admin_access_required' }),
  );
  await forbidden.load(scope());
  forbidden.toggleSelection('message-1');
  await assert.rejects(forbidden.retrySelected(), /forbidden/u);
  assert.equal(forbidden.getSnapshot().mutationState, 'forbidden');

  const conflict = controllerWithMutationError(
    new DesktopApiError('conflict', 409, { reason_code: 'dlq_message_state_conflict' }),
  );
  await conflict.load(scope());
  conflict.toggleSelection('message-1');
  await assert.rejects(conflict.discardSelected('reviewed'), /conflict/u);
  assert.equal(conflict.getSnapshot().mutationState, 'conflict');
  await assert.rejects(
    conflict.discardSelected('   '),
    /dead_letter_queue_discard_reason_invalid/u,
  );
});

function controllerWithMutationError(error) {
  return createDeadLetterQueueController({
    authority: 'cloud',
    client: {
      async listMessages() {
        return page();
      },
      async getStats() {
        return stats();
      },
      async retryMessages() {
        throw error;
      },
      async discardMessages() {
        throw error;
      },
    },
    initialScope: scope(),
  });
}

function scope() {
  return { authority: 'cloud', tenantId: 'tenant-1' };
}

function page(overrides = {}) {
  return {
    scope: scope(),
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    serviceVersion: 'cloud',
    contractVersion: '3.0.0',
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
    authorityRevision: null,
    messages: [message()],
    total: 1,
    limit: 50,
    offset: 0,
    hasMore: false,
    ...overrides,
  };
}

function message() {
  return {
    id: 'message-1',
    eventId: 'event-1',
    eventType: 'episode.created',
    eventData: '{"episode_id":"episode-1"}',
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
    metadata: { source: 'worker' },
    canRetry: true,
    ageSeconds: 60,
  };
}

function stats() {
  return {
    totalMessages: 1,
    pendingCount: 1,
    retryingCount: 0,
    discardedCount: 0,
    expiredCount: 0,
    resolvedCount: 0,
    oldestMessageAgeSeconds: 60,
    errorTypeCounts: { TimeoutError: 1 },
    eventTypeCounts: { 'episode.created': 1 },
  };
}
