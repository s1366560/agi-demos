import { DesktopApiError } from '../api/client';
import type {
  TenantOverviewAvailability,
  TenantOverviewField,
  TenantOverviewMemoryPoint,
  TenantOverviewProject,
  TenantOverviewScope,
  TenantOverviewSnapshot,
  TenantOverviewStorage,
} from '../features/tenant/tenantOverviewClient';

export function projectDesktopTenantOverviewResponseV2(
  payload: unknown,
  scope: TenantOverviewScope,
): TenantOverviewSnapshot {
  return scope.authority === 'cloud'
    ? projectCloudSnapshotV2(payload, scope)
    : projectLocalSnapshotV2(payload, scope);
}

export function requireDesktopTenantOverviewSnapshotV2(
  payload: unknown,
  expectedScope: TenantOverviewScope,
): TenantOverviewSnapshot {
  const reason = 'desktop_tenant_overview_service_contract_invalid';
  if (
    !isRecordV2(payload) ||
    !isRecordV2(payload.scope) ||
    payload.scope.authority !== expectedScope.authority ||
    payload.scope.tenantId !== expectedScope.tenantId ||
    payload.authority !== expectedScope.authority ||
    !isAvailabilityV2(payload.availability) ||
    !isNullableReasonV2(payload.reasonCode) ||
    !isNonEmptyStringV2(payload.serviceVersion) ||
    !isNonEmptyStringV2(payload.contractVersion) ||
    !isStringArrayV2(payload.allowedActions) ||
    !isNullableRevisionV2(payload.authorityRevision) ||
    !isRecordV2(payload.tenantInfo) ||
    !isNonEmptyStringV2(payload.tenantInfo.organizationId) ||
    !isNonEmptyStringV2(payload.tenantInfo.plan)
  ) {
    throw tenantOverviewContractErrorV2(reason);
  }
  const scope = Object.freeze({ ...expectedScope });
  return freezeDeepV2({
    scope,
    authority: expectedScope.authority,
    availability: payload.availability,
    reasonCode: payload.reasonCode,
    serviceVersion: payload.serviceVersion,
    contractVersion: payload.contractVersion,
    allowedActions: [...payload.allowedActions],
    authorityRevision: payload.authorityRevision,
    tenantInfo: {
      organizationId: payload.tenantInfo.organizationId,
      plan: payload.tenantInfo.plan,
      region: requireProjectedFieldV2(
        payload.tenantInfo.region,
        reason,
        requireNullableStringV2,
      ),
      nextBillingDate: requireProjectedFieldV2(
        payload.tenantInfo.nextBillingDate,
        reason,
        requireNullableStringV2,
      ),
    },
    storage: requireProjectedFieldV2(payload.storage, reason, (value) =>
      value === null ? null : requireStorageV2(value, reason),
    ),
    projects: requireProjectedProjectsV2(payload.projects, reason),
    members: requireProjectedFieldV2(payload.members, reason, (value) =>
      requireProjectedMembersV2(value, reason),
    ),
    memoryHistory: requireProjectedFieldV2(payload.memoryHistory, reason, (value) =>
      requireProjectedHistoryV2(value, reason),
    ),
  } satisfies TenantOverviewSnapshot);
}

function projectCloudSnapshotV2(
  payload: unknown,
  scope: TenantOverviewScope,
): TenantOverviewSnapshot {
  const reason = 'cloud_tenant_overview_contract_invalid';
  if (!isRecordV2(payload)) throw tenantOverviewContractErrorV2(reason);
  const storage = requireStorageV2(payload.storage, reason);
  const projects = requireCloudProjectsV2(payload.projects);
  const members = requireRawMembersV2(payload.members, reason);
  const history = requireRawHistoryV2(payload.memory_history, reason);
  const tenantInfo = requireCloudTenantInfoV2(payload.tenant_info);
  return freezeDeepV2({
    scope: { ...scope },
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    serviceVersion: 'cloud',
    contractVersion: '3.0.0',
    allowedActions: ['view'],
    authorityRevision: null,
    tenantInfo,
    storage: availableFieldV2(storage),
    projects: {
      availability: 'available',
      reasonCode: null,
      value: projects.list,
      active: projects.active,
      newThisWeek: projects.newThisWeek,
    },
    members: availableFieldV2(members),
    memoryHistory: availableFieldV2(history),
  } satisfies TenantOverviewSnapshot);
}

function projectLocalSnapshotV2(
  payload: unknown,
  scope: TenantOverviewScope,
): TenantOverviewSnapshot {
  const reason = 'local_tenant_overview_contract_invalid';
  if (
    !isRecordV2(payload) ||
    payload.capability !== 'tenant_overview' ||
    !isAvailabilityV2(payload.availability) ||
    !isNullableReasonV2(payload.reason_code) ||
    !isNonEmptyStringV2(payload.service_version) ||
    !isNonEmptyStringV2(payload.contract_version) ||
    !isStringArrayV2(payload.allowed_actions) ||
    !isRecordV2(payload.scope) ||
    payload.scope.tenant_id !== scope.tenantId ||
    payload.scope.project_id !== null ||
    payload.scope.workspace_id !== null ||
    payload.scope.instance_id !== null ||
    !isNonnegativeIntegerV2(payload.authority_revision) ||
    !isRecordV2(payload.tenant_info)
  ) {
    throw tenantOverviewContractErrorV2(reason);
  }
  const tenantInfo = payload.tenant_info;
  if (
    !isNonEmptyStringV2(tenantInfo.organization_id) ||
    !isNonEmptyStringV2(tenantInfo.plan)
  ) {
    throw tenantOverviewContractErrorV2(reason);
  }
  const storage = requireRawFieldV2(payload.storage, reason, (value) =>
    value === null ? null : requireStorageV2(value, reason),
  );
  const projects = requireLocalProjectsV2(payload.projects, reason);
  const members = requireRawMembersV2(payload.members, reason);
  const memoryHistory = requireRawFieldV2(payload.memory_history, reason, (value) =>
    requireRawHistoryV2(value, reason),
  );
  return freezeDeepV2({
    scope: { ...scope },
    authority: 'local',
    availability: payload.availability,
    reasonCode: payload.reason_code,
    serviceVersion: payload.service_version,
    contractVersion: payload.contract_version,
    allowedActions: [...payload.allowed_actions],
    authorityRevision: payload.authority_revision,
    tenantInfo: {
      organizationId: tenantInfo.organization_id,
      plan: tenantInfo.plan,
      region: requireRawFieldV2(tenantInfo.region, reason, requireNullableStringV2),
      nextBillingDate: requireRawFieldV2(
        tenantInfo.next_billing_date,
        reason,
        requireNullableStringV2,
      ),
    },
    storage,
    projects,
    members: availableFieldV2(members),
    memoryHistory,
  } satisfies TenantOverviewSnapshot);
}

function requireCloudProjectsV2(payload: unknown): Readonly<{
  active: number;
  newThisWeek: number;
  list: readonly TenantOverviewProject[];
}> {
  const reason = 'cloud_tenant_overview_contract_invalid';
  if (
    !isRecordV2(payload) ||
    !isNonnegativeIntegerV2(payload.active) ||
    !isNonnegativeIntegerV2(payload.new_this_week) ||
    !Array.isArray(payload.list)
  ) {
    throw tenantOverviewContractErrorV2(reason);
  }
  return {
    active: payload.active,
    newThisWeek: payload.new_this_week,
    list: payload.list.map((project) => requireCloudProjectV2(project, reason)),
  };
}

function requireCloudProjectV2(payload: unknown, reason: string): TenantOverviewProject {
  if (
    !isRecordV2(payload) ||
    !isNonEmptyStringV2(payload.id) ||
    !isNonEmptyStringV2(payload.name) ||
    !isNonEmptyStringV2(payload.owner) ||
    !isNonEmptyStringV2(payload.memory_consumed) ||
    !isNonEmptyStringV2(payload.status)
  ) {
    throw tenantOverviewContractErrorV2(reason);
  }
  return {
    id: payload.id,
    name: payload.name,
    owner: availableFieldV2(payload.owner),
    memoryConsumed: availableFieldV2(payload.memory_consumed),
    status: payload.status,
  };
}

function requireLocalProjectsV2(payload: unknown, reason: string) {
  if (
    !isRecordV2(payload) ||
    !isAvailabilityV2(payload.availability) ||
    !isNullableReasonV2(payload.reason_code) ||
    !isNonnegativeIntegerV2(payload.active) ||
    !isNonnegativeIntegerV2(payload.new_this_week) ||
    !Array.isArray(payload.list)
  ) {
    throw tenantOverviewContractErrorV2(reason);
  }
  return {
    availability: payload.availability,
    reasonCode: payload.reason_code,
    active: payload.active,
    newThisWeek: payload.new_this_week,
    value: payload.list.map((project) => {
      if (
        !isRecordV2(project) ||
        !isNonEmptyStringV2(project.id) ||
        !isNonEmptyStringV2(project.name) ||
        !isNonEmptyStringV2(project.status)
      ) {
        throw tenantOverviewContractErrorV2(reason);
      }
      return {
        id: project.id,
        name: project.name,
        owner: requireRawFieldV2(project.owner, reason, requireNullableStringV2),
        memoryConsumed: requireRawFieldV2(
          project.memory_consumed,
          reason,
          requireNullableStringV2,
        ),
        status: project.status,
      };
    }),
  };
}

function requireProjectedProjectsV2(payload: unknown, reason: string) {
  if (
    !isRecordV2(payload) ||
    !isAvailabilityV2(payload.availability) ||
    !isNullableReasonV2(payload.reasonCode) ||
    !isNonnegativeIntegerV2(payload.active) ||
    !isNonnegativeIntegerV2(payload.newThisWeek) ||
    !Array.isArray(payload.value)
  ) {
    throw tenantOverviewContractErrorV2(reason);
  }
  return {
    availability: payload.availability,
    reasonCode: payload.reasonCode,
    active: payload.active,
    newThisWeek: payload.newThisWeek,
    value: payload.value.map((project) => {
      if (
        !isRecordV2(project) ||
        !isNonEmptyStringV2(project.id) ||
        !isNonEmptyStringV2(project.name) ||
        !isNonEmptyStringV2(project.status)
      ) {
        throw tenantOverviewContractErrorV2(reason);
      }
      return {
        id: project.id,
        name: project.name,
        owner: requireProjectedFieldV2(project.owner, reason, requireNullableStringV2),
        memoryConsumed: requireProjectedFieldV2(
          project.memoryConsumed,
          reason,
          requireNullableStringV2,
        ),
        status: project.status,
      };
    }),
  };
}

function requireRawFieldV2<T>(
  payload: unknown,
  reason: string,
  readValue: (value: unknown) => T,
): TenantOverviewField<T> {
  if (
    !isRecordV2(payload) ||
    !isAvailabilityV2(payload.availability) ||
    !isNullableReasonV2(payload.reason_code) ||
    !Object.hasOwn(payload, 'value')
  ) {
    throw tenantOverviewContractErrorV2(reason);
  }
  return {
    availability: payload.availability,
    reasonCode: payload.reason_code,
    value: readValue(payload.value),
  };
}

function requireProjectedFieldV2<T>(
  payload: unknown,
  reason: string,
  readValue: (value: unknown) => T,
): TenantOverviewField<T> {
  if (
    !isRecordV2(payload) ||
    !isAvailabilityV2(payload.availability) ||
    !isNullableReasonV2(payload.reasonCode) ||
    !Object.hasOwn(payload, 'value')
  ) {
    throw tenantOverviewContractErrorV2(reason);
  }
  return {
    availability: payload.availability,
    reasonCode: payload.reasonCode,
    value: readValue(payload.value),
  };
}

function requireStorageV2(payload: unknown, reason: string): TenantOverviewStorage {
  if (
    !isRecordV2(payload) ||
    !isFiniteNonnegativeV2(payload.used) ||
    !isFiniteNonnegativeV2(payload.total) ||
    !isFiniteNonnegativeV2(payload.percentage) ||
    payload.percentage > 100
  ) {
    throw tenantOverviewContractErrorV2(reason);
  }
  return { used: payload.used, total: payload.total, percentage: payload.percentage };
}

function requireRawMembersV2(payload: unknown, reason: string) {
  if (
    !isRecordV2(payload) ||
    !isNonnegativeIntegerV2(payload.total) ||
    !isNonnegativeIntegerV2(payload.new_added)
  ) {
    throw tenantOverviewContractErrorV2(reason);
  }
  return { total: payload.total, newAdded: payload.new_added };
}

function requireProjectedMembersV2(payload: unknown, reason: string) {
  if (
    !isRecordV2(payload) ||
    !isNonnegativeIntegerV2(payload.total) ||
    !isNonnegativeIntegerV2(payload.newAdded)
  ) {
    throw tenantOverviewContractErrorV2(reason);
  }
  return { total: payload.total, newAdded: payload.newAdded };
}

function requireRawHistoryV2(
  payload: unknown,
  reason: string,
): readonly TenantOverviewMemoryPoint[] {
  if (!Array.isArray(payload)) throw tenantOverviewContractErrorV2(reason);
  return payload.map((point) => {
    if (
      !isRecordV2(point) ||
      !isNonEmptyStringV2(point.date) ||
      !isFiniteNonnegativeV2(point.used) ||
      !isFiniteNonnegativeV2(point.daily_added) ||
      !isNonnegativeIntegerV2(point.memory_count) ||
      !isFiniteNonnegativeV2(point.percentage) ||
      point.percentage > 100
    ) {
      throw tenantOverviewContractErrorV2(reason);
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

function requireProjectedHistoryV2(
  payload: unknown,
  reason: string,
): readonly TenantOverviewMemoryPoint[] {
  if (!Array.isArray(payload)) throw tenantOverviewContractErrorV2(reason);
  return payload.map((point) => {
    if (
      !isRecordV2(point) ||
      !isNonEmptyStringV2(point.date) ||
      !isFiniteNonnegativeV2(point.used) ||
      !isFiniteNonnegativeV2(point.dailyAdded) ||
      !isNonnegativeIntegerV2(point.memoryCount) ||
      !isFiniteNonnegativeV2(point.percentage) ||
      point.percentage > 100
    ) {
      throw tenantOverviewContractErrorV2(reason);
    }
    return {
      date: point.date,
      used: point.used,
      dailyAdded: point.dailyAdded,
      memoryCount: point.memoryCount,
      percentage: point.percentage,
    };
  });
}

function requireCloudTenantInfoV2(payload: unknown) {
  const reason = 'cloud_tenant_overview_contract_invalid';
  if (
    !isRecordV2(payload) ||
    !isNonEmptyStringV2(payload.organization_id) ||
    !isNonEmptyStringV2(payload.plan) ||
    !isNullableStringV2(payload.region) ||
    !isNullableStringV2(payload.next_billing_date)
  ) {
    throw tenantOverviewContractErrorV2(reason);
  }
  return {
    organizationId: payload.organization_id,
    plan: payload.plan,
    region: availableFieldV2(payload.region),
    nextBillingDate: availableFieldV2(payload.next_billing_date),
  };
}

function availableFieldV2<T>(value: T): TenantOverviewField<T> {
  return { availability: 'available', reasonCode: null, value };
}

function requireNullableStringV2(value: unknown): string | null {
  if (!isNullableStringV2(value)) {
    throw tenantOverviewContractErrorV2('local_tenant_overview_contract_invalid');
  }
  return value;
}

export function tenantOverviewContractErrorV2(reasonCode: string): DesktopApiError {
  return new DesktopApiError(reasonCode, 0, { reason_code: reasonCode });
}

function freezeDeepV2<T>(value: T): T {
  if (value === null || typeof value !== 'object') return value;
  for (const nested of Object.values(value)) freezeDeepV2(nested);
  return Object.isFrozen(value) ? value : Object.freeze(value);
}

function isRecordV2(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isNonEmptyStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function isNullableStringV2(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isNullableReasonV2(value: unknown): value is string | null {
  return value === null || isNonEmptyStringV2(value);
}

function isStringArrayV2(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isNonEmptyStringV2);
}

function isFiniteNonnegativeV2(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}

function isNonnegativeIntegerV2(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function isNullableRevisionV2(value: unknown): value is number | null {
  return value === null || isNonnegativeIntegerV2(value);
}

function isAvailabilityV2(value: unknown): value is TenantOverviewAvailability {
  return (
    value === 'available' ||
    value === 'degraded' ||
    value === 'unavailable' ||
    value === 'not_applicable'
  );
}
