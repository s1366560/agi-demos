import {
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import { desktopApiFetch } from '../../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../../types';
import type {
  CloudProjectOverviewClient,
  CloudProjectOverviewMemory,
  CloudProjectOverviewMemoryPage,
  CloudProjectOverviewMemoryQuery,
  CloudProjectOverviewProject,
  CloudProjectOverviewReadOptions,
  CloudProjectOverviewScope,
  CloudProjectOverviewStats,
} from './projectOverviewClient';

export function createCloudProjectOverviewClient(
  config: DesktopRuntimeConfig,
): CloudProjectOverviewClient {
  if (config.mode !== 'cloud') {
    throw contractError('cloud_project_overview_config_required');
  }
  const runtimeConfig = Object.freeze({ ...config });
  const client: CloudProjectOverviewClient = {
    async getProject(scope, options) {
      const currentScope = requireCloudScope(scope);
      const payload = await requestCloudJson(
        runtimeConfig,
        projectPath(currentScope),
        options,
      );
      return requireProject(payload, currentScope);
    },
    async getProjectStats(scope, options) {
      const currentScope = requireCloudScope(scope);
      const payload = await requestCloudJson(
        runtimeConfig,
        `${projectRoot(currentScope)}/stats`,
        options,
      );
      return requireStats(payload, currentScope);
    },
    async listMemories(scope, query, options) {
      const currentScope = requireCloudScope(scope);
      requireLatestMemoriesQuery(query);
      const payload = await requestCloudJson(
        runtimeConfig,
        latestMemoriesPath(currentScope),
        options,
      );
      return requireMemoryPage(payload, currentScope);
    },
  };
  return Object.freeze(client);
}

async function requestCloudJson(
  config: DesktopRuntimeConfig,
  path: string,
  options?: CloudProjectOverviewReadOptions,
): Promise<unknown> {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);

  const response = await desktopApiFetch(config, path, {
    method: 'GET',
    headers,
    signal: options?.signal,
  });
  const contentType = response.headers.get('content-type') ?? '';
  const isJson = contentType.toLowerCase().includes('application/json');
  const payload = isJson
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '');
  if (!response.ok) {
    throw new DesktopApiError(errorMessage(response.status, payload), response.status, payload);
  }
  if (!isJson || payload === null) {
    throw contractError('cloud_project_overview_response_invalid');
  }
  return payload;
}

function requireCloudScope(scope: CloudProjectOverviewScope): CloudProjectOverviewScope {
  if (
    !isRecord(scope) ||
    scope.authority !== 'cloud' ||
    !isExactIdentifier(scope.tenantId) ||
    !isExactIdentifier(scope.projectId)
  ) {
    throw contractError('cloud_project_overview_scope_invalid');
  }
  return scope;
}

function requireLatestMemoriesQuery(query: CloudProjectOverviewMemoryQuery): void {
  if (!isRecord(query) || query.page !== 1 || query.page_size !== 5) {
    throw contractError('cloud_project_overview_memory_query_invalid');
  }
}

function requireProject(
  payload: unknown,
  scope: CloudProjectOverviewScope,
): CloudProjectOverviewProject {
  if (!isRecord(payload)) {
    throw contractError('cloud_project_overview_response_invalid');
  }
  if (payload.id !== scope.projectId || payload.tenant_id !== scope.tenantId) {
    throw contractError('cloud_project_overview_project_scope_invalid');
  }
  if (
    !isNonEmptyString(payload.name) ||
    !isNullableString(payload.description) ||
    !isNullableString(payload.created_at) ||
    !isNullableString(payload.updated_at)
  ) {
    throw contractError('cloud_project_overview_project_invalid');
  }
  return {
    id: payload.id,
    tenant_id: payload.tenant_id,
    name: payload.name,
    description: payload.description,
    created_at: payload.created_at,
    updated_at: payload.updated_at,
  };
}

function requireStats(
  payload: unknown,
  scope: CloudProjectOverviewScope,
): CloudProjectOverviewStats {
  if (
    isRecord(payload) &&
    ((Object.hasOwn(payload, 'tenant_id') && payload.tenant_id !== scope.tenantId) ||
      (Object.hasOwn(payload, 'project_id') && payload.project_id !== scope.projectId))
  ) {
    throw contractError('cloud_project_overview_stats_scope_invalid');
  }
  if (
    !isRecord(payload) ||
    !isFiniteNonnegative(payload.memory_count) ||
    !isFiniteNonnegative(payload.storage_used) ||
    !isFiniteNonnegative(payload.storage_limit) ||
    !isFiniteNonnegative(payload.active_nodes) ||
    !isFiniteNonnegative(payload.collaborators)
  ) {
    throw contractError('cloud_project_overview_stats_invalid');
  }
  return {
    memory_count: payload.memory_count,
    storage_used: payload.storage_used,
    storage_limit: payload.storage_limit,
    active_nodes: payload.active_nodes,
    collaborators: payload.collaborators,
  };
}

function requireMemoryPage(
  payload: unknown,
  scope: CloudProjectOverviewScope,
): CloudProjectOverviewMemoryPage {
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.memories) ||
    payload.memories.length > 5 ||
    !Number.isSafeInteger(payload.total) ||
    Number(payload.total) < payload.memories.length ||
    payload.page !== 1 ||
    payload.page_size !== 5
  ) {
    throw contractError('cloud_project_overview_memory_page_invalid');
  }
  if (
    (Object.hasOwn(payload, 'tenant_id') && payload.tenant_id !== scope.tenantId) ||
    (Object.hasOwn(payload, 'project_id') && payload.project_id !== scope.projectId)
  ) {
    throw contractError('cloud_project_overview_memory_scope_invalid');
  }
  const memories = payload.memories.map((memory) => requireMemory(memory, scope));
  return {
    memories,
    total: Number(payload.total),
    page: 1,
    page_size: 5,
  };
}

function requireMemory(
  payload: unknown,
  scope: CloudProjectOverviewScope,
): CloudProjectOverviewMemory {
  if (!isRecord(payload)) {
    throw contractError('cloud_project_overview_memory_page_invalid');
  }
  if (payload.project_id !== scope.projectId) {
    throw contractError('cloud_project_overview_memory_scope_invalid');
  }
  if (
    !isNonEmptyString(payload.id) ||
    !isNonEmptyString(payload.title) ||
    typeof payload.content !== 'string' ||
    !isNonEmptyString(payload.content_type) ||
    !isNonEmptyString(payload.status) ||
    !isRecord(payload.metadata) ||
    !isNonEmptyString(payload.created_at) ||
    !isNullableString(payload.updated_at)
  ) {
    throw contractError('cloud_project_overview_memory_page_invalid');
  }
  return {
    id: payload.id,
    project_id: payload.project_id,
    title: payload.title,
    content: payload.content,
    content_type: payload.content_type,
    status: payload.status,
    metadata: payload.metadata,
    created_at: payload.created_at,
    updated_at: payload.updated_at,
  };
}

function projectPath(scope: CloudProjectOverviewScope): string {
  return `${projectRoot(scope)}?tenant_id=${encodeURIComponent(scope.tenantId)}`;
}

function projectRoot(scope: CloudProjectOverviewScope): string {
  return `/api/v1/projects/${encodeURIComponent(scope.projectId)}`;
}

function latestMemoriesPath(scope: CloudProjectOverviewScope): string {
  return (
    '/api/v1/memories/?page=1&page_size=5&project_id=' +
    encodeURIComponent(scope.projectId)
  );
}

function errorMessage(status: number, payload: unknown): string {
  if (isRecord(payload) && typeof payload.detail === 'string' && payload.detail.trim()) {
    return payload.detail;
  }
  return `HTTP ${status}`;
}

function contractError(reasonCode: string): DesktopApiError {
  return new DesktopApiError(reasonCode, 0, { reason_code: reasonCode });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isExactIdentifier(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isFiniteNonnegative(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}
