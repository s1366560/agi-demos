import assert from 'node:assert/strict';
import { test } from 'node:test';

const { createDeadLetterQueueHttpClient } =
  await import('/tmp/agistack-desktop-test-dist/src/features/governance/deadLetterQueueHttpClient.js');

const originalFetch = globalThis.fetch;

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test('Cloud DLQ client binds list, detail, retry, discard, stats and cleanup contracts', async () => {
  const requests = [];
  globalThis.fetch = async (url, init = {}) => {
    const parsed = new URL(String(url));
    requests.push({
      path: parsed.pathname,
      search: parsed.search,
      method: init.method ?? 'GET',
      body: init.body ? JSON.parse(String(init.body)) : null,
      authorization: new Headers(init.headers).get('Authorization'),
    });
    if (parsed.pathname.endsWith('/messages/message-1') && (init.method ?? 'GET') === 'GET') {
      return jsonResponse(message());
    }
    if (parsed.pathname.endsWith('/messages')) {
      return jsonResponse({ messages: [message()], total: 1, limit: 25, offset: 0 });
    }
    if (parsed.pathname.endsWith('/stats')) {
      return jsonResponse(stats());
    }
    if (parsed.pathname.endsWith('/messages/retry')) {
      return jsonResponse({ results: { 'message-1': true }, success_count: 1, failure_count: 0 });
    }
    if (parsed.pathname.endsWith('/messages/discard')) {
      return jsonResponse({ results: { 'message-1': true }, success_count: 1, failure_count: 0 });
    }
    if (parsed.pathname.endsWith('/retry')) {
      return jsonResponse({ message_id: 'message-1', success: true });
    }
    if (parsed.pathname.endsWith('/cleanup/expired')) {
      return jsonResponse({ cleaned_count: 2 });
    }
    if (parsed.pathname.endsWith('/cleanup/resolved')) {
      return jsonResponse({ cleaned_count: 1 });
    }
    return jsonResponse({ message_id: 'message-1', success: true });
  };

  const client = createDeadLetterQueueHttpClient(runtimeConfig());
  const scope = cloudScope();
  const page = await client.listMessages(scope, {
    status: 'pending',
    eventType: 'episode.created',
    errorType: 'TimeoutError',
    routingKey: 'memory.episode',
    limit: 25,
    offset: 0,
  });
  const detail = await client.getMessage(scope, 'message-1');
  const queueStats = await client.getStats(scope);
  await client.retryMessage(scope, 'message-1');
  await client.retryMessages(scope, ['message-1']);
  await client.discardMessage(scope, 'message-1', 'operator reviewed');
  await client.discardMessages(scope, ['message-1'], 'operator reviewed');
  await client.cleanupExpired(scope, 168);
  await client.cleanupResolved(scope, 24);

  assert.equal(page.messages[0].eventType, 'episode.created');
  assert.equal(detail.id, 'message-1');
  assert.equal(queueStats.pendingCount, 1);
  assert.deepEqual(
    requests.map(({ path, method }) => [path, method]),
    [
      ['/api/v1/admin/dlq/messages', 'GET'],
      ['/api/v1/admin/dlq/messages/message-1', 'GET'],
      ['/api/v1/admin/dlq/stats', 'GET'],
      ['/api/v1/admin/dlq/messages/message-1/retry', 'POST'],
      ['/api/v1/admin/dlq/messages/retry', 'POST'],
      ['/api/v1/admin/dlq/messages/message-1', 'DELETE'],
      ['/api/v1/admin/dlq/messages/discard', 'POST'],
      ['/api/v1/admin/dlq/cleanup/expired', 'POST'],
      ['/api/v1/admin/dlq/cleanup/resolved', 'POST'],
    ],
  );
  assert.match(requests[0].search, /status=pending/u);
  assert.match(requests[0].search, /event_type=episode.created/u);
  assert.match(requests[0].search, /error_type=TimeoutError/u);
  assert.match(requests[0].search, /routing_key=memory.episode/u);
  assert.match(requests[5].search, /reason=operator\+reviewed/u);
  assert.deepEqual(requests[4].body, { message_ids: ['message-1'] });
  assert.deepEqual(requests[6].body, { message_ids: ['message-1'], reason: 'operator reviewed' });
  assert.equal(
    requests.every(({ authorization }) => authorization === 'Bearer test-token'),
    true,
  );
});

test('DLQ client rejects malformed authority payloads and invalid mutations', async () => {
  globalThis.fetch = async () => jsonResponse({ messages: [], total: -1, limit: 50, offset: 0 });
  const client = createDeadLetterQueueHttpClient(runtimeConfig());

  await assert.rejects(
    client.listMessages(cloudScope()),
    /cloud_dead_letter_queue_contract_invalid/u,
  );
  await assert.rejects(
    client.retryMessages(cloudScope(), []),
    /dead_letter_queue_message_ids_invalid/u,
  );
  await assert.rejects(
    client.discardMessage(cloudScope(), 'message-1', '   '),
    /dead_letter_queue_discard_reason_invalid/u,
  );
});

test('Local DLQ is stable not-applicable and performs zero Cloud requests', async () => {
  let fetchCalls = 0;
  globalThis.fetch = async () => {
    fetchCalls += 1;
    return jsonResponse({});
  };
  const client = createDeadLetterQueueHttpClient(
    runtimeConfig({ mode: 'local', apiBaseUrl: 'http://127.0.0.1:4777' }),
  );
  const scope = { authority: 'local', tenantId: 'tenant-1' };

  await assert.rejects(client.listMessages(scope), /cloud_message_bus_dlq_not_applicable/u);
  await assert.rejects(client.getStats(scope), /cloud_message_bus_dlq_not_applicable/u);
  assert.equal(fetchCalls, 0);
});

function runtimeConfig(overrides = {}) {
  return {
    mode: 'cloud',
    apiBaseUrl: 'https://memstack.test',
    deviceAuthorizationBaseUrl: 'https://memstack.test',
    apiKey: 'test-token',
    localApiToken: 'test-local-token',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: '',
    workspaceRoot: '/workspace',
    ...overrides,
  };
}

function cloudScope() {
  return { authority: 'cloud', tenantId: 'tenant-1' };
}

function message() {
  return {
    id: 'message-1',
    event_id: 'event-1',
    event_type: 'episode.created',
    event_data: '{"episode_id":"episode-1"}',
    routing_key: 'memory.episode',
    error: 'timed out',
    error_type: 'TimeoutError',
    error_traceback: null,
    retry_count: 1,
    max_retries: 3,
    first_failed_at: '2026-08-01T00:00:00Z',
    last_failed_at: '2026-08-01T00:01:00Z',
    next_retry_at: null,
    status: 'pending',
    metadata: { source: 'worker' },
    can_retry: true,
    age_seconds: 60,
  };
}

function stats() {
  return {
    total_messages: 1,
    pending_count: 1,
    retrying_count: 0,
    discarded_count: 0,
    expired_count: 0,
    resolved_count: 0,
    oldest_message_age_seconds: 60,
    error_type_counts: { TimeoutError: 1 },
    event_type_counts: { 'episode.created': 1 },
  };
}

function jsonResponse(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
