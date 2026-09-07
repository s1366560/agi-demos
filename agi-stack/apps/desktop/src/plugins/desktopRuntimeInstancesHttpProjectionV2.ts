import {
  desktopApiCredential,
  desktopLaunchCapability,
  DesktopApiError,
} from '../api/client';
import { desktopApiFetch } from '../api/cloudRequestBroker';
import {
  RUNTIME_INSTANCES_CLOUD_ACTIONS,
  RUNTIME_INSTANCES_CLOUD_REASON,
  RUNTIME_INSTANCES_LOCAL_ACTIONS,
  RUNTIME_INSTANCES_LOCAL_REASON,
  RuntimeInstancesUnavailableError,
} from '../features/runtime-instances/runtimeInstancesContract';
import type {
  RuntimeInstanceSummary,
  RuntimeInstancesPage,
  RuntimeInstancesQuery,
  RuntimeInstancesScope,
} from '../features/runtime-instances/runtimeInstancesTypes';
import type { DesktopCapabilityAvailability } from '../features/runtime/capabilitySnapshot';
import type { DesktopRuntimeConfig } from '../types';
import {
  cloneDesktopRuntimeInstancesConfigV2,
  cloneDesktopRuntimeInstancesScopeV2,
} from './desktopRuntimeInstancesOperationContractV2';

export type DesktopRuntimeInstancesHttpAuthorityV2 = Readonly<{
  list: (
    query: Required<RuntimeInstancesQuery>,
    signal?: AbortSignal,
  ) => Promise<RuntimeInstancesPage>;
  restart: (instanceId: string, signal?: AbortSignal) => Promise<void>;
  delete: (instanceId: string, signal?: AbortSignal) => Promise<void>;
  probe: (signal?: AbortSignal) => Promise<DesktopCapabilityAvailability>;
}>;

export function createDesktopRuntimeInstancesHttpAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: RuntimeInstancesScope,
): DesktopRuntimeInstancesHttpAuthorityV2 {
  const runtimeConfig = cloneDesktopRuntimeInstancesConfigV2(config);
  const operationScope = cloneDesktopRuntimeInstancesScopeV2(scope, runtimeConfig);
  return Object.freeze({
    async list(query, signal) {
      if (operationScope.authority === 'local') {
        const payload = await readLocalRuntimeStatusV2();
        if (signal?.aborted) throw new DOMException('The operation was aborted.', 'AbortError');
        return localPageV2(payload, query);
      }
      return requestInstancePageV2(runtimeConfig, operationScope, query, signal);
    },
    async restart(instanceId, signal) {
      requireCloudAuthorityV2(operationScope);
      await requestJsonV2(
        runtimeConfig,
        `/api/v1/instances/${encodeURIComponent(requireIdentifierV2(instanceId))}/restart`,
        'POST',
        signal,
      );
    },
    async delete(instanceId, signal) {
      requireCloudAuthorityV2(operationScope);
      await requestJsonV2(
        runtimeConfig,
        `/api/v1/instances/${encodeURIComponent(requireIdentifierV2(instanceId))}`,
        'DELETE',
        signal,
      );
    },
    async probe(signal) {
      if (operationScope.authority === 'local') {
        await readLocalRuntimeStatusV2();
        return capabilityV2(operationScope);
      }
      await requestInstancePageV2(
        runtimeConfig,
        operationScope,
        Object.freeze({ page: 1, pageSize: 1, search: '', status: 'all' }),
        signal,
      );
      return capabilityV2(operationScope);
    },
  });
}

async function requestInstancePageV2(
  config: DesktopRuntimeConfig,
  scope: RuntimeInstancesScope,
  query: Required<RuntimeInstancesQuery>,
  signal?: AbortSignal,
): Promise<RuntimeInstancesPage> {
  const params = new URLSearchParams({
    page: String(query.page),
    page_size: String(query.pageSize),
  });
  if (query.search) params.set('search', query.search);
  if (query.status !== 'all') params.set('status', query.status);
  const payload = await requestJsonV2(
    config,
    `/api/v1/instances/?${params.toString()}`,
    'GET',
    signal,
  );
  return parsePageV2(payload, scope);
}

async function requestJsonV2(
  config: DesktopRuntimeConfig,
  path: string,
  method: 'GET' | 'POST' | 'DELETE',
  signal?: AbortSignal,
): Promise<unknown> {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  const response = await desktopApiFetch(config, path, {
    method,
    headers,
    signal,
  });
  const contentType = response.headers.get('content-type') ?? '';
  const isJson = contentType.toLowerCase().includes('application/json');
  const payload = isJson
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '');
  if (!response.ok) {
    throw new DesktopApiError(errorMessageV2(response.status, payload), response.status, payload);
  }
  if (method === 'GET' && (!isJson || payload === null)) throw responseContractErrorV2();
  return payload;
}

function parsePageV2(payload: unknown, scope: RuntimeInstancesScope): RuntimeInstancesPage {
  if (
    !isRecordV2(payload) ||
    !Array.isArray(payload.instances) ||
    !nonnegativeIntegerV2(payload.total) ||
    !positiveIntegerV2(payload.page) ||
    !positiveIntegerV2(payload.page_size)
  ) {
    throw responseContractErrorV2();
  }
  const instances = payload.instances.map((value) => parseInstanceV2(value, scope));
  if (instances.length > payload.total || instances.length > payload.page_size) {
    throw responseContractErrorV2();
  }
  return Object.freeze({
    instances: Object.freeze(instances),
    total: payload.total,
    page: payload.page,
    pageSize: payload.page_size,
  });
}

function parseInstanceV2(
  value: unknown,
  scope: RuntimeInstancesScope,
): RuntimeInstanceSummary {
  if (
    !isRecordV2(value) ||
    !canonicalStringV2(value.id) ||
    !canonicalStringV2(value.name) ||
    !canonicalStringV2(value.status) ||
    !nullableStringV2(value.health_status) ||
    !nullableStringV2(value.image_version) ||
    !nullableNonnegativeIntegerV2(value.replicas) ||
    !nullableNonnegativeIntegerV2(value.available_replicas) ||
    !nullableStringV2(value.cluster_id) ||
    !nullableStringV2(value.created_at) ||
    !nullableStringV2(value.updated_at) ||
    (value.tenant_id !== undefined && value.tenant_id !== scope.tenantId)
  ) {
    throw responseContractErrorV2();
  }
  return Object.freeze({
    id: value.id,
    name: value.name,
    status: value.status,
    healthStatus: value.health_status,
    imageVersion: value.image_version,
    replicas: value.replicas,
    availableReplicas: value.available_replicas,
    clusterId: value.cluster_id,
    createdAt: value.created_at,
    updatedAt: value.updated_at,
    projection: 'cloud',
  });
}

function capabilityV2(scope: RuntimeInstancesScope): DesktopCapabilityAvailability {
  const local = scope.authority === 'local';
  return Object.freeze({
    availability: 'degraded',
    reason_code: local ? RUNTIME_INSTANCES_LOCAL_REASON : RUNTIME_INSTANCES_CLOUD_REASON,
    service_version: '0.1.0',
    contract_version: '3.0.0',
    allowed_actions: local ? RUNTIME_INSTANCES_LOCAL_ACTIONS : RUNTIME_INSTANCES_CLOUD_ACTIONS,
    scope: Object.freeze({
      tenant_id: scope.tenantId,
      project_id: null,
      workspace_id: null,
      instance_id: null,
    }),
    authority_revision: null,
  });
}

function requireCloudAuthorityV2(scope: RuntimeInstancesScope): void {
  if (scope.authority === 'cloud') return;
  throw new RuntimeInstancesUnavailableError('local_instance_lifecycle_not_applicable');
}

async function readLocalRuntimeStatusV2(): Promise<unknown> {
  const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke;
  if (!invoke) {
    throw new RuntimeInstancesUnavailableError('runtime_instances_native_bridge_unavailable');
  }
  return invoke<unknown>('local_runtime_status');
}

function localPageV2(
  payload: unknown,
  query: Required<RuntimeInstancesQuery>,
): RuntimeInstancesPage {
  if (
    !isRecordV2(payload) ||
    typeof payload.running !== 'boolean' ||
    !nonnegativeIntegerV2(payload.tool_count) ||
    !Array.isArray(payload.runtime_providers)
  ) {
    throw responseContractErrorV2();
  }
  const instance = Object.freeze({
    id: 'local-sidecar',
    name: 'Local sidecar',
    status: payload.running ? 'running' : 'stopped',
    healthStatus: payload.running ? 'healthy' : 'unavailable',
    imageVersion: null,
    replicas: null,
    availableReplicas: null,
    clusterId: null,
    createdAt: null,
    updatedAt: null,
    projection: 'local_sidecar' as const,
  });
  const search = query.search.toLocaleLowerCase();
  const matchesSearch =
    !search ||
    `${instance.id} ${instance.name} ${instance.status}`.toLocaleLowerCase().includes(search);
  const matchesStatus = query.status === 'all' || query.status === instance.status;
  const instances = matchesSearch && matchesStatus ? [instance] : [];
  return Object.freeze({
    instances: Object.freeze(instances),
    total: instances.length,
    page: 1,
    pageSize: query.pageSize,
  });
}

function requireIdentifierV2(value: unknown): string {
  if (!canonicalStringV2(value) || /\s/u.test(value)) {
    throw new RuntimeInstancesUnavailableError('runtime_instances_identifier_invalid');
  }
  return value;
}

function responseContractErrorV2(): RuntimeInstancesUnavailableError {
  return new RuntimeInstancesUnavailableError('runtime_instances_response_contract_invalid');
}

function errorMessageV2(status: number, payload: unknown): string {
  if (isRecordV2(payload) && typeof payload.detail === 'string') return payload.detail;
  return `Runtime Instances request failed (${status})`;
}

function isRecordV2(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function canonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function nullableStringV2(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function positiveIntegerV2(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0;
}

function nonnegativeIntegerV2(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function nullableNonnegativeIntegerV2(value: unknown): value is number | null {
  return value === null || nonnegativeIntegerV2(value);
}
