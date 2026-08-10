import {
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import { desktopApiFetch } from '../../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../../types';
import type {
  TenantAnalyticsAvailability,
  TenantAnalyticsClient,
  TenantAnalyticsField,
  TenantAnalyticsMemoryPoint,
  TenantAnalyticsPeriod,
  TenantAnalyticsProjectStorage,
  TenantAnalyticsReadOptions,
  TenantAnalyticsScope,
  TenantAnalyticsSnapshot,
} from './tenantAnalyticsClient';

const PERIOD_DAYS: Readonly<Record<TenantAnalyticsPeriod, number>> = {
  '7d': 7,
  '30d': 30,
  '90d': 90,
};

export function createTenantAnalyticsHttpClient(
  config: DesktopRuntimeConfig,
): TenantAnalyticsClient {
  const runtimeConfig = Object.freeze({ ...config });
  return Object.freeze({
    async load(scope, options) {
      requireRuntimeScope(runtimeConfig, scope);
      const query = new URLSearchParams({ period: scope.period });
      const payload = await requestJson(
        runtimeConfig,
        `/api/v1/tenants/${encodeURIComponent(scope.tenantId)}/analytics?${query}`,
        options,
      );
      return runtimeConfig.mode === 'cloud'
        ? projectCloudSnapshot(payload, scope)
        : projectLocalSnapshot(payload, scope);
    },
  });
}

async function requestJson(
  config: DesktopRuntimeConfig,
  path: string,
  options?: TenantAnalyticsReadOptions,
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
    throw new DesktopApiError(
      errorMessage(response.status, payload),
      response.status,
      payload,
    );
  }
  if (!isJson || payload === null) {
    throw contractError(`${config.mode}_tenant_analytics_contract_invalid`);
  }
  return payload;
}

function projectCloudSnapshot(
  payload: unknown,
  scope: TenantAnalyticsScope,
): TenantAnalyticsSnapshot {
  const reason = 'cloud_tenant_analytics_contract_invalid';
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.memoryGrowth) ||
    !Array.isArray(payload.projectStorage) ||
    !isRecord(payload.summary)
  ) {
    throw contractError(reason);
  }
  const summary = payload.summary;
  if (
    !isNonnegativeInteger(summary.total_memories) ||
    !isFiniteNonnegative(summary.total_storage_bytes) ||
    !isNonnegativeInteger(summary.total_projects) ||
    summary.period_days !== PERIOD_DAYS[scope.period]
  ) {
    throw contractError(reason);
  }
  return Object.freeze({
    scope,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    serviceVersion: 'cloud',
    contractVersion: '3.0.0',
    allowedActions: Object.freeze(['view', 'retry']),
    authorityRevision: null,
    memoryGrowth: availableField(
      Object.freeze(payload.memoryGrowth.map((point) => readMemoryPoint(point, reason))),
    ),
    projectStorage: availableField(
      Object.freeze(
        payload.projectStorage.map((project) =>
          readCloudProjectStorage(project, reason),
        ),
      ),
    ),
    summary: {
      totalMemories: availableField(summary.total_memories),
      totalStorageBytes: availableField(summary.total_storage_bytes),
      totalProjects: availableField(summary.total_projects),
      periodDays: summary.period_days,
    },
  });
}

function projectLocalSnapshot(
  payload: unknown,
  scope: TenantAnalyticsScope,
): TenantAnalyticsSnapshot {
  const reason = 'local_tenant_analytics_contract_invalid';
  if (
    !isRecord(payload) ||
    payload.capability !== 'tenant_analytics' ||
    !isAvailability(payload.availability) ||
    !isNullableReason(payload.reason_code) ||
    !isNonEmptyString(payload.service_version) ||
    !isNonEmptyString(payload.contract_version) ||
    !isStringArray(payload.allowed_actions) ||
    !isRecord(payload.scope) ||
    payload.scope.tenant_id !== scope.tenantId ||
    !isNullableIdentifier(payload.scope.project_id) ||
    !isNullableIdentifier(payload.scope.workspace_id) ||
    !isNullableIdentifier(payload.scope.instance_id) ||
    !isNonnegativeInteger(payload.authority_revision) ||
    !isRecord(payload.summary)
  ) {
    throw contractError(reason);
  }
  const summary = payload.summary;
  if (summary.period_days !== PERIOD_DAYS[scope.period]) {
    throw contractError(reason);
  }
  return Object.freeze({
    scope,
    authority: 'local',
    availability: payload.availability,
    reasonCode: payload.reason_code,
    serviceVersion: payload.service_version,
    contractVersion: payload.contract_version,
    allowedActions: Object.freeze([...payload.allowed_actions]),
    authorityRevision: payload.authority_revision,
    memoryGrowth: readField(payload.memoryGrowth, reason, (value) => {
      if (!Array.isArray(value)) throw contractError(reason);
      return Object.freeze(value.map((point) => readMemoryPoint(point, reason)));
    }),
    projectStorage: readField(payload.projectStorage, reason, (value) => {
      if (!Array.isArray(value)) throw contractError(reason);
      return Object.freeze(
        value.map((project) => readLocalProjectStorage(project, reason)),
      );
    }),
    summary: {
      totalMemories: readField(
        summary.total_memories,
        reason,
        readNullableNonnegativeInteger,
      ),
      totalStorageBytes: readField(
        summary.total_storage_bytes,
        reason,
        readNullableFiniteNonnegative,
      ),
      totalProjects: readField(
        summary.total_projects,
        reason,
        readNullableNonnegativeInteger,
      ),
      periodDays: summary.period_days,
    },
  });
}

function readMemoryPoint(
  payload: unknown,
  reason: string,
): TenantAnalyticsMemoryPoint {
  if (
    !isRecord(payload) ||
    !isNonEmptyString(payload.date) ||
    !isNonnegativeInteger(payload.count)
  ) {
    throw contractError(reason);
  }
  return { date: payload.date, count: payload.count };
}

function readCloudProjectStorage(
  payload: unknown,
  reason: string,
): TenantAnalyticsProjectStorage {
  if (
    !isRecord(payload) ||
    !isNonEmptyString(payload.name) ||
    !isFiniteNonnegative(payload.storage_bytes) ||
    !isNonnegativeInteger(payload.memory_count)
  ) {
    throw contractError(reason);
  }
  return {
    name: payload.name,
    storageBytes: availableField(payload.storage_bytes),
    memoryCount: availableField(payload.memory_count),
  };
}

function readLocalProjectStorage(
  payload: unknown,
  reason: string,
): TenantAnalyticsProjectStorage {
  if (!isRecord(payload) || !isNonEmptyString(payload.name)) {
    throw contractError(reason);
  }
  return {
    name: payload.name,
    storageBytes: readField(
      payload.storage_bytes,
      reason,
      readNullableFiniteNonnegative,
    ),
    memoryCount: readField(
      payload.memory_count,
      reason,
      readNullableNonnegativeInteger,
    ),
  };
}

function readField<T>(
  payload: unknown,
  reason: string,
  readValue: (value: unknown) => T,
): TenantAnalyticsField<T> {
  if (
    !isRecord(payload) ||
    !isAvailability(payload.availability) ||
    !isNullableReason(payload.reason_code) ||
    !Object.hasOwn(payload, 'value')
  ) {
    throw contractError(reason);
  }
  return {
    availability: payload.availability,
    reasonCode: payload.reason_code,
    value: readValue(payload.value),
  };
}

function availableField<T>(value: T): TenantAnalyticsField<T> {
  return { availability: 'available', reasonCode: null, value };
}

function requireRuntimeScope(
  config: DesktopRuntimeConfig,
  scope: TenantAnalyticsScope,
): void {
  if (
    !isRecord(scope) ||
    scope.authority !== config.mode ||
    !isNonEmptyString(scope.tenantId) ||
    scope.tenantId !== config.tenantId ||
    !Object.hasOwn(PERIOD_DAYS, scope.period)
  ) {
    throw contractError('tenant_analytics_runtime_scope_mismatch');
  }
}

function readNullableNonnegativeInteger(value: unknown): number | null {
  if (value === null || isNonnegativeInteger(value)) return value;
  throw contractError('local_tenant_analytics_contract_invalid');
}

function readNullableFiniteNonnegative(value: unknown): number | null {
  if (value === null || isFiniteNonnegative(value)) return value;
  throw contractError('local_tenant_analytics_contract_invalid');
}

function errorMessage(status: number, payload: unknown): string {
  if (isRecord(payload) && typeof payload.detail === 'string' && payload.detail.trim()) {
    return payload.detail;
  }
  return `Tenant analytics request failed (${status})`;
}

function contractError(reasonCode: string): DesktopApiError {
  return new DesktopApiError(reasonCode, 0, { reason_code: reasonCode });
}

function isAvailability(value: unknown): value is TenantAnalyticsAvailability {
  return (
    value === 'available' ||
    value === 'degraded' ||
    value === 'unavailable' ||
    value === 'not_applicable'
  );
}

function isNullableReason(value: unknown): value is string | null {
  return value === null || isNonEmptyString(value);
}

function isNullableIdentifier(value: unknown): value is string | null {
  return value === null || isNonEmptyString(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isNonEmptyString);
}

function isNonnegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function isFiniteNonnegative(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
