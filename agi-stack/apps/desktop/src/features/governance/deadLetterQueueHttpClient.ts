import {
  absoluteUrl,
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import {
  DeadLetterQueueUnavailableError,
  type DeadLetterQueueBatchResult,
  type DeadLetterQueueCleanupResult,
  type DeadLetterQueueClient,
  type DeadLetterQueueMessage,
  type DeadLetterQueueMessageStatus,
  type DeadLetterQueuePage,
  type DeadLetterQueueQuery,
  type DeadLetterQueueScope,
  type DeadLetterQueueStats,
} from './deadLetterQueueClient';

const BASE_PATH = '/api/v1/admin/dlq';
const CONTRACT_VERSION = '3.0.0';
const CLOUD_ACTIONS = Object.freeze([
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
]);
const MESSAGE_STATUSES = new Set<DeadLetterQueueMessageStatus>([
  'pending',
  'retrying',
  'discarded',
  'expired',
  'resolved',
]);

type RequestOptions = Readonly<{
  method: 'GET' | 'POST' | 'DELETE';
  signal?: AbortSignal;
  body?: Readonly<Record<string, unknown>>;
}>;

export function createDeadLetterQueueHttpClient(
  config: DesktopRuntimeConfig,
): DeadLetterQueueClient {
  const runtimeConfig = Object.freeze({ ...config });
  return Object.freeze({
    async listMessages(scope, query = {}, options) {
      requireCloudScope(runtimeConfig, scope);
      const normalized = normalizeQuery(query);
      const params = new URLSearchParams({
        limit: String(normalized.limit),
        offset: String(normalized.offset),
      });
      if (normalized.status !== 'all') params.set('status', normalized.status);
      if (normalized.eventType) params.set('event_type', normalized.eventType);
      if (normalized.errorType) params.set('error_type', normalized.errorType);
      if (normalized.routingKey) params.set('routing_key', normalized.routingKey);
      const payload = await requestJson(
        runtimeConfig,
        `${BASE_PATH}/messages?${params.toString()}`,
        { method: 'GET', signal: options?.signal },
      );
      return parsePage(payload, scope);
    },
    async getMessage(scope, messageId, options) {
      requireCloudScope(runtimeConfig, scope);
      const id = requireIdentifier(messageId, 'dead_letter_queue_message_id_invalid');
      const payload = await requestJson(
        runtimeConfig,
        `${BASE_PATH}/messages/${encodeURIComponent(id)}`,
        { method: 'GET', signal: options?.signal },
      );
      return parseMessage(payload);
    },
    async getStats(scope, options) {
      requireCloudScope(runtimeConfig, scope);
      const payload = await requestJson(runtimeConfig, `${BASE_PATH}/stats`, {
        method: 'GET',
        signal: options?.signal,
      });
      return parseStats(payload);
    },
    async retryMessage(scope, messageId, options) {
      requireCloudScope(runtimeConfig, scope);
      const id = requireIdentifier(messageId, 'dead_letter_queue_message_id_invalid');
      const payload = await requestJson(
        runtimeConfig,
        `${BASE_PATH}/messages/${encodeURIComponent(id)}/retry`,
        { method: 'POST', signal: options?.signal },
      );
      parseSingleMutation(payload, id);
    },
    async retryMessages(scope, messageIds, options) {
      requireCloudScope(runtimeConfig, scope);
      const ids = requireMessageIds(messageIds);
      const payload = await requestJson(runtimeConfig, `${BASE_PATH}/messages/retry`, {
        method: 'POST',
        signal: options?.signal,
        body: { message_ids: ids },
      });
      return parseBatchResult(payload, ids);
    },
    async discardMessage(scope, messageId, reason, options) {
      requireCloudScope(runtimeConfig, scope);
      const id = requireIdentifier(messageId, 'dead_letter_queue_message_id_invalid');
      const discardReason = requireDiscardReason(reason);
      const params = new URLSearchParams({ reason: discardReason });
      const payload = await requestJson(
        runtimeConfig,
        `${BASE_PATH}/messages/${encodeURIComponent(id)}?${params.toString()}`,
        { method: 'DELETE', signal: options?.signal },
      );
      parseSingleMutation(payload, id);
    },
    async discardMessages(scope, messageIds, reason, options) {
      requireCloudScope(runtimeConfig, scope);
      const ids = requireMessageIds(messageIds);
      const discardReason = requireDiscardReason(reason);
      const payload = await requestJson(runtimeConfig, `${BASE_PATH}/messages/discard`, {
        method: 'POST',
        signal: options?.signal,
        body: { message_ids: ids, reason: discardReason },
      });
      return parseBatchResult(payload, ids);
    },
    async cleanupExpired(scope, olderThanHours, options) {
      requireCloudScope(runtimeConfig, scope);
      return cleanup(
        runtimeConfig,
        'expired',
        integerInRange(olderThanHours, 1, 720, 'dead_letter_queue_cleanup_hours_invalid'),
        options?.signal,
      );
    },
    async cleanupResolved(scope, olderThanHours, options) {
      requireCloudScope(runtimeConfig, scope);
      return cleanup(
        runtimeConfig,
        'resolved',
        integerInRange(olderThanHours, 1, 168, 'dead_letter_queue_cleanup_hours_invalid'),
        options?.signal,
      );
    },
  });
}

async function cleanup(
  config: DesktopRuntimeConfig,
  kind: 'expired' | 'resolved',
  hours: number,
  signal?: AbortSignal,
): Promise<DeadLetterQueueCleanupResult> {
  const params = new URLSearchParams({ older_than_hours: String(hours) });
  const payload = await requestJson(config, `${BASE_PATH}/cleanup/${kind}?${params.toString()}`, {
    method: 'POST',
    signal,
  });
  if (!isRecord(payload) || !isNonnegativeInteger(payload.cleaned_count)) {
    throw contractError();
  }
  return Object.freeze({ cleanedCount: payload.cleaned_count });
}

async function requestJson(
  config: DesktopRuntimeConfig,
  path: string,
  options: RequestOptions,
): Promise<unknown> {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  if (options.body) headers.set('Content-Type', 'application/json');
  const response = await fetch(absoluteUrl(config.apiBaseUrl, path), {
    method: options.method,
    headers,
    signal: options.signal,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const contentType = response.headers.get('content-type') ?? '';
  const isJson = contentType.toLowerCase().includes('application/json');
  const payload = isJson
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '');
  if (!response.ok) {
    throw new DesktopApiError(errorMessage(response.status, payload), response.status, payload);
  }
  if (!isJson || payload === null) throw contractError();
  return payload;
}

function parsePage(payload: unknown, scope: DeadLetterQueueScope): DeadLetterQueuePage {
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.messages) ||
    !isNonnegativeInteger(payload.total) ||
    !isPositiveInteger(payload.limit) ||
    !isNonnegativeInteger(payload.offset)
  ) {
    throw contractError();
  }
  const messages = Object.freeze(payload.messages.map(parseMessage));
  if (messages.length > payload.limit) throw contractError();
  return Object.freeze({
    scope,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    serviceVersion: 'cloud',
    contractVersion: CONTRACT_VERSION,
    allowedActions: CLOUD_ACTIONS,
    authorityRevision: null,
    messages,
    total: payload.total,
    limit: payload.limit,
    offset: payload.offset,
    hasMore: payload.offset + messages.length < payload.total,
  });
}

function parseMessage(payload: unknown): DeadLetterQueueMessage {
  if (
    !isRecord(payload) ||
    !isNonEmptyString(payload.id) ||
    !isNonEmptyString(payload.event_id) ||
    !isNonEmptyString(payload.event_type) ||
    typeof payload.event_data !== 'string' ||
    !isNonEmptyString(payload.routing_key) ||
    typeof payload.error !== 'string' ||
    !isNonEmptyString(payload.error_type) ||
    !isNullableString(payload.error_traceback) ||
    !isNonnegativeInteger(payload.retry_count) ||
    !isNonnegativeInteger(payload.max_retries) ||
    !isNonEmptyString(payload.first_failed_at) ||
    !isNonEmptyString(payload.last_failed_at) ||
    !isNullableString(payload.next_retry_at) ||
    !isMessageStatus(payload.status) ||
    !isRecord(payload.metadata) ||
    typeof payload.can_retry !== 'boolean' ||
    !isFiniteNonnegative(payload.age_seconds)
  ) {
    throw contractError();
  }
  return Object.freeze({
    id: payload.id,
    eventId: payload.event_id,
    eventType: payload.event_type,
    eventData: payload.event_data,
    routingKey: payload.routing_key,
    error: payload.error,
    errorType: payload.error_type,
    errorTraceback: payload.error_traceback,
    retryCount: payload.retry_count,
    maxRetries: payload.max_retries,
    firstFailedAt: payload.first_failed_at,
    lastFailedAt: payload.last_failed_at,
    nextRetryAt: payload.next_retry_at,
    status: payload.status,
    metadata: Object.freeze({ ...payload.metadata }),
    canRetry: payload.can_retry,
    ageSeconds: payload.age_seconds,
  });
}

function parseStats(payload: unknown): DeadLetterQueueStats {
  if (
    !isRecord(payload) ||
    !isNonnegativeInteger(payload.total_messages) ||
    !isNonnegativeInteger(payload.pending_count) ||
    !isNonnegativeInteger(payload.retrying_count) ||
    !isNonnegativeInteger(payload.discarded_count) ||
    !isNonnegativeInteger(payload.expired_count) ||
    !isNonnegativeInteger(payload.resolved_count) ||
    !isFiniteNonnegative(payload.oldest_message_age_seconds) ||
    !isCountRecord(payload.error_type_counts) ||
    !isCountRecord(payload.event_type_counts)
  ) {
    throw contractError();
  }
  return Object.freeze({
    totalMessages: payload.total_messages,
    pendingCount: payload.pending_count,
    retryingCount: payload.retrying_count,
    discardedCount: payload.discarded_count,
    expiredCount: payload.expired_count,
    resolvedCount: payload.resolved_count,
    oldestMessageAgeSeconds: payload.oldest_message_age_seconds,
    errorTypeCounts: Object.freeze({ ...payload.error_type_counts }),
    eventTypeCounts: Object.freeze({ ...payload.event_type_counts }),
  });
}

function parseSingleMutation(payload: unknown, expectedId: string): void {
  if (!isRecord(payload) || payload.message_id !== expectedId || payload.success !== true) {
    throw contractError();
  }
}

function parseBatchResult(
  payload: unknown,
  expectedIds: readonly string[],
): DeadLetterQueueBatchResult {
  if (
    !isRecord(payload) ||
    !isBooleanRecord(payload.results) ||
    !isNonnegativeInteger(payload.success_count) ||
    !isNonnegativeInteger(payload.failure_count)
  ) {
    throw contractError();
  }
  const results = payload.results;
  const resultIds = Object.keys(results);
  if (
    resultIds.length !== expectedIds.length ||
    expectedIds.some((id) => !Object.hasOwn(results, id)) ||
    payload.success_count + payload.failure_count !== resultIds.length
  ) {
    throw contractError();
  }
  return Object.freeze({
    results: Object.freeze({ ...results }),
    successCount: payload.success_count,
    failureCount: payload.failure_count,
  });
}

function requireCloudScope(config: DesktopRuntimeConfig, scope: DeadLetterQueueScope): void {
  if (scope.authority === 'local' || config.mode === 'local') {
    throw new DeadLetterQueueUnavailableError('cloud_message_bus_dlq_not_applicable');
  }
  if (scope.authority !== 'cloud' || scope.tenantId !== config.tenantId || !scope.tenantId.trim()) {
    throw new DeadLetterQueueUnavailableError('dead_letter_queue_runtime_scope_mismatch');
  }
}

function normalizeQuery(query: DeadLetterQueueQuery) {
  const status = query.status ?? 'all';
  if (status !== 'all' && !MESSAGE_STATUSES.has(status)) {
    throw new Error('dead_letter_queue_status_invalid');
  }
  return Object.freeze({
    status,
    eventType: optionalFilter(query.eventType),
    errorType: optionalFilter(query.errorType),
    routingKey: optionalFilter(query.routingKey),
    limit: integerInRange(query.limit ?? 50, 1, 100, 'dead_letter_queue_limit_invalid'),
    offset: integerInRange(
      query.offset ?? 0,
      0,
      Number.MAX_SAFE_INTEGER,
      'dead_letter_queue_offset_invalid',
    ),
  });
}

function requireMessageIds(input: readonly string[]): readonly string[] {
  if (!Array.isArray(input) || input.length < 1 || input.length > 100) {
    throw new Error('dead_letter_queue_message_ids_invalid');
  }
  const ids = input.map((id) => requireIdentifier(id, 'dead_letter_queue_message_ids_invalid'));
  if (new Set(ids).size !== ids.length) {
    throw new Error('dead_letter_queue_message_ids_invalid');
  }
  return Object.freeze(ids);
}

function requireDiscardReason(input: string): string {
  const reason = typeof input === 'string' ? input.trim() : '';
  if (!reason || reason.length > 500) {
    throw new Error('dead_letter_queue_discard_reason_invalid');
  }
  return reason;
}

function requireIdentifier(input: string, reason: string): string {
  if (typeof input !== 'string' || !input.trim() || input !== input.trim()) {
    throw new Error(reason);
  }
  return input;
}

function optionalFilter(input: string | undefined): string {
  if (input === undefined) return '';
  if (typeof input !== 'string' || input.length > 200) {
    throw new Error('dead_letter_queue_filter_invalid');
  }
  return input.trim();
}

function integerInRange(input: number, minimum: number, maximum: number, reason: string): number {
  if (!Number.isInteger(input) || input < minimum || input > maximum) {
    throw new Error(reason);
  }
  return input;
}

function contractError(): DesktopApiError {
  return new DesktopApiError('cloud_dead_letter_queue_contract_invalid', 502, {
    reason_code: 'cloud_dead_letter_queue_contract_invalid',
  });
}

function errorMessage(status: number, payload: unknown): string {
  if (isRecord(payload) && typeof payload.detail === 'string') {
    return payload.detail;
  }
  return `HTTP ${status}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isNonnegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) > 0;
}

function isFiniteNonnegative(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}

function isMessageStatus(value: unknown): value is DeadLetterQueueMessageStatus {
  return typeof value === 'string' && MESSAGE_STATUSES.has(value as DeadLetterQueueMessageStatus);
}

function isCountRecord(value: unknown): value is Record<string, number> {
  return (
    isRecord(value) &&
    Object.entries(value).every(
      ([key, count]) => key.trim().length > 0 && isNonnegativeInteger(count),
    )
  );
}

function isBooleanRecord(value: unknown): value is Record<string, boolean> {
  return (
    isRecord(value) &&
    Object.entries(value).every(
      ([key, result]) => key.trim().length > 0 && typeof result === 'boolean',
    )
  );
}
