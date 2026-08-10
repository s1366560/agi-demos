import {
  absoluteUrl,
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import { desktopApiFetch } from '../../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../../types';
import type {
  RuntimeInstanceSummary,
  RuntimeInstancesClient,
  RuntimeInstancesNormalizedQuery,
  RuntimeInstancesPage,
  RuntimeInstancesQuery,
  RuntimeInstancesScope,
} from './runtimeInstancesTypes';

type Fetch = typeof globalThis.fetch;
type FetchPath = (path: string, init: RequestInit) => Promise<Response>;
type LocalRuntimeStatusReader = () => Promise<unknown>;

export type RuntimeInstancesClientDependencies = Readonly<{
  fetch?: Fetch;
  readLocalRuntimeStatus?: LocalRuntimeStatusReader;
}>;

export class RuntimeInstancesUnavailableError extends Error {
  readonly reasonCode: string;

  constructor(reasonCode: string) {
    super(reasonCode);
    this.name = 'RuntimeInstancesUnavailableError';
    this.reasonCode = reasonCode;
  }
}
const DEFAULT_QUERY: RuntimeInstancesNormalizedQuery = Object.freeze({
  page: 1,
  pageSize: 20,
  search: '',
  status: 'all',
});

export function createRuntimeInstancesClient(
  config: DesktopRuntimeConfig,
  dependencies: RuntimeInstancesClientDependencies = {},
): RuntimeInstancesClient {
  const runtimeConfig = Object.freeze({ ...config });
  const fetchPath: FetchPath = dependencies.fetch
    ? (path, init) => dependencies.fetch!(absoluteUrl(runtimeConfig.apiBaseUrl, path), init)
    : (path, init) => desktopApiFetch(runtimeConfig, path, init);
  const readLocalRuntimeStatus =
    dependencies.readLocalRuntimeStatus ?? defaultLocalRuntimeStatusReader;

  return Object.freeze({
    async list(scope, query = {}, options) {
      requireScope(runtimeConfig, scope);
      const normalized = normalizeQuery(query);
      if (scope.authority === 'local') {
        const payload = await readLocalRuntimeStatus();
        if (options?.signal?.aborted) throw abortError();
        return localPage(payload, normalized);
      }
      const params = new URLSearchParams({
        page: String(normalized.page),
        page_size: String(normalized.pageSize),
      });
      if (normalized.search) params.set('search', normalized.search);
      if (normalized.status !== 'all') params.set('status', normalized.status);
      const payload = await requestJson(
        runtimeConfig,
        `/api/v1/instances/?${params.toString()}`,
        'GET',
        fetchPath,
        options?.signal,
      );
      return parseCloudPage(payload, scope);
    },
    async restart(scope, instanceId, options) {
      requireCloudMutation(runtimeConfig, scope);
      await requestJson(
        runtimeConfig,
        `/api/v1/instances/${encodeURIComponent(identifier(instanceId))}/restart`,
        'POST',
        fetchPath,
        options?.signal,
      );
    },
    async delete(scope, instanceId, options) {
      requireCloudMutation(runtimeConfig, scope);
      await requestJson(
        runtimeConfig,
        `/api/v1/instances/${encodeURIComponent(identifier(instanceId))}`,
        'DELETE',
        fetchPath,
        options?.signal,
      );
    },
  });
}

function requireScope(
  config: DesktopRuntimeConfig,
  scope: RuntimeInstancesScope,
): void {
  if (
    config.mode !== scope.authority ||
    identifier(config.tenantId) !== identifier(scope.tenantId)
  ) {
    throw new RuntimeInstancesUnavailableError(
      'runtime_instances_runtime_scope_mismatch',
    );
  }
}

function requireCloudMutation(
  config: DesktopRuntimeConfig,
  scope: RuntimeInstancesScope,
): void {
  requireScope(config, scope);
  if (scope.authority !== 'cloud') {
    throw new RuntimeInstancesUnavailableError(
      'local_instance_lifecycle_not_applicable',
    );
  }
}

async function requestJson(
  config: DesktopRuntimeConfig,
  path: string,
  method: 'GET' | 'POST' | 'DELETE',
  fetchPath: FetchPath,
  signal?: AbortSignal,
): Promise<unknown> {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  const response = await fetchPath(path, {
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
    throw new DesktopApiError(
      errorMessage(response.status, payload),
      response.status,
      payload,
    );
  }
  if (method === 'GET' && (!isJson || payload === null)) {
    throw contractError();
  }
  return payload;
}

function parseCloudPage(
  payload: unknown,
  scope: RuntimeInstancesScope,
): RuntimeInstancesPage {
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.instances) ||
    !isNonnegativeInteger(payload.total) ||
    !isPositiveInteger(payload.page) ||
    !isPositiveInteger(payload.page_size)
  ) {
    throw contractError();
  }
  const instances = payload.instances.map((value) =>
    parseCloudInstance(value, scope),
  );
  if (instances.length > payload.total) throw contractError();
  return Object.freeze({
    instances: Object.freeze(instances),
    total: payload.total,
    page: payload.page,
    pageSize: payload.page_size,
  });
}

function parseCloudInstance(
  value: unknown,
  scope: RuntimeInstancesScope,
): RuntimeInstanceSummary {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value.id) ||
    !isNonEmptyString(value.name) ||
    !isNonEmptyString(value.status) ||
    !isNullableString(value.health_status) ||
    !isNullableString(value.image_version) ||
    !isNullableNonnegativeInteger(value.replicas) ||
    !isNullableNonnegativeInteger(value.available_replicas) ||
    !isNullableString(value.cluster_id) ||
    !isNullableString(value.created_at) ||
    !isNullableString(value.updated_at) ||
    (value.tenant_id !== undefined && value.tenant_id !== scope.tenantId)
  ) {
    throw contractError();
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

function localPage(
  payload: unknown,
  query: RuntimeInstancesNormalizedQuery,
): RuntimeInstancesPage {
  if (
    !isRecord(payload) ||
    typeof payload.running !== 'boolean' ||
    !isNonnegativeInteger(payload.tool_count) ||
    !Array.isArray(payload.runtime_providers)
  ) {
    throw contractError();
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
    `${instance.id} ${instance.name} ${instance.status}`
      .toLocaleLowerCase()
      .includes(search);
  const matchesStatus =
    query.status === 'all' || query.status === instance.status;
  const instances = matchesSearch && matchesStatus ? [instance] : [];
  return Object.freeze({
    instances: Object.freeze(instances),
    total: instances.length,
    page: 1,
    pageSize: query.pageSize,
  });
}

function normalizeQuery(
  query: RuntimeInstancesQuery,
): RuntimeInstancesNormalizedQuery {
  const page = query.page ?? DEFAULT_QUERY.page;
  const pageSize = query.pageSize ?? DEFAULT_QUERY.pageSize;
  const search = (query.search ?? DEFAULT_QUERY.search).trim();
  const status = (query.status ?? DEFAULT_QUERY.status).trim();
  if (
    !isPositiveInteger(page) ||
    !isPositiveInteger(pageSize) ||
    pageSize > 100 ||
    search.length > 200 ||
    !status
  ) {
    throw new RuntimeInstancesUnavailableError(
      'runtime_instances_query_invalid',
    );
  }
  return Object.freeze({ page, pageSize, search, status });
}

async function defaultLocalRuntimeStatusReader(): Promise<unknown> {
  const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke;
  if (!invoke) {
    throw new RuntimeInstancesUnavailableError(
      'runtime_instances_native_bridge_unavailable',
    );
  }
  return invoke<unknown>('local_runtime_status');
}

function identifier(value: string): string {
  if (!value || value !== value.trim()) {
    throw new RuntimeInstancesUnavailableError(
      'runtime_instances_identifier_invalid',
    );
  }
  return value;
}

function errorMessage(status: number, payload: unknown): string {
  if (isRecord(payload) && isNonEmptyString(payload.detail)) {
    return payload.detail;
  }
  return `Request failed (${String(status)})`;
}

function contractError(): DesktopApiError {
  return new DesktopApiError('runtime_instances_contract_invalid', 502, null);
}

function abortError(): DOMException {
  return new DOMException('The operation was aborted.', 'AbortError');
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

function isPositiveInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) > 0;
}

function isNonnegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function isNullableNonnegativeInteger(
  value: unknown,
): value is number | null {
  return value === null || isNonnegativeInteger(value);
}
