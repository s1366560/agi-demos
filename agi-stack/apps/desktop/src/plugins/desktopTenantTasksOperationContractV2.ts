import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  TenantTaskRecord,
  TenantTasksQuery,
  TenantTasksScope,
} from '../features/tenant/tenantTasksClient';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopTenantTasksOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TenantTasksScope;
  signal?: AbortSignal;
}>;
export type DesktopTenantTasksLoadInputV2 = DesktopTenantTasksOperationInputV2 &
  Readonly<{ query?: TenantTasksQuery }>;
export type DesktopTenantTaskMutationInputV2 = DesktopTenantTasksOperationInputV2 &
  Readonly<{ task: TenantTaskRecord }>;
export type DesktopTenantTasksRetryPendingInputV2 = DesktopTenantTasksOperationInputV2 &
  Readonly<{ limit: number }>;

export type PreparedTenantTasksOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TenantTasksScope;
  signal?: AbortSignal;
}>;
export type PreparedTenantTasksLoadOperationV2 = PreparedTenantTasksOperationV2 &
  Readonly<{ query: Required<TenantTasksQuery> }>;
export type PreparedTenantTaskMutationOperationV2 = PreparedTenantTasksOperationV2 &
  Readonly<{ task: TenantTaskRecord }>;
export type PreparedTenantTasksRetryPendingOperationV2 = PreparedTenantTasksOperationV2 &
  Readonly<{ limit: number }>;

const BASE_KEYS_V2 = new Set(['config', 'scope', 'signal']);
const LOAD_KEYS_V2 = new Set([...BASE_KEYS_V2, 'query']);
const TASK_KEYS_V2 = new Set([...BASE_KEYS_V2, 'task']);
const RETRY_PENDING_KEYS_V2 = new Set([...BASE_KEYS_V2, 'limit']);
const CLOUD_SCOPE_KEYS_V2 = new Set(['authority', 'tenantId', 'projectId']);
const LOCAL_SCOPE_KEYS_V2 = new Set(['authority', 'tenantId', 'projectId']);
const TASK_RECORD_KEYS_V2 = new Set([
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
const DEFAULT_LIMIT_V2 = 50;
const MAX_LIMIT_V2 = 100;

export function prepareTenantTasksBaseOperationV2(
  input: DesktopTenantTasksOperationInputV2,
): PreparedTenantTasksOperationV2 {
  return prepareBaseOperationV2(input, BASE_KEYS_V2);
}

export function prepareTenantTasksLoadOperationV2(
  input: DesktopTenantTasksLoadInputV2,
): PreparedTenantTasksLoadOperationV2 {
  const prepared = prepareBaseOperationV2(input, LOAD_KEYS_V2);
  return Object.freeze({
    ...prepared,
    query: cloneTenantTasksQueryV2(input.query),
  });
}

export function prepareTenantTaskMutationOperationV2(
  input: DesktopTenantTaskMutationInputV2,
  action: 'retry-task' | 'stop-task',
): PreparedTenantTaskMutationOperationV2 {
  const prepared = prepareBaseOperationV2(input, TASK_KEYS_V2);
  if (prepared.scope.authority === 'local') {
    throw new RuntimeV2Error(
      'desktop_tenant_tasks_operation_unsupported',
      `local_task_mutation_unavailable:${action}`,
    );
  }
  if (!Object.hasOwn(input, 'task')) throw invalidOperationInputV2();
  return Object.freeze({
    ...prepared,
    task: cloneTenantTaskRecordV2(input.task, prepared.scope),
  });
}

export function prepareTenantTasksRetryPendingOperationV2(
  input: DesktopTenantTasksRetryPendingInputV2,
): PreparedTenantTasksRetryPendingOperationV2 {
  const prepared = prepareBaseOperationV2(input, RETRY_PENDING_KEYS_V2);
  if (prepared.scope.authority === 'local') {
    throw new RuntimeV2Error(
      'desktop_tenant_tasks_operation_unsupported',
      'local_task_mutation_unavailable:retry-pending',
    );
  }
  return Object.freeze({
    ...prepared,
    limit: integerInRangeV2(input.limit, 1, 10),
  });
}

export function cloneDesktopTenantTasksRuntimeConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw invalidOperationInputV2();
  const copy: DesktopRuntimeConfig = {
    apiBaseUrl: config.apiBaseUrl,
    deviceAuthorizationBaseUrl: config.deviceAuthorizationBaseUrl,
    apiKey: config.apiKey,
    localApiToken: config.localApiToken,
    tenantId: config.tenantId,
    projectId: config.projectId,
    workspaceId: config.workspaceId,
    mode: config.mode,
    workspaceRoot: config.workspaceRoot,
  };
  if (
    Object.values(copy).some((value) => typeof value !== 'string') ||
    (copy.mode !== 'cloud' && copy.mode !== 'local') ||
    !isCanonicalStringV2(copy.tenantId)
  ) {
    throw invalidOperationInputV2();
  }
  return Object.freeze(copy);
}

export function cloneDesktopTenantTasksScopeV2(
  scope: TenantTasksScope,
  config: DesktopRuntimeConfig,
): TenantTasksScope {
  if (
    !isPlainRecordV2(scope) ||
    scope.authority !== config.mode ||
    !isCanonicalStringV2(scope.tenantId) ||
    scope.tenantId !== config.tenantId
  ) {
    throw invalidOperationInputV2();
  }
  if (scope.authority === 'cloud') {
    if (!hasExactKeysV2(scope, CLOUD_SCOPE_KEYS_V2) || scope.projectId !== null) {
      throw invalidOperationInputV2();
    }
    return Object.freeze({ authority: 'cloud', tenantId: scope.tenantId, projectId: null });
  }
  if (
    !hasExactKeysV2(scope, LOCAL_SCOPE_KEYS_V2) ||
    !isCanonicalStringV2(scope.projectId) ||
    scope.projectId !== config.projectId
  ) {
    throw invalidOperationInputV2();
  }
  return Object.freeze({
    authority: 'local',
    tenantId: scope.tenantId,
    projectId: scope.projectId,
  });
}

function prepareBaseOperationV2(
  input: DesktopTenantTasksOperationInputV2,
  allowedKeys: ReadonlySet<string>,
): PreparedTenantTasksOperationV2 {
  if (
    !isPlainRecordV2(input) ||
    !hasAllowedKeysV2(input, allowedKeys) ||
    !Object.hasOwn(input, 'config') ||
    !Object.hasOwn(input, 'scope') ||
    (input.signal !== undefined && !isAbortSignalV2(input.signal))
  ) {
    throw invalidOperationInputV2();
  }
  const config = cloneDesktopTenantTasksRuntimeConfigV2(input.config);
  const scope = cloneDesktopTenantTasksScopeV2(input.scope, config);
  return Object.freeze({
    config,
    scope,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

function cloneTenantTasksQueryV2(
  query: TenantTasksQuery | undefined,
): Required<TenantTasksQuery> {
  if (query !== undefined && !isPlainRecordV2(query)) throw invalidOperationInputV2();
  if (
    query !== undefined &&
    !hasAllowedKeysV2(query, new Set(['search', 'status', 'limit', 'offset']))
  ) {
    throw invalidOperationInputV2();
  }
  if (
    query?.search !== undefined && typeof query.search !== 'string' ||
    query?.status !== undefined && typeof query.status !== 'string'
  ) {
    throw invalidOperationInputV2();
  }
  return Object.freeze({
    search: query?.search?.trim() ?? '',
    status: query?.status?.trim().toLocaleLowerCase() || 'all',
    limit: integerInRangeV2(query?.limit ?? DEFAULT_LIMIT_V2, 1, MAX_LIMIT_V2),
    offset: integerInRangeV2(query?.offset ?? 0, 0, Number.MAX_SAFE_INTEGER),
  });
}

function cloneTenantTaskRecordV2(
  task: TenantTaskRecord,
  scope: TenantTasksScope,
): TenantTaskRecord {
  if (
    !isPlainRecordV2(task) ||
    !hasExactKeysV2(task, TASK_RECORD_KEYS_V2) ||
    !isCanonicalStringV2(task.id) ||
    task.projectId !== scope.projectId ||
    !isNullableCanonicalStringV2(task.workspaceId) ||
    !isNullableCanonicalStringV2(task.conversationId) ||
    !isCanonicalStringV2(task.taskType) ||
    !isCanonicalStringV2(task.name) ||
    !isCanonicalStringV2(task.status) ||
    !isCanonicalStringV2(task.createdAt) ||
    !isNullableCanonicalStringV2(task.completedAt) ||
    !isNullableCanonicalStringV2(task.error) ||
    !isNullableCanonicalStringV2(task.duration) ||
    !isNullableCanonicalStringV2(task.entityId) ||
    !isNullableCanonicalStringV2(task.entityType) ||
    !(task.revision === null || isNonnegativeIntegerV2(task.revision)) ||
    typeof task.canRetry !== 'boolean' ||
    typeof task.canStop !== 'boolean'
  ) {
    throw invalidOperationInputV2();
  }
  return Object.freeze({ ...task });
}

function integerInRangeV2(value: unknown, min: number, max: number): number {
  if (!Number.isInteger(value) || Number(value) < min || Number(value) > max) {
    throw invalidOperationInputV2();
  }
  return Number(value);
}

function isAbortSignalV2(value: unknown): value is AbortSignal {
  return typeof AbortSignal !== 'undefined' && value instanceof AbortSignal;
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

function hasAllowedKeysV2(
  value: Record<string, unknown>,
  allowed: ReadonlySet<string>,
): boolean {
  return Object.keys(value).every((key) => allowed.has(key));
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

function invalidOperationInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_tasks_operation_input_invalid',
    'desktop tenant tasks operation input is invalid',
  );
}
