import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import {
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../api/client';
import { desktopApiFetch } from '../api/cloudRequestBroker';
import type {
  TenantTaskRecord,
  TenantTasksClient,
  TenantTasksQuery,
  TenantTasksRetryPendingResult,
  TenantTasksScope,
  TenantTasksSnapshot,
} from '../features/tenant/tenantTasksClient';
import type { DesktopRuntimeConfig } from '../types';
import {
  requireDesktopTenantTaskRecordV2,
  requireDesktopTenantTasksRetryPendingResultV2,
  requireDesktopTenantTasksSnapshotV2,
} from './desktopTenantTasksContractV2';
import {
  desktopTenantTasksLoadPathsV2,
  projectDesktopTenantTasksCloudSnapshotV2,
  projectDesktopTenantTasksLocalSnapshotV2,
  projectDesktopTenantTasksRetryPendingResultV2,
  tenantTasksContractErrorV2,
} from './desktopTenantTasksHttpProjectionV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import {
  cloneDesktopTenantTasksRuntimeConfigV2,
  cloneDesktopTenantTasksScopeV2,
  prepareTenantTaskMutationOperationV2,
  prepareTenantTasksBaseOperationV2,
  prepareTenantTasksLoadOperationV2,
  prepareTenantTasksRetryPendingOperationV2,
  type DesktopTenantTaskMutationInputV2,
  type DesktopTenantTasksLoadInputV2,
  type DesktopTenantTasksOperationInputV2,
  type DesktopTenantTasksRetryPendingInputV2,
  type PreparedTenantTasksOperationV2,
} from './desktopTenantTasksOperationContractV2';

export type {
  DesktopTenantTaskMutationInputV2,
  DesktopTenantTasksLoadInputV2,
  DesktopTenantTasksOperationInputV2,
  DesktopTenantTasksRetryPendingInputV2,
} from './desktopTenantTasksOperationContractV2';

export const DESKTOP_TENANT_TASKS_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-tasks-authority';
export const DESKTOP_TENANT_TASKS_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-tasks-authority';
export const DESKTOP_TENANT_TASKS_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopTenantTasksAuthorityV2 {
  readonly load: (
    query?: TenantTasksQuery,
    signal?: AbortSignal,
  ) => Promise<TenantTasksSnapshot>;
  readonly retryTask: (
    task: TenantTaskRecord,
    signal?: AbortSignal,
  ) => Promise<void>;
  readonly stopTask: (
    task: TenantTaskRecord,
    signal?: AbortSignal,
  ) => Promise<void>;
  readonly retryPending: (
    limit: number,
    signal?: AbortSignal,
  ) => Promise<TenantTasksRetryPendingResult>;
}

export interface DesktopTenantTasksAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    scope: TenantTasksScope,
  ) => DesktopTenantTasksAuthorityV2;
}

export interface DesktopTenantTasksOperationsV2 {
  readonly loadTenantTasks: (
    input: DesktopTenantTasksLoadInputV2,
  ) => Promise<TenantTasksSnapshot>;
  readonly retryTenantTask: (
    input: DesktopTenantTaskMutationInputV2,
  ) => Promise<void>;
  readonly stopTenantTask: (
    input: DesktopTenantTaskMutationInputV2,
  ) => Promise<void>;
  readonly retryPendingTenantTasks: (
    input: DesktopTenantTasksRetryPendingInputV2,
  ) => Promise<TenantTasksRetryPendingResult>;
}

type ServiceAdmissionRejectionV2 = Extract<
  DesktopRendererServiceOperationLeaseAdmissionV2<never>,
  { status: 'rejected' }
>;
type GenerationActionsUnavailableV2 = Readonly<{
  reasonCode: 'desktop_renderer_generation_actions_unavailable';
  runtimeCode?: undefined;
}>;
type AuthorityAdmissionRejectionV2 =
  | ServiceAdmissionRejectionV2
  | GenerationActionsUnavailableV2;

const AUTHORITY_KEYS_V2 = new Set(['load', 'retryTask', 'stopTask', 'retryPending']);

export class DesktopTenantTasksAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopTenantTasksAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopTenantTasksAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_tenant_tasks_authority_config_invalid',
      'desktop tenant tasks authority requires desktop-api-fetch strategy',
    );
  }
  const service: DesktopTenantTasksAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopTenantTasksAuthorityV2,
  });
  context.provide(DESKTOP_TENANT_TASKS_AUTHORITY_SERVICE_V2, service);
}

export const desktopTenantTasksAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_TENANT_TASKS_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopTenantTasksAuthorityV2,
});

export function createDesktopTenantTasksOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopTenantTasksOperationsV2 {
  return Object.freeze({
    loadTenantTasks(input: DesktopTenantTasksLoadInputV2) {
      const prepared = prepareTenantTasksLoadOperationV2(input);
      return runDesktopTenantTasksAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.load(prepared.query, prepared.signal),
      );
    },
    retryTenantTask(input: DesktopTenantTaskMutationInputV2) {
      const prepared = prepareTenantTaskMutationOperationV2(input, 'retry-task');
      return runDesktopTenantTasksAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.retryTask(prepared.task, prepared.signal),
      );
    },
    stopTenantTask(input: DesktopTenantTaskMutationInputV2) {
      const prepared = prepareTenantTaskMutationOperationV2(input, 'stop-task');
      return runDesktopTenantTasksAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.stopTask(prepared.task, prepared.signal),
      );
    },
    retryPendingTenantTasks(input: DesktopTenantTasksRetryPendingInputV2) {
      const prepared = prepareTenantTasksRetryPendingOperationV2(input);
      return runDesktopTenantTasksAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.retryPending(prepared.limit, prepared.signal),
      );
    },
  });
}

export function withDesktopTenantTasksAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopTenantTasksOperationInputV2,
  operation: (authority: DesktopTenantTasksAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopTenantTasksAuthorityOperationV2(
    actions,
    prepareTenantTasksBaseOperationV2(input),
    operation,
  );
}

export function createDesktopTenantTasksClientV2(
  operations: DesktopTenantTasksOperationsV2,
  config: DesktopRuntimeConfig,
): TenantTasksClient {
  const operationConfig = cloneDesktopTenantTasksRuntimeConfigV2(config);
  return Object.freeze({
    load(scope, query, options) {
      return operations.loadTenantTasks({
        config: operationConfig,
        scope,
        ...(query === undefined ? {} : { query }),
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
    retryTask(scope, task, options) {
      return operations.retryTenantTask({
        config: operationConfig,
        scope,
        task,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
    stopTask(scope, task, options) {
      return operations.stopTenantTask({
        config: operationConfig,
        scope,
        task,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
    retryPending(scope, limit, options) {
      return operations.retryPendingTenantTasks({
        config: operationConfig,
        scope,
        limit,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
  });
}

async function runDesktopTenantTasksAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedTenantTasksOperationV2,
  operation: (authority: DesktopTenantTasksAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  const scope =
    prepared.scope.authority === 'cloud'
      ? Object.freeze({ kind: 'tenant' as const, tenant_id: prepared.scope.tenantId })
      : Object.freeze({
          kind: 'project' as const,
          tenant_id: prepared.scope.tenantId,
          project_id: prepared.scope.projectId,
        });
  const admission =
    await actions.acquireServiceOperationLease<DesktopTenantTasksAuthorityServiceV2>({
      service: DESKTOP_TENANT_TASKS_AUTHORITY_SERVICE_V2,
      version: DESKTOP_TENANT_TASKS_AUTHORITY_VERSION_V2,
      scope,
    });
  if (admission.status === 'rejected') {
    throw new DesktopTenantTasksAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireTenantTasksServiceV2(candidate);
      const authority = requireTenantTasksAuthorityV2(
        service.bindOperation(prepared.config, prepared.scope),
      );
      return operation(
        createRevocableTenantTasksAuthorityV2(
          authority,
          prepared.scope,
          () => operationActive,
        ),
      );
    });
  } catch (error) {
    operationFailed = true;
    throw error;
  } finally {
    operationActive = false;
    try {
      await admission.release();
    } catch (releaseError) {
      if (!operationFailed) throw releaseError;
    }
  }
}

function createDesktopTenantTasksAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: TenantTasksScope,
): DesktopTenantTasksAuthorityV2 {
  const operationConfig = cloneDesktopTenantTasksRuntimeConfigV2(config);
  const operationScope = cloneDesktopTenantTasksScopeV2(scope, operationConfig);
  return Object.freeze({
    async load(query: TenantTasksQuery = {}, signal?: AbortSignal) {
      const normalizedQuery = Object.freeze({
        search: query.search ?? '',
        status: query.status ?? 'all',
        limit: query.limit ?? 50,
        offset: query.offset ?? 0,
      });
      if (operationScope.authority === 'local') {
        const payload = await requestJsonV2(
          operationConfig,
          `/api/v1/projects/${encodeURIComponent(operationScope.projectId)}/my-work`,
          { method: 'GET', signal },
        );
        return projectDesktopTenantTasksLocalSnapshotV2(
          payload,
          operationScope,
          normalizedQuery,
        );
      }
      const paths = desktopTenantTasksLoadPathsV2(operationScope, normalizedQuery);
      const [stats, queue, recent] = await Promise.all([
        requestJsonV2(operationConfig, paths.stats, { method: 'GET', signal }),
        requestJsonV2(operationConfig, paths.queue, { method: 'GET', signal }),
        requestJsonV2(operationConfig, paths.recent, { method: 'GET', signal }),
      ]);
      return projectDesktopTenantTasksCloudSnapshotV2(
        stats,
        queue,
        recent,
        operationScope,
        normalizedQuery,
      );
    },
    async retryTask(task: TenantTaskRecord, signal?: AbortSignal) {
      await requestJsonV2(
        operationConfig,
        `/api/v1/tasks/${encodeURIComponent(task.id)}/retry`,
        { method: 'POST', signal },
      );
    },
    async stopTask(task: TenantTaskRecord, signal?: AbortSignal) {
      await requestJsonV2(
        operationConfig,
        `/api/v1/tasks/${encodeURIComponent(task.id)}/stop`,
        { method: 'POST', signal },
      );
    },
    async retryPending(limit: number, signal?: AbortSignal) {
      const params = new URLSearchParams({ limit: String(limit) });
      const payload = await requestJsonV2(
        operationConfig,
        `/api/v1/tasks/retry-pending?${params.toString()}`,
        { method: 'POST', signal },
      );
      return projectDesktopTenantTasksRetryPendingResultV2(payload);
    },
  });
}

function createRevocableTenantTasksAuthorityV2(
  authority: DesktopTenantTasksAuthorityV2,
  scope: TenantTasksScope,
  isOperationActive: () => boolean,
): DesktopTenantTasksAuthorityV2 {
  return Object.freeze({
    async load(query?: TenantTasksQuery, signal?: AbortSignal) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.load(query, signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopTenantTasksSnapshotV2(result, scope);
    },
    async retryTask(task: TenantTaskRecord, signal?: AbortSignal) {
      requireOperationActiveV2(isOperationActive);
      requireCloudMutationV2(scope, 'retry-task');
      const record = requireDesktopTenantTaskRecordV2(task, scope);
      const result = await authority.retryTask(record, signal);
      requireOperationActiveV2(isOperationActive);
      if (result !== undefined) throw invalidServiceV2();
    },
    async stopTask(task: TenantTaskRecord, signal?: AbortSignal) {
      requireOperationActiveV2(isOperationActive);
      requireCloudMutationV2(scope, 'stop-task');
      const record = requireDesktopTenantTaskRecordV2(task, scope);
      const result = await authority.stopTask(record, signal);
      requireOperationActiveV2(isOperationActive);
      if (result !== undefined) throw invalidServiceV2();
    },
    async retryPending(limit: number, signal?: AbortSignal) {
      requireOperationActiveV2(isOperationActive);
      requireCloudMutationV2(scope, 'retry-pending');
      if (!Number.isInteger(limit) || limit < 1 || limit > 10) throw invalidServiceV2();
      const result = await authority.retryPending(limit, signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopTenantTasksRetryPendingResultV2(result);
    },
  });
}

type RequestOptionsV2 = Readonly<{
  method: 'GET' | 'POST';
  signal?: AbortSignal;
}>;

async function requestJsonV2(
  config: DesktopRuntimeConfig,
  path: string,
  options: RequestOptionsV2,
): Promise<unknown> {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  const response = await desktopApiFetch(config, path, {
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
    throw new DesktopApiError(errorMessageV2(response.status, payload), response.status, payload);
  }
  if (!isJson || payload === null) {
    throw tenantTasksContractErrorV2(`${config.mode}_tenant_tasks_contract_invalid`);
  }
  return payload;
}

function requireTenantTasksServiceV2(value: unknown): DesktopTenantTasksAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopTenantTasksAuthorityServiceV2;
}

function requireTenantTasksAuthorityV2(value: unknown): DesktopTenantTasksAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, AUTHORITY_KEYS_V2) ||
    typeof value.load !== 'function' ||
    typeof value.retryTask !== 'function' ||
    typeof value.stopTask !== 'function' ||
    typeof value.retryPending !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopTenantTasksAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopTenantTasksAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function requireOperationActiveV2(isOperationActive: () => boolean): void {
  if (isOperationActive()) return;
  throw new RuntimeV2Error(
    'desktop_tenant_tasks_operation_released',
    'desktop tenant tasks operation has been released',
  );
}

function requireCloudMutationV2(scope: TenantTasksScope, action: string): void {
  if (scope.authority === 'cloud') return;
  throw new RuntimeV2Error(
    'desktop_tenant_tasks_operation_unsupported',
    `local_task_mutation_unavailable:${action}`,
  );
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_tasks_service_invalid',
    'desktop tenant tasks authority service is invalid',
  );
}

function errorMessageV2(status: number, payload: unknown): string {
  if (isPlainRecordV2(payload) && typeof payload.detail === 'string' && payload.detail.trim()) {
    return payload.detail;
  }
  const reasonCode = structuredReasonCodeV2(payload);
  return reasonCode ?? `tenant_tasks_http_${status}`;
}

function structuredReasonCodeV2(payload: unknown): string | null {
  if (!isPlainRecordV2(payload)) return null;
  if (typeof payload.reason_code === 'string') return payload.reason_code;
  return isPlainRecordV2(payload.detail) && typeof payload.detail.reason_code === 'string'
    ? payload.detail.reason_code
    : null;
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

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) => candidate.module_ref === DESKTOP_TENANT_TASKS_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_tenant_tasks_authority_catalog_missing',
      'desktop tenant tasks authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
