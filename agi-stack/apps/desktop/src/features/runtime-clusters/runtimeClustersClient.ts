import {
  absoluteUrl,
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import { desktopApiFetch } from '../../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../../types';
import type {
  RuntimeClusterHealth,
  RuntimeClusterSummary,
  RuntimeClustersClient,
  RuntimeClustersPage,
  RuntimeClustersQuery,
  RuntimeClustersScope,
} from './runtimeClustersTypes';

type Fetch = typeof globalThis.fetch;
type FetchPath = (path: string, init: RequestInit) => Promise<Response>;

export type RuntimeClustersClientDependencies = Readonly<{
  fetch?: Fetch;
}>;

export class RuntimeClustersUnavailableError extends Error {
  readonly reasonCode: string;

  constructor(reasonCode: string) {
    super(reasonCode);
    this.name = 'RuntimeClustersUnavailableError';
    this.reasonCode = reasonCode;
  }
}

export function createRuntimeClustersClient(
  config: DesktopRuntimeConfig,
  dependencies: RuntimeClustersClientDependencies = {},
): RuntimeClustersClient {
  const runtimeConfig = Object.freeze({ ...config });
  const fetchPath: FetchPath = dependencies.fetch
    ? (path, init) => dependencies.fetch!(absoluteUrl(runtimeConfig.apiBaseUrl, path), init)
    : (path, init) => desktopApiFetch(runtimeConfig, path, init);
  return Object.freeze({
    async list(scope, query = {}, options) {
      requireCloudScope(runtimeConfig, scope);
      const normalized = normalizeQuery(query);
      const params = new URLSearchParams({
        page: String(normalized.page),
        page_size: String(normalized.pageSize),
      });
      const payload = await requestJson(
        runtimeConfig,
        `/api/v1/clusters/?${params.toString()}`,
        fetchPath,
        options?.signal,
      );
      return parsePage(payload, scope);
    },
    async getHealth(scope, clusterId, options) {
      requireCloudScope(runtimeConfig, scope);
      const payload = await requestJson(
        runtimeConfig,
        `/api/v1/clusters/${encodeURIComponent(identifier(clusterId))}/health`,
        fetchPath,
        options?.signal,
      );
      return parseHealth(payload);
    },
  });
}

function requireCloudScope(
  config: DesktopRuntimeConfig,
  scope: RuntimeClustersScope,
): void {
  if (
    config.mode !== scope.authority ||
    identifier(config.tenantId) !== identifier(scope.tenantId)
  ) {
    throw new RuntimeClustersUnavailableError(
      'runtime_clusters_runtime_scope_mismatch',
    );
  }
  if (scope.authority !== 'cloud') {
    throw new RuntimeClustersUnavailableError(
      'cloud_cluster_control_not_applicable',
    );
  }
}

async function requestJson(
  config: DesktopRuntimeConfig,
  path: string,
  fetchPath: FetchPath,
  signal?: AbortSignal,
): Promise<unknown> {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  const response = await fetchPath(path, {
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
    throw new DesktopApiError(
      errorMessage(response.status, payload),
      response.status,
      payload,
    );
  }
  if (!isJson || payload === null) throw contractError();
  return payload;
}

function parsePage(
  payload: unknown,
  scope: RuntimeClustersScope,
): RuntimeClustersPage {
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.clusters) ||
    !isNonnegativeInteger(payload.total) ||
    !isPositiveInteger(payload.page) ||
    !isPositiveInteger(payload.page_size)
  ) {
    throw contractError();
  }
  const clusters = payload.clusters.map((value) =>
    parseCluster(value, scope),
  );
  if (clusters.length > payload.total) throw contractError();
  return Object.freeze({
    clusters: Object.freeze(clusters),
    total: payload.total,
    page: payload.page,
    pageSize: payload.page_size,
  });
}

function parseCluster(
  value: unknown,
  scope: RuntimeClustersScope,
): RuntimeClusterSummary {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value.id) ||
    !isNonEmptyString(value.name) ||
    !isNonEmptyString(value.compute_provider) ||
    !isNullableString(value.proxy_endpoint) ||
    !isNonEmptyString(value.status) ||
    !isNullableString(value.health_status) ||
    !isNullableString(value.last_health_check) ||
    !isNonEmptyString(value.created_at) ||
    !isNullableString(value.updated_at) ||
    (value.tenant_id !== undefined && value.tenant_id !== scope.tenantId)
  ) {
    throw contractError();
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

function parseHealth(payload: unknown): RuntimeClusterHealth {
  if (
    !isRecord(payload) ||
    !isNonEmptyString(payload.status) ||
    !isNonnegativeInteger(payload.node_count) ||
    !isNullableNonnegativeNumber(payload.cpu_usage) ||
    !isNullableNonnegativeNumber(payload.memory_usage) ||
    !isNullableString(payload.checked_at)
  ) {
    throw contractError();
  }
  return Object.freeze({
    status: payload.status,
    nodeCount: payload.node_count,
    cpuUsage: payload.cpu_usage,
    memoryUsage: payload.memory_usage,
    checkedAt: payload.checked_at,
  });
}

function normalizeQuery(query: RuntimeClustersQuery) {
  const page = query.page ?? 1;
  const pageSize = query.pageSize ?? 20;
  const search = (query.search ?? '').trim();
  const status = (query.status ?? 'all').trim();
  if (
    !isPositiveInteger(page) ||
    !isPositiveInteger(pageSize) ||
    pageSize > 100 ||
    search.length > 200 ||
    !status
  ) {
    throw new RuntimeClustersUnavailableError(
      'runtime_clusters_query_invalid',
    );
  }
  return Object.freeze({ page, pageSize, search, status });
}

function errorMessage(status: number, payload: unknown): string {
  if (isRecord(payload) && typeof payload.detail === 'string') {
    return payload.detail;
  }
  return `Runtime Clusters request failed (${status})`;
}

function identifier(value: string): string {
  if (!value || value !== value.trim()) {
    throw new RuntimeClustersUnavailableError(
      'runtime_clusters_identifier_invalid',
    );
  }
  return value;
}

function contractError(): RuntimeClustersUnavailableError {
  return new RuntimeClustersUnavailableError(
    'runtime_clusters_response_contract_invalid',
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) > 0;
}

function isNonnegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function isNullableNonnegativeNumber(value: unknown): value is number | null {
  return (
    value === null ||
    (typeof value === 'number' && Number.isFinite(value) && value >= 0)
  );
}
