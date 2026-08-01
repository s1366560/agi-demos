import {
  absoluteUrl,
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import type {
  TenantTaskRecord,
  TenantTaskStats,
  TenantTasksClient,
  TenantTasksQuery,
  TenantTasksScope,
  TenantTasksSnapshot,
} from './tenantTasksClient';

const CLOUD_ACTIONS = Object.freeze([
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
const LOCAL_ACTIONS = Object.freeze([
  'view',
  'list',
  'search',
  'filter',
  'paginate',
  'refresh',
  'open-workspace',
]);
const DEFAULT_LIMIT = 50;
const MAX_LIMIT = 100;

export function createTenantTasksHttpClient(
  config: DesktopRuntimeConfig,
): TenantTasksClient {
  const runtimeConfig = Object.freeze({ ...config });
  return Object.freeze({
    async load(scope, query = {}, options) {
      requireRuntimeScope(runtimeConfig, scope);
      const normalized = normalizeQuery(query);
      return scope.authority === 'cloud'
        ? loadCloud(runtimeConfig, scope, normalized, options?.signal)
        : loadLocal(runtimeConfig, scope, normalized, options?.signal);
    },
    async retryTask(scope, task, options) {
      requireRuntimeScope(runtimeConfig, scope);
      requireTaskScope(scope, task);
      requireCloudMutation(scope, 'retry-task');
      await requestJson(
        runtimeConfig,
        `/api/v1/tasks/${encodeURIComponent(task.id)}/retry`,
        {
          method: 'POST',
          signal: options?.signal,
        },
      );
    },
    async stopTask(scope, task, options) {
      requireRuntimeScope(runtimeConfig, scope);
      requireTaskScope(scope, task);
      requireCloudMutation(scope, 'stop-task');
      await requestJson(
        runtimeConfig,
        `/api/v1/tasks/${encodeURIComponent(task.id)}/stop`,
        {
          method: 'POST',
          signal: options?.signal,
        },
      );
    },
    async retryPending(scope, limit, options) {
      requireRuntimeScope(runtimeConfig, scope);
      requireCloudMutation(scope, 'retry-pending');
      const boundedLimit = integerInRange(
        limit,
        1,
        10,
        'tenant_tasks_retry_limit_invalid',
      );
      const params = new URLSearchParams({ limit: String(boundedLimit) });
      const payload = await requestJson(
        runtimeConfig,
        `/api/v1/tasks/retry-pending?${params.toString()}`,
        { method: 'POST', signal: options?.signal },
      );
      return retryPendingResult(payload);
    },
  });
}

async function loadCloud(
  config: DesktopRuntimeConfig,
  scope: TenantTasksScope,
  query: Required<TenantTasksQuery>,
  signal?: AbortSignal,
): Promise<TenantTasksSnapshot> {
  const params = new URLSearchParams({
    limit: String(query.limit),
    offset: String(query.offset),
  });
  if (query.search) params.set('search', query.search);
  if (query.status !== 'all') params.set('status', query.status);
  const [statsPayload, queuePayload, tasksPayload] = await Promise.all([
    requestJson(config, '/api/v1/tasks/stats', { method: 'GET', signal }),
    requestJson(config, '/api/v1/tasks/queue-depth', { method: 'GET', signal }),
    requestJson(config, `/api/v1/tasks/recent?${params.toString()}`, {
      method: 'GET',
      signal,
    }),
  ]);
  const stats = cloudStats(statsPayload);
  const queue = queueProjection(
    queuePayload,
    'cloud_tenant_tasks_contract_invalid',
  );
  const page = cloudTaskPage(tasksPayload, scope, query);
  return Object.freeze({
    scope,
    authority: scope.authority,
    availability: 'available',
    reasonCode: null,
    serviceVersion: 'cloud',
    contractVersion: '3.0.0',
    allowedActions: CLOUD_ACTIONS,
    authorityRevision: null,
    stats,
    queue,
    ...page,
  });
}

async function loadLocal(
  config: DesktopRuntimeConfig,
  scope: TenantTasksScope,
  query: Required<TenantTasksQuery>,
  signal?: AbortSignal,
): Promise<TenantTasksSnapshot> {
  const payload = await requestJson(
    config,
    `/api/v1/projects/${encodeURIComponent(scope.projectId)}/my-work`,
    { method: 'GET', signal },
  );
  const allTasks = localTasks(payload, scope);
  const filtered = allTasks.filter((task) => {
    const searchMatches =
      !query.search ||
      task.id.toLocaleLowerCase().includes(query.search.toLocaleLowerCase()) ||
      task.name.toLocaleLowerCase().includes(query.search.toLocaleLowerCase());
    return (
      searchMatches && (query.status === 'all' || task.status === query.status)
    );
  });
  const tasks = Object.freeze(
    filtered.slice(query.offset, query.offset + query.limit),
  );
  const stats = localStats(allTasks);
  return Object.freeze({
    scope,
    authority: scope.authority,
    availability: 'degraded',
    reasonCode: 'local_task_dashboard_partial',
    serviceVersion: '0.1.0',
    contractVersion: '3.0.0',
    allowedActions: LOCAL_ACTIONS,
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

type RequestOptions = Readonly<{
  method: 'GET' | 'POST';
  signal?: AbortSignal;
}>;

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
  const response = await fetch(absoluteUrl(config.apiBaseUrl, path), {
    method: options.method,
    headers,
    signal: options.signal,
  });
  const contentType = response.headers.get('content-type') ?? '';
  const isJson = contentType.toLowerCase().includes('application/json');
  const payload = isJson
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '');
  if (!response.ok) {
    throw new DesktopApiError(
      errorMessage(response.status, payload),
      response.status,
      payload,
    );
  }
  if (!isJson || payload === null) {
    throw contractError(`${config.mode}_tenant_tasks_contract_invalid`);
  }
  return payload;
}

function cloudStats(payload: unknown): TenantTaskStats {
  const reason = 'cloud_tenant_tasks_contract_invalid';
  if (
    !isRecord(payload) ||
    !isNonnegativeInteger(payload.total) ||
    !isNonnegativeInteger(payload.pending) ||
    !isNonnegativeInteger(payload.processing) ||
    !isNonnegativeInteger(payload.completed) ||
    !isNonnegativeInteger(payload.failed) ||
    !isFiniteNonnegative(payload.throughput_per_minute) ||
    !isFiniteNonnegative(payload.error_rate)
  ) {
    throw contractError(reason);
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

function queueProjection(payload: unknown, reason: string) {
  if (!Array.isArray(payload)) throw contractError(reason);
  const history = Object.freeze(
    payload.map((point) => {
      if (
        !isRecord(point) ||
        !isNonEmptyString(point.timestamp) ||
        !isNonnegativeInteger(point.depth)
      ) {
        throw contractError(reason);
      }
      return Object.freeze({ timestamp: point.timestamp, depth: point.depth });
    }),
  );
  return Object.freeze({
    current: history.at(-1)?.depth ?? 0,
    history,
  });
}

function cloudTaskPage(
  payload: unknown,
  scope: TenantTasksScope,
  query: Required<TenantTasksQuery>,
) {
  const reason = 'cloud_tenant_tasks_contract_invalid';
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.tasks) ||
    !isNonnegativeInteger(payload.total) ||
    !isNonnegativeInteger(payload.offset) ||
    !isPositiveInteger(payload.limit) ||
    typeof payload.has_more !== 'boolean'
  ) {
    throw contractError(reason);
  }
  if (payload.limit !== query.limit || payload.offset !== query.offset)
    throw contractError(reason);
  return Object.freeze({
    tasks: Object.freeze(
      payload.tasks.map((task) => cloudTask(task, scope, reason)),
    ),
    total: payload.total,
    limit: payload.limit,
    offset: payload.offset,
    hasMore: payload.has_more,
  });
}

function cloudTask(
  payload: unknown,
  scope: TenantTasksScope,
  reason: string,
): TenantTaskRecord {
  if (
    !isRecord(payload) ||
    !isNonEmptyString(payload.id) ||
    !isNonEmptyString(payload.status) ||
    !isNonEmptyString(payload.created_at)
  ) {
    throw contractError(reason);
  }
  const status = payload.status.toLocaleLowerCase();
  const taskType =
    optionalString(payload.task_type) ??
    optionalString(payload.name) ??
    payload.id;
  return Object.freeze({
    id: payload.id,
    projectId: null,
    workspaceId: null,
    conversationId: null,
    taskType,
    name: optionalString(payload.name) ?? taskType,
    status,
    createdAt: payload.created_at,
    completedAt: optionalString(payload.completed_at),
    error: optionalString(payload.error),
    duration: optionalString(payload.duration),
    entityId: optionalString(payload.entity_id),
    entityType: optionalString(payload.entity_type),
    revision: null,
    canRetry:
      status === 'failed' ||
      (status === 'pending' && taskType === 'add_episode'),
    canStop: status === 'pending' || status === 'processing',
  });
}

function localTasks(
  payload: unknown,
  scope: TenantTasksScope,
): readonly TenantTaskRecord[] {
  const reason = 'local_tenant_tasks_contract_invalid';
  if (
    !isRecord(payload) ||
    payload.project_id !== scope.projectId ||
    !Array.isArray(payload.items) ||
    !isNonnegativeInteger(payload.total) ||
    payload.total !== payload.items.length
  ) {
    throw contractError(reason);
  }
  return Object.freeze(
    payload.items.map((item) => {
      if (
        !isRecord(item) ||
        !isNonEmptyString(item.id) ||
        item.project_id !== scope.projectId ||
        !isNonEmptyString(item.title) ||
        !isNonEmptyString(item.group) ||
        !isNonEmptyString(item.status) ||
        !isNonEmptyString(item.created_at)
      ) {
        throw contractError(reason);
      }
      return Object.freeze({
        id: item.id,
        projectId: scope.projectId,
        workspaceId: optionalString(item.workspace_id),
        conversationId: optionalString(item.conversation_id),
        taskType: isNonEmptyString(item.authority_kind)
          ? item.authority_kind
          : 'local_work',
        name: item.title,
        status: localStatus(item.group),
        createdAt: item.created_at,
        completedAt: null,
        error: optionalString(item.error),
        duration: null,
        entityId: null,
        entityType: null,
        revision: isNonnegativeInteger(item.revision) ? item.revision : null,
        canRetry: false,
        canStop: false,
      });
    }),
  );
}

function localStats(tasks: readonly TenantTaskRecord[]): TenantTaskStats {
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

function localStatus(group: string): string {
  if (group === 'running') return 'processing';
  if (group === 'ready_review') return 'completed';
  return 'pending';
}

function retryPendingResult(payload: unknown) {
  const reason = 'cloud_tenant_tasks_contract_invalid';
  if (
    !isRecord(payload) ||
    !isNonnegativeInteger(payload.submitted) ||
    !isNonnegativeInteger(payload.skipped) ||
    !isPositiveInteger(payload.limit) ||
    !isStringArray(payload.task_ids)
  ) {
    throw contractError(reason);
  }
  return Object.freeze({
    submitted: payload.submitted,
    skipped: payload.skipped,
    limit: payload.limit,
    taskIds: Object.freeze([...payload.task_ids]),
  });
}

function normalizeQuery(query: TenantTasksQuery): Required<TenantTasksQuery> {
  return Object.freeze({
    search: query.search?.trim() ?? '',
    status: query.status?.trim().toLocaleLowerCase() || 'all',
    limit: integerInRange(
      query.limit ?? DEFAULT_LIMIT,
      1,
      MAX_LIMIT,
      'tenant_tasks_limit_invalid',
    ),
    offset: integerInRange(
      query.offset ?? 0,
      0,
      Number.MAX_SAFE_INTEGER,
      'tenant_tasks_offset_invalid',
    ),
  });
}

function requireRuntimeScope(
  config: DesktopRuntimeConfig,
  scope: TenantTasksScope,
): void {
  if (
    config.mode !== scope.authority ||
    config.tenantId !== scope.tenantId ||
    config.projectId !== scope.projectId
  ) {
    throw new Error('tenant_tasks_runtime_scope_mismatch');
  }
}

function requireTaskScope(
  scope: TenantTasksScope,
  task: TenantTaskRecord,
): void {
  const scopeMatches =
    scope.authority === 'cloud'
      ? task.projectId === null
      : task.projectId === scope.projectId;
  if (!scopeMatches)
    throw new Error('tenant_tasks_task_scope_mismatch');
}

function requireCloudMutation(scope: TenantTasksScope, action: string): void {
  if (scope.authority !== 'cloud')
    throw new Error(`local_task_mutation_unavailable:${action}`);
}

function integerInRange(
  value: number,
  min: number,
  max: number,
  reason: string,
): number {
  if (!Number.isInteger(value) || value < min || value > max)
    throw new Error(reason);
  return value;
}

function optionalString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && Boolean(value.trim());
}

function isNonnegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) > 0;
}

function isFiniteNonnegative(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isNonEmptyString);
}

function contractError(reason: string): DesktopApiError {
  return new DesktopApiError(reason, 502, { reason_code: reason });
}

function errorMessage(status: number, payload: unknown): string {
  if (
    isRecord(payload) &&
    typeof payload.detail === 'string' &&
    payload.detail.trim()
  ) {
    return payload.detail;
  }
  return `Tenant Tasks request failed (${status})`;
}
