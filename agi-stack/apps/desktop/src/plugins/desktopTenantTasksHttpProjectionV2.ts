import { DesktopApiError } from '../api/client';
import type {
  CloudTenantTasksScope,
  LocalTenantTasksScope,
  TenantTaskRecord,
  TenantTaskStats,
  TenantTasksQuery,
  TenantTasksRetryPendingResult,
  TenantTasksSnapshot,
} from '../features/tenant/tenantTasksClient';

export const DESKTOP_TENANT_TASKS_CLOUD_ACTIONS_V2 = Object.freeze([
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
export const DESKTOP_TENANT_TASKS_LOCAL_ACTIONS_V2 = Object.freeze([
  'view',
  'list',
  'search',
  'filter',
  'paginate',
  'refresh',
  'open-workspace',
]);

export function projectDesktopTenantTasksCloudSnapshotV2(
  statsPayload: unknown,
  queuePayload: unknown,
  tasksPayload: unknown,
  scope: CloudTenantTasksScope,
  query: Required<TenantTasksQuery>,
): TenantTasksSnapshot {
  const page = cloudTaskPageV2(tasksPayload, scope, query);
  return Object.freeze({
    scope,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    serviceVersion: 'cloud',
    contractVersion: '3.0.0',
    allowedActions: DESKTOP_TENANT_TASKS_CLOUD_ACTIONS_V2,
    authorityRevision: null,
    stats: cloudStatsV2(statsPayload),
    queue: queueProjectionV2(queuePayload, 'cloud_tenant_tasks_contract_invalid'),
    ...page,
  });
}

export function projectDesktopTenantTasksLocalSnapshotV2(
  payload: unknown,
  scope: LocalTenantTasksScope,
  query: Required<TenantTasksQuery>,
): TenantTasksSnapshot {
  const allTasks = localTasksV2(payload, scope);
  const search = query.search.toLocaleLowerCase();
  const filtered = allTasks.filter((task) => {
    const searchMatches =
      !search ||
      task.id.toLocaleLowerCase().includes(search) ||
      task.name.toLocaleLowerCase().includes(search);
    return searchMatches && (query.status === 'all' || task.status === query.status);
  });
  const tasks = Object.freeze(filtered.slice(query.offset, query.offset + query.limit));
  const stats = localStatsV2(allTasks);
  return Object.freeze({
    scope,
    authority: 'local',
    availability: 'degraded',
    reasonCode: 'local_task_dashboard_partial',
    serviceVersion: '0.1.0',
    contractVersion: '3.0.0',
    allowedActions: DESKTOP_TENANT_TASKS_LOCAL_ACTIONS_V2,
    authorityRevision: null,
    stats,
    queue: Object.freeze({
      current: stats.pending + stats.processing,
      history: Object.freeze([]),
    }),
    tasks,
    total: filtered.length,
    limit: query.limit,
    offset: query.offset,
    hasMore: query.offset + tasks.length < filtered.length,
  });
}

export function projectDesktopTenantTasksRetryPendingResultV2(
  payload: unknown,
): TenantTasksRetryPendingResult {
  const reason = 'cloud_tenant_tasks_contract_invalid';
  if (
    !isRecordV2(payload) ||
    !isNonnegativeIntegerV2(payload.submitted) ||
    !isNonnegativeIntegerV2(payload.skipped) ||
    !isPositiveIntegerV2(payload.limit) ||
    !isStringArrayV2(payload.task_ids)
  ) {
    throw tenantTasksContractErrorV2(reason);
  }
  return Object.freeze({
    submitted: payload.submitted,
    skipped: payload.skipped,
    limit: payload.limit,
    taskIds: Object.freeze([...payload.task_ids]),
  });
}

export function desktopTenantTasksLoadPathsV2(
  scope: CloudTenantTasksScope,
  query: Required<TenantTasksQuery>,
): Readonly<{ stats: string; queue: string; recent: string }> {
  void scope;
  const params = new URLSearchParams({
    limit: String(query.limit),
    offset: String(query.offset),
  });
  if (query.search) params.set('search', query.search);
  if (query.status !== 'all') params.set('status', query.status);
  return Object.freeze({
    stats: '/api/v1/tasks/stats',
    queue: '/api/v1/tasks/queue-depth',
    recent: `/api/v1/tasks/recent?${params.toString()}`,
  });
}

export function tenantTasksContractErrorV2(reason: string): DesktopApiError {
  return new DesktopApiError(reason, 502, { reason_code: reason });
}

function cloudStatsV2(payload: unknown): TenantTaskStats {
  const reason = 'cloud_tenant_tasks_contract_invalid';
  if (
    !isRecordV2(payload) ||
    !isNonnegativeIntegerV2(payload.total) ||
    !isNonnegativeIntegerV2(payload.pending) ||
    !isNonnegativeIntegerV2(payload.processing) ||
    !isNonnegativeIntegerV2(payload.completed) ||
    !isNonnegativeIntegerV2(payload.failed) ||
    !isFiniteNonnegativeV2(payload.throughput_per_minute) ||
    !isFiniteNonnegativeV2(payload.error_rate)
  ) {
    throw tenantTasksContractErrorV2(reason);
  }
  return Object.freeze({
    total: payload.total,
    pending: payload.pending,
    processing: payload.processing,
    completed: payload.completed,
    failed: payload.failed,
    throughputPerMinute: payload.throughput_per_minute,
    errorRate: payload.error_rate,
  });
}

function queueProjectionV2(payload: unknown, reason: string) {
  if (!Array.isArray(payload)) throw tenantTasksContractErrorV2(reason);
  const history = Object.freeze(
    payload.map((point) => {
      if (
        !isRecordV2(point) ||
        !isCanonicalStringV2(point.timestamp) ||
        !isNonnegativeIntegerV2(point.depth)
      ) {
        throw tenantTasksContractErrorV2(reason);
      }
      return Object.freeze({ timestamp: point.timestamp, depth: point.depth });
    }),
  );
  return Object.freeze({ current: history.at(-1)?.depth ?? 0, history });
}

function cloudTaskPageV2(
  payload: unknown,
  scope: CloudTenantTasksScope,
  query: Required<TenantTasksQuery>,
) {
  const reason = 'cloud_tenant_tasks_contract_invalid';
  if (
    !isRecordV2(payload) ||
    !Array.isArray(payload.tasks) ||
    !isNonnegativeIntegerV2(payload.total) ||
    !isNonnegativeIntegerV2(payload.offset) ||
    !isPositiveIntegerV2(payload.limit) ||
    typeof payload.has_more !== 'boolean' ||
    payload.limit !== query.limit ||
    payload.offset !== query.offset
  ) {
    throw tenantTasksContractErrorV2(reason);
  }
  return Object.freeze({
    tasks: Object.freeze(payload.tasks.map((task) => cloudTaskV2(task, scope, reason))),
    total: payload.total,
    limit: payload.limit,
    offset: payload.offset,
    hasMore: payload.has_more,
  });
}

function cloudTaskV2(
  payload: unknown,
  scope: CloudTenantTasksScope,
  reason: string,
): TenantTaskRecord {
  void scope;
  if (
    !isRecordV2(payload) ||
    !isCanonicalStringV2(payload.id) ||
    !isCanonicalStringV2(payload.status) ||
    !isCanonicalStringV2(payload.created_at)
  ) {
    throw tenantTasksContractErrorV2(reason);
  }
  const status = payload.status.toLocaleLowerCase();
  const taskType =
    optionalCanonicalStringV2(payload.task_type) ??
    optionalCanonicalStringV2(payload.name) ??
    payload.id;
  return Object.freeze({
    id: payload.id,
    projectId: null,
    workspaceId: null,
    conversationId: null,
    taskType,
    name: optionalCanonicalStringV2(payload.name) ?? taskType,
    status,
    createdAt: payload.created_at,
    completedAt: optionalCanonicalStringV2(payload.completed_at),
    error: optionalCanonicalStringV2(payload.error),
    duration: optionalCanonicalStringV2(payload.duration),
    entityId: optionalCanonicalStringV2(payload.entity_id),
    entityType: optionalCanonicalStringV2(payload.entity_type),
    revision: null,
    canRetry: status === 'failed' || (status === 'pending' && taskType === 'add_episode'),
    canStop: status === 'pending' || status === 'processing',
  });
}

function localTasksV2(
  payload: unknown,
  scope: LocalTenantTasksScope,
): readonly TenantTaskRecord[] {
  const reason = 'local_tenant_tasks_contract_invalid';
  if (
    !isRecordV2(payload) ||
    payload.project_id !== scope.projectId ||
    !Array.isArray(payload.items) ||
    !isNonnegativeIntegerV2(payload.total) ||
    payload.total !== payload.items.length
  ) {
    throw tenantTasksContractErrorV2(reason);
  }
  return Object.freeze(
    payload.items.map((item) => {
      if (
        !isRecordV2(item) ||
        !isCanonicalStringV2(item.id) ||
        item.project_id !== scope.projectId ||
        !isCanonicalStringV2(item.title) ||
        !isCanonicalStringV2(item.group) ||
        !isCanonicalStringV2(item.status) ||
        !isCanonicalStringV2(item.created_at)
      ) {
        throw tenantTasksContractErrorV2(reason);
      }
      return Object.freeze({
        id: item.id,
        projectId: scope.projectId,
        workspaceId: optionalCanonicalStringV2(item.workspace_id),
        conversationId: optionalCanonicalStringV2(item.conversation_id),
        taskType: optionalCanonicalStringV2(item.authority_kind) ?? 'local_work',
        name: item.title,
        status: localStatusV2(item.group),
        createdAt: item.created_at,
        completedAt: null,
        error: optionalCanonicalStringV2(item.error),
        duration: null,
        entityId: null,
        entityType: null,
        revision: isNonnegativeIntegerV2(item.revision) ? item.revision : null,
        canRetry: false,
        canStop: false,
      });
    }),
  );
}

function localStatsV2(tasks: readonly TenantTaskRecord[]): TenantTaskStats {
  const count = (status: string): number =>
    tasks.filter((task) => task.status === status).length;
  return Object.freeze({
    total: tasks.length,
    pending: count('pending'),
    processing: count('processing'),
    completed: count('completed'),
    failed: count('failed'),
    throughputPerMinute: 0,
    errorRate: 0,
  });
}

function localStatusV2(group: string): string {
  if (group === 'running') return 'processing';
  if (group === 'ready_review') return 'completed';
  return 'pending';
}

function optionalCanonicalStringV2(value: unknown): string | null {
  return isCanonicalStringV2(value) ? value : null;
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

function isStringArrayV2(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isCanonicalStringV2);
}

function isRecordV2(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
