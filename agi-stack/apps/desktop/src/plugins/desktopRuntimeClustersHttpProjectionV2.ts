import {
  desktopApiCredential,
  desktopLaunchCapability,
  DesktopApiError,
} from '../api/client';
import { desktopApiFetch } from '../api/cloudRequestBroker';
import {
  RUNTIME_CLUSTERS_CLOUD_ACTIONS,
  RUNTIME_CLUSTERS_CLOUD_REASON,
  RUNTIME_CLUSTERS_LOCAL_REASON,
  RuntimeClustersUnavailableError,
} from '../features/runtime-clusters/runtimeClustersContract';
import type {
  RuntimeClusterHealth,
  RuntimeClusterSummary,
  RuntimeClustersPage,
  RuntimeClustersQuery,
  RuntimeClustersScope,
} from '../features/runtime-clusters/runtimeClustersTypes';
import type { DesktopCapabilityAvailability } from '../features/runtime/capabilitySnapshot';
import type { DesktopRuntimeConfig } from '../types';
import {
  cloneDesktopRuntimeClustersConfigV2,
  cloneDesktopRuntimeClustersScopeV2,
} from './desktopRuntimeClustersOperationContractV2';

export type DesktopRuntimeClustersHttpAuthorityV2 = Readonly<{
  list: (
    query: Required<RuntimeClustersQuery>,
    signal?: AbortSignal,
  ) => Promise<RuntimeClustersPage>;
  getHealth: (clusterId: string, signal?: AbortSignal) => Promise<RuntimeClusterHealth>;
  probe: (signal?: AbortSignal) => Promise<DesktopCapabilityAvailability>;
}>;

export function createDesktopRuntimeClustersHttpAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: RuntimeClustersScope,
): DesktopRuntimeClustersHttpAuthorityV2 {
  const runtimeConfig = cloneDesktopRuntimeClustersConfigV2(config);
  const operationScope = cloneDesktopRuntimeClustersScopeV2(scope, runtimeConfig);
  return Object.freeze({
    async list(query, signal) {
      requireCloudAuthorityV2(operationScope);
      return requestClusterPageV2(runtimeConfig, operationScope, query, signal);
    },
    async getHealth(clusterId, signal) {
      requireCloudAuthorityV2(operationScope);
      const payload = await requestJsonV2(
        runtimeConfig,
        `/api/v1/clusters/${encodeURIComponent(requireIdentifierV2(clusterId))}/health`,
        signal,
      );
      return parseHealthV2(payload);
    },
    async probe(signal) {
      if (operationScope.authority === 'local') {
        return capabilityV2(operationScope);
      }
      await requestClusterPageV2(
        runtimeConfig,
        operationScope,
        Object.freeze({ page: 1, pageSize: 1, search: '', status: 'all' }),
        signal,
      );
      return capabilityV2(operationScope);
    },
  });
}

async function requestClusterPageV2(
  config: DesktopRuntimeConfig,
  scope: RuntimeClustersScope,
  query: Required<RuntimeClustersQuery>,
  signal?: AbortSignal,
): Promise<RuntimeClustersPage> {
  const params = new URLSearchParams({
    page: String(query.page),
    page_size: String(query.pageSize),
  });
  const payload = await requestJsonV2(
    config,
    `/api/v1/clusters/?${params.toString()}`,
    signal,
  );
  return parsePageV2(payload, scope);
}

async function requestJsonV2(
  config: DesktopRuntimeConfig,
  path: string,
  signal?: AbortSignal,
): Promise<unknown> {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  const response = await desktopApiFetch(config, path, {
    method: 'GET',
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
  if (!isJson || payload === null) throw responseContractErrorV2();
  return payload;
}

function parsePageV2(payload: unknown, scope: RuntimeClustersScope): RuntimeClustersPage {
  if (
    !isRecordV2(payload) ||
    !Array.isArray(payload.clusters) ||
    !nonnegativeIntegerV2(payload.total) ||
    !positiveIntegerV2(payload.page) ||
    !positiveIntegerV2(payload.page_size)
  ) {
    throw responseContractErrorV2();
  }
  const clusters = payload.clusters.map((value) => parseClusterV2(value, scope));
  if (clusters.length > payload.total || clusters.length > payload.page_size) {
    throw responseContractErrorV2();
  }
  return Object.freeze({
    clusters: Object.freeze(clusters),
    total: payload.total,
    page: payload.page,
    pageSize: payload.page_size,
  });
}

function parseClusterV2(
  value: unknown,
  scope: RuntimeClustersScope,
): RuntimeClusterSummary {
  if (
    !isRecordV2(value) ||
    !canonicalStringV2(value.id) ||
    !canonicalStringV2(value.name) ||
    !canonicalStringV2(value.compute_provider) ||
    !nullableStringV2(value.proxy_endpoint) ||
    !canonicalStringV2(value.status) ||
    !nullableStringV2(value.health_status) ||
    !nullableStringV2(value.last_health_check) ||
    !canonicalStringV2(value.created_at) ||
    !nullableStringV2(value.updated_at) ||
    (value.tenant_id !== undefined && value.tenant_id !== scope.tenantId)
  ) {
    throw responseContractErrorV2();
  }
  return Object.freeze({
    id: value.id,
    name: value.name,
    computeProvider: value.compute_provider,
    proxyEndpoint: value.proxy_endpoint,
    status: value.status,
    healthStatus: value.health_status,
    lastHealthCheck: value.last_health_check,
    createdAt: value.created_at,
    updatedAt: value.updated_at,
  });
}

function parseHealthV2(payload: unknown): RuntimeClusterHealth {
  if (
    !isRecordV2(payload) ||
    !canonicalStringV2(payload.status) ||
    !nonnegativeIntegerV2(payload.node_count) ||
    !nullableNonnegativeNumberV2(payload.cpu_usage) ||
    !nullableNonnegativeNumberV2(payload.memory_usage) ||
    !nullableStringV2(payload.checked_at)
  ) {
    throw responseContractErrorV2();
  }
  return Object.freeze({
    status: payload.status,
    nodeCount: payload.node_count,
    cpuUsage: payload.cpu_usage,
    memoryUsage: payload.memory_usage,
    checkedAt: payload.checked_at,
  });
}

function capabilityV2(scope: RuntimeClustersScope): DesktopCapabilityAvailability {
  const local = scope.authority === 'local';
  return Object.freeze({
    availability: local ? 'not_applicable' : 'degraded',
    reason_code: local ? RUNTIME_CLUSTERS_LOCAL_REASON : RUNTIME_CLUSTERS_CLOUD_REASON,
    service_version: local ? null : '0.1.0',
    contract_version: local ? null : '3.0.0',
    allowed_actions: local ? Object.freeze([]) : RUNTIME_CLUSTERS_CLOUD_ACTIONS,
    scope: Object.freeze({
      tenant_id: scope.tenantId,
      project_id: null,
      workspace_id: null,
      instance_id: null,
    }),
    authority_revision: null,
  });
}

function requireCloudAuthorityV2(scope: RuntimeClustersScope): void {
  if (scope.authority === 'cloud') return;
  throw new RuntimeClustersUnavailableError(RUNTIME_CLUSTERS_LOCAL_REASON);
}

function requireIdentifierV2(value: unknown): string {
  if (!canonicalStringV2(value) || /\s/u.test(value)) {
    throw new RuntimeClustersUnavailableError('runtime_clusters_identifier_invalid');
  }
  return value;
}

function responseContractErrorV2(): RuntimeClustersUnavailableError {
  return new RuntimeClustersUnavailableError('runtime_clusters_response_contract_invalid');
}

function errorMessageV2(status: number, payload: unknown): string {
  if (isRecordV2(payload) && typeof payload.detail === 'string') return payload.detail;
  return `Runtime Clusters request failed (${status})`;
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

function nullableNonnegativeNumberV2(value: unknown): value is number | null {
  return value === null || (typeof value === 'number' && Number.isFinite(value) && value >= 0);
}
