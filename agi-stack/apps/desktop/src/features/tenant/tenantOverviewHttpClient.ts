import {
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import { desktopApiFetch } from '../../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../../types';
import type {
  TenantOverviewAvailability,
  TenantOverviewClient,
  TenantOverviewField,
  TenantOverviewMemoryPoint,
  TenantOverviewProject,
  TenantOverviewReadOptions,
  TenantOverviewScope,
  TenantOverviewSnapshot,
  TenantOverviewStorage,
} from './tenantOverviewClient';

export function createTenantOverviewHttpClient(
  config: DesktopRuntimeConfig,
): TenantOverviewClient {
  const runtimeConfig = Object.freeze({ ...config });
  return Object.freeze({
    async load(scope, options) {
      requireRuntimeScope(runtimeConfig, scope);
      const payload = await requestJson(
        runtimeConfig,
        `/api/v1/tenants/${encodeURIComponent(scope.tenantId)}/stats`,
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
  options?: TenantOverviewReadOptions,
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
    throw contractError(`${config.mode}_tenant_overview_contract_invalid`);
  }
  return payload;
}

function projectCloudSnapshot(
  payload: unknown,
  scope: TenantOverviewScope,
): TenantOverviewSnapshot {
  if (!isRecord(payload)) throw contractError('cloud_tenant_overview_contract_invalid');
  const storage = requireStorage(payload.storage, 'cloud_tenant_overview_contract_invalid');
  const projects = requireCloudProjects(payload.projects);
  const members = requireMembers(payload.members, 'cloud_tenant_overview_contract_invalid');
  const history = requireHistory(payload.memory_history, 'cloud_tenant_overview_contract_invalid');
  const tenantInfo = requireCloudTenantInfo(payload.tenant_info);
  return Object.freeze({
    scope,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    serviceVersion: 'cloud',
    contractVersion: '3.0.0',
    allowedActions: Object.freeze(['view']),
    authorityRevision: null,
    tenantInfo,
    storage: availableField(storage),
    projects: {
      availability: 'available',
      reasonCode: null,
      value: projects.list,
      active: projects.active,
      newThisWeek: projects.newThisWeek,
    } satisfies TenantOverviewSnapshot['projects'],
    members: availableField(members),
    memoryHistory: availableField(history),
  });
}

function projectLocalSnapshot(
  payload: unknown,
  scope: TenantOverviewScope,
): TenantOverviewSnapshot {
  const reason = 'local_tenant_overview_contract_invalid';
  if (
    !isRecord(payload) ||
    payload.capability !== 'tenant_overview' ||
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
    !isRecord(payload.tenant_info)
  ) {
    throw contractError(reason);
  }
  const tenantInfo = payload.tenant_info;
  if (
    !isNonEmptyString(tenantInfo.organization_id) ||
    !isNonEmptyString(tenantInfo.plan)
  ) {
    throw contractError(reason);
  }
  const storage = requireLocalField(payload.storage, reason, (value) =>
    value === null ? null : requireStorage(value, reason),
  );
  const projects = requireLocalProjects(payload.projects, reason);
  const members = requireMembers(payload.members, reason);
  const memoryHistory = requireLocalField(payload.memory_history, reason, (value) =>
    requireHistory(value, reason),
  );
  return Object.freeze({
    scope,
    authority: 'local',
    availability: payload.availability,
    reasonCode: payload.reason_code,
    serviceVersion: payload.service_version,
    contractVersion: payload.contract_version,
    allowedActions: Object.freeze([...payload.allowed_actions]),
    authorityRevision: payload.authority_revision,
    tenantInfo: {
      organizationId: tenantInfo.organization_id,
      plan: tenantInfo.plan,
      region: requireLocalField(tenantInfo.region, reason, requireNullableString),
      nextBillingDate: requireLocalField(
        tenantInfo.next_billing_date,
        reason,
        requireNullableString,
      ),
    },
    storage,
    projects,
    members: availableField(members),
    memoryHistory,
  });
}

function requireCloudProjects(payload: unknown): Readonly<{
  active: number;
  newThisWeek: number;
  list: readonly TenantOverviewProject[];
}> {
  const reason = 'cloud_tenant_overview_contract_invalid';
  if (
    !isRecord(payload) ||
    !isNonnegativeInteger(payload.active) ||
    !isNonnegativeInteger(payload.new_this_week) ||
    !Array.isArray(payload.list)
  ) {
    throw contractError(reason);
  }
  return {
    active: payload.active,
    newThisWeek: payload.new_this_week,
    list: payload.list.map((project) => requireCloudProject(project, reason)),
  };
}

function requireCloudProject(payload: unknown, reason: string): TenantOverviewProject {
  if (
    !isRecord(payload) ||
    !isNonEmptyString(payload.id) ||
    !isNonEmptyString(payload.name) ||
    !isNonEmptyString(payload.owner) ||
    !isNonEmptyString(payload.memory_consumed) ||
    !isNonEmptyString(payload.status)
  ) {
    throw contractError(reason);
  }
  return {
    id: payload.id,
    name: payload.name,
    owner: availableField(payload.owner),
    memoryConsumed: availableField(payload.memory_consumed),
    status: payload.status,
  };
}

function requireLocalProjects(payload: unknown, reason: string) {
  if (
    !isRecord(payload) ||
    !isAvailability(payload.availability) ||
    !isNullableReason(payload.reason_code) ||
    !isNonnegativeInteger(payload.active) ||
    !isNonnegativeInteger(payload.new_this_week) ||
    !Array.isArray(payload.list)
  ) {
    throw contractError(reason);
  }
  return {
    availability: payload.availability,
    reasonCode: payload.reason_code,
    active: payload.active,
    newThisWeek: payload.new_this_week,
    value: payload.list.map((project) => {
      if (
        !isRecord(project) ||
        !isNonEmptyString(project.id) ||
        !isNonEmptyString(project.name) ||
        !isNonEmptyString(project.status)
      ) {
        throw contractError(reason);
      }
      return {
        id: project.id,
        name: project.name,
        owner: requireLocalField(project.owner, reason, requireNullableString),
        memoryConsumed: requireLocalField(
          project.memory_consumed,
          reason,
          requireNullableString,
        ),
        status: project.status,
      };
    }),
  };
}

function requireLocalField<T>(
  payload: unknown,
  reason: string,
  readValue: (value: unknown) => T,
): TenantOverviewField<T> {
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

function requireStorage(payload: unknown, reason: string): TenantOverviewStorage {
  if (
    !isRecord(payload) ||
    !isFiniteNonnegative(payload.used) ||
    !isFiniteNonnegative(payload.total) ||
    !isFiniteNonnegative(payload.percentage) ||
    payload.percentage > 100
  ) {
    throw contractError(reason);
  }
  return { used: payload.used, total: payload.total, percentage: payload.percentage };
}

function requireMembers(payload: unknown, reason: string) {
  if (
    !isRecord(payload) ||
    !isNonnegativeInteger(payload.total) ||
    !isNonnegativeInteger(payload.new_added)
  ) {
    throw contractError(reason);
  }
  return { total: payload.total, newAdded: payload.new_added };
}

function requireHistory(payload: unknown, reason: string): readonly TenantOverviewMemoryPoint[] {
  if (!Array.isArray(payload)) throw contractError(reason);
  return payload.map((point) => {
    if (
      !isRecord(point) ||
      !isNonEmptyString(point.date) ||
      !isFiniteNonnegative(point.used) ||
      !isFiniteNonnegative(point.daily_added) ||
      !isNonnegativeInteger(point.memory_count) ||
      !isFiniteNonnegative(point.percentage) ||
      point.percentage > 100
    ) {
      throw contractError(reason);
    }
    return {
      date: point.date,
      used: point.used,
      dailyAdded: point.daily_added,
      memoryCount: point.memory_count,
      percentage: point.percentage,
    };
  });
}

function requireCloudTenantInfo(payload: unknown) {
  const reason = 'cloud_tenant_overview_contract_invalid';
  if (
    !isRecord(payload) ||
    !isNonEmptyString(payload.organization_id) ||
    !isNonEmptyString(payload.plan) ||
    !isNullableString(payload.region) ||
    !isNullableString(payload.next_billing_date)
  ) {
    throw contractError(reason);
  }
  return {
    organizationId: payload.organization_id,
    plan: payload.plan,
    region: availableField(payload.region),
    nextBillingDate: availableField(payload.next_billing_date),
  };
}

function requireRuntimeScope(
  config: DesktopRuntimeConfig,
  scope: TenantOverviewScope,
): void {
  if (
    !isRecord(scope) ||
    scope.authority !== config.mode ||
    !isNonEmptyString(scope.tenantId) ||
    scope.tenantId !== config.tenantId
  ) {
    throw contractError('tenant_overview_runtime_scope_mismatch');
  }
}

function availableField<T>(value: T): TenantOverviewField<T> {
  return { availability: 'available', reasonCode: null, value };
}

function requireNullableString(value: unknown): string | null {
  if (!isNullableString(value)) {
    throw contractError('local_tenant_overview_contract_invalid');
  }
  return value;
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

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isNullableIdentifier(value: unknown): boolean {
  return value === null || isNonEmptyString(value);
}

function isNullableReason(value: unknown): value is string | null {
  return value === null || isNonEmptyString(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isNonEmptyString);
}

function isFiniteNonnegative(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}

function isNonnegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function isAvailability(value: unknown): value is TenantOverviewAvailability {
  return (
    value === 'available' ||
    value === 'degraded' ||
    value === 'unavailable' ||
    value === 'not_applicable'
  );
}
