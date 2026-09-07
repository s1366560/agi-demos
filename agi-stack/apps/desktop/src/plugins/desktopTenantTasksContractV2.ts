import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  TenantTaskQueuePoint,
  TenantTaskRecord,
  TenantTasksRetryPendingResult,
  TenantTasksScope,
  TenantTasksSnapshot,
} from '../features/tenant/tenantTasksClient';

const SNAPSHOT_KEYS_V2 = new Set([
  'scope',
  'authority',
  'availability',
  'reasonCode',
  'serviceVersion',
  'contractVersion',
  'allowedActions',
  'authorityRevision',
  'stats',
  'queue',
  'tasks',
  'total',
  'limit',
  'offset',
  'hasMore',
]);
const STATS_KEYS_V2 = new Set([
  'total',
  'pending',
  'processing',
  'completed',
  'failed',
  'throughputPerMinute',
  'errorRate',
]);
const QUEUE_KEYS_V2 = new Set(['current', 'history']);
const QUEUE_POINT_KEYS_V2 = new Set(['timestamp', 'depth']);
const TASK_KEYS_V2 = new Set([
  'id',
  'projectId',
  'workspaceId',
  'conversationId',
  'taskType',
  'name',
  'status',
  'createdAt',
  'completedAt',
  'error',
  'duration',
  'entityId',
  'entityType',
  'revision',
  'canRetry',
  'canStop',
]);
const RETRY_PENDING_KEYS_V2 = new Set(['submitted', 'skipped', 'limit', 'taskIds']);
const CLOUD_ACTIONS_V2 = Object.freeze([
  'view',
  'list',
  'search',
  'filter',
  'paginate',
  'refresh',
  'retry-task',
  'stop-task',
  'retry-pending',
  'navigate-dead-letter-queue',
]);
const LOCAL_ACTIONS_V2 = Object.freeze([
  'view',
  'list',
  'search',
  'filter',
  'paginate',
  'refresh',
  'open-workspace',
]);

export function requireDesktopTenantTasksSnapshotV2(
  value: unknown,
  expectedScope: TenantTasksScope,
): TenantTasksSnapshot {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, SNAPSHOT_KEYS_V2) ||
    value.authority !== expectedScope.authority ||
    !sameScopeV2(value.scope, expectedScope) ||
    !isAvailabilityV2(value.availability) ||
    !isNullableCanonicalStringV2(value.reasonCode) ||
    !isCanonicalStringV2(value.serviceVersion) ||
    !isCanonicalStringV2(value.contractVersion) ||
    !isOrderedSubsetV2(
      value.allowedActions,
      expectedScope.authority === 'cloud' ? CLOUD_ACTIONS_V2 : LOCAL_ACTIONS_V2,
    ) ||
    !(value.authorityRevision === null || isNonnegativeIntegerV2(value.authorityRevision)) ||
    !isPlainRecordV2(value.stats) ||
    !hasExactKeysV2(value.stats, STATS_KEYS_V2) ||
    !isNonnegativeIntegerV2(value.stats.total) ||
    !isNonnegativeIntegerV2(value.stats.pending) ||
    !isNonnegativeIntegerV2(value.stats.processing) ||
    !isNonnegativeIntegerV2(value.stats.completed) ||
    !isNonnegativeIntegerV2(value.stats.failed) ||
    !isFiniteNonnegativeV2(value.stats.throughputPerMinute) ||
    !isFiniteNonnegativeV2(value.stats.errorRate) ||
    !isPlainRecordV2(value.queue) ||
    !hasExactKeysV2(value.queue, QUEUE_KEYS_V2) ||
    !isNonnegativeIntegerV2(value.queue.current) ||
    !Array.isArray(value.queue.history) ||
    !Array.isArray(value.tasks) ||
    !isNonnegativeIntegerV2(value.total) ||
    !isPositiveIntegerV2(value.limit) ||
    !isNonnegativeIntegerV2(value.offset) ||
    typeof value.hasMore !== 'boolean'
  ) {
    throw invalidServiceContractV2();
  }
  const history = Object.freeze(value.queue.history.map(requireQueuePointV2));
  const tasks = Object.freeze(
    value.tasks.map((task) => requireDesktopTenantTaskRecordV2(task, expectedScope)),
  );
  if (value.availability === 'unavailable' && (value.allowedActions.length || tasks.length)) {
    throw invalidServiceContractV2();
  }
  return Object.freeze({
    scope: cloneScopeV2(expectedScope),
    authority: expectedScope.authority,
    availability: value.availability,
    reasonCode: value.reasonCode,
    serviceVersion: value.serviceVersion,
    contractVersion: value.contractVersion,
    allowedActions: Object.freeze([...value.allowedActions]),
    authorityRevision: value.authorityRevision,
    stats: Object.freeze({ ...value.stats }),
    queue: Object.freeze({ current: value.queue.current, history }),
    tasks,
    total: value.total,
    limit: value.limit,
    offset: value.offset,
    hasMore: value.hasMore,
  }) as TenantTasksSnapshot;
}

export function requireDesktopTenantTaskRecordV2(
  value: unknown,
  expectedScope: TenantTasksScope,
): TenantTaskRecord {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, TASK_KEYS_V2) ||
    !isCanonicalStringV2(value.id) ||
    value.projectId !== expectedScope.projectId ||
    !isNullableCanonicalStringV2(value.workspaceId) ||
    !isNullableCanonicalStringV2(value.conversationId) ||
    !isCanonicalStringV2(value.taskType) ||
    !isCanonicalStringV2(value.name) ||
    !isCanonicalStringV2(value.status) ||
    !isCanonicalStringV2(value.createdAt) ||
    !isNullableCanonicalStringV2(value.completedAt) ||
    !isNullableCanonicalStringV2(value.error) ||
    !isNullableCanonicalStringV2(value.duration) ||
    !isNullableCanonicalStringV2(value.entityId) ||
    !isNullableCanonicalStringV2(value.entityType) ||
    !(value.revision === null || isNonnegativeIntegerV2(value.revision)) ||
    typeof value.canRetry !== 'boolean' ||
    typeof value.canStop !== 'boolean'
  ) {
    throw invalidServiceContractV2();
  }
  return Object.freeze({ ...value }) as TenantTaskRecord;
}

export function requireDesktopTenantTasksRetryPendingResultV2(
  value: unknown,
): TenantTasksRetryPendingResult {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, RETRY_PENDING_KEYS_V2) ||
    !isNonnegativeIntegerV2(value.submitted) ||
    !isNonnegativeIntegerV2(value.skipped) ||
    !isPositiveIntegerV2(value.limit) ||
    !Array.isArray(value.taskIds) ||
    !value.taskIds.every(isCanonicalStringV2)
  ) {
    throw invalidServiceContractV2();
  }
  return Object.freeze({
    submitted: value.submitted,
    skipped: value.skipped,
    limit: value.limit,
    taskIds: Object.freeze([...value.taskIds]),
  });
}

function requireQueuePointV2(value: unknown): TenantTaskQueuePoint {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, QUEUE_POINT_KEYS_V2) ||
    !isCanonicalStringV2(value.timestamp) ||
    !isNonnegativeIntegerV2(value.depth)
  ) {
    throw invalidServiceContractV2();
  }
  return Object.freeze({ timestamp: value.timestamp, depth: value.depth });
}

function sameScopeV2(value: unknown, expected: TenantTasksScope): boolean {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, new Set(['authority', 'tenantId', 'projectId'])) &&
    value.authority === expected.authority &&
    value.tenantId === expected.tenantId &&
    value.projectId === expected.projectId
  );
}

function cloneScopeV2(scope: TenantTasksScope): TenantTasksScope {
  return scope.authority === 'cloud'
    ? Object.freeze({ authority: 'cloud', tenantId: scope.tenantId, projectId: null })
    : Object.freeze({
        authority: 'local',
        tenantId: scope.tenantId,
        projectId: scope.projectId,
      });
}

function isOrderedSubsetV2(value: unknown, order: readonly string[]): value is string[] {
  if (!Array.isArray(value)) return false;
  let previous = -1;
  for (const action of value) {
    const index = order.indexOf(action);
    if (index <= previous) return false;
    previous = index;
  }
  return true;
}

function isAvailabilityV2(value: unknown): value is TenantTasksSnapshot['availability'] {
  return value === 'available' || value === 'degraded' || value === 'unavailable';
}

function isNullableCanonicalStringV2(value: unknown): value is string | null {
  return value === null || isCanonicalStringV2(value);
}

function isCanonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isNonnegativeIntegerV2(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function isPositiveIntegerV2(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) > 0;
}

function isFiniteNonnegativeV2(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}

function hasExactKeysV2(
  value: Record<string, unknown>,
  expected: ReadonlySet<string>,
): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function invalidServiceContractV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_tasks_service_contract_invalid',
    'desktop tenant tasks authority returned an invalid contract',
  );
}
