import { DesktopApiError } from '../api/client';
import type {
  TenantAnalyticsAvailability,
  TenantAnalyticsField,
  TenantAnalyticsMemoryPoint,
  TenantAnalyticsPeriod,
  TenantAnalyticsProjectStorage,
  TenantAnalyticsScope,
  TenantAnalyticsSnapshot,
} from '../features/tenant/tenantAnalyticsClient';

const PERIOD_DAYS_V2: Readonly<Record<TenantAnalyticsPeriod, number>> = Object.freeze({
  '7d': 7,
  '30d': 30,
  '90d': 90,
});

const PROJECTED_SNAPSHOT_KEYS_V2 = new Set([
  'scope',
  'authority',
  'availability',
  'reasonCode',
  'serviceVersion',
  'contractVersion',
  'allowedActions',
  'authorityRevision',
  'memoryGrowth',
  'projectStorage',
  'summary',
]);

export function projectDesktopTenantAnalyticsResponseV2(
  payload: unknown,
  scope: TenantAnalyticsScope,
): TenantAnalyticsSnapshot {
  return scope.authority === 'cloud'
    ? projectCloudSnapshotV2(payload, scope)
    : projectLocalSnapshotV2(payload, scope);
}

export function requireDesktopTenantAnalyticsSnapshotV2(
  payload: unknown,
  expectedScope: TenantAnalyticsScope,
): TenantAnalyticsSnapshot {
  const reason = 'desktop_tenant_analytics_service_contract_invalid';
  if (
    !isRecordV2(payload) ||
    !hasExactKeysV2(payload, PROJECTED_SNAPSHOT_KEYS_V2) ||
    !isProjectedScopeV2(payload.scope, expectedScope) ||
    payload.authority !== expectedScope.authority ||
    !isAvailabilityV2(payload.availability) ||
    !isNullableReasonV2(payload.reasonCode) ||
    !isNonEmptyStringV2(payload.serviceVersion) ||
    !isNonEmptyStringV2(payload.contractVersion) ||
    !isStringArrayV2(payload.allowedActions) ||
    !isNullableRevisionV2(payload.authorityRevision) ||
    !isRecordV2(payload.summary)
  ) {
    throw tenantAnalyticsContractErrorV2(reason);
  }
  const summary = payload.summary;
  if (
    !hasExactKeysV2(
      summary,
      new Set(['totalMemories', 'totalStorageBytes', 'totalProjects', 'periodDays']),
    ) ||
    summary.periodDays !== PERIOD_DAYS_V2[expectedScope.period]
  ) {
    throw tenantAnalyticsContractErrorV2(reason);
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
    memoryGrowth: requireProjectedFieldV2(payload.memoryGrowth, reason, (value) =>
      requireProjectedMemoryPointsV2(value, reason),
    ),
    projectStorage: requireProjectedFieldV2(payload.projectStorage, reason, (value) =>
      requireProjectedProjectStorageListV2(value, reason),
    ),
    summary: {
      totalMemories: requireProjectedFieldV2(
        summary.totalMemories,
        reason,
        (value) => requireNullableNonnegativeIntegerV2(value, reason),
      ),
      totalStorageBytes: requireProjectedFieldV2(
        summary.totalStorageBytes,
        reason,
        (value) => requireNullableFiniteNonnegativeV2(value, reason),
      ),
      totalProjects: requireProjectedFieldV2(
        summary.totalProjects,
        reason,
        (value) => requireNullableNonnegativeIntegerV2(value, reason),
      ),
      periodDays: summary.periodDays,
    },
  } satisfies TenantAnalyticsSnapshot);
}

export function tenantAnalyticsContractErrorV2(reasonCode: string): DesktopApiError {
  return new DesktopApiError(reasonCode, 0, { reason_code: reasonCode });
}

function projectCloudSnapshotV2(
  payload: unknown,
  scope: TenantAnalyticsScope,
): TenantAnalyticsSnapshot {
  const reason = 'cloud_tenant_analytics_contract_invalid';
  if (
    !isRecordV2(payload) ||
    !Array.isArray(payload.memoryGrowth) ||
    !Array.isArray(payload.projectStorage) ||
    !isRecordV2(payload.summary)
  ) {
    throw tenantAnalyticsContractErrorV2(reason);
  }
  const summary = payload.summary;
  if (
    !isNonnegativeIntegerV2(summary.total_memories) ||
    !isFiniteNonnegativeV2(summary.total_storage_bytes) ||
    !isNonnegativeIntegerV2(summary.total_projects) ||
    summary.period_days !== PERIOD_DAYS_V2[scope.period]
  ) {
    throw tenantAnalyticsContractErrorV2(reason);
  }
  return freezeDeepV2({
    scope: { ...scope },
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    serviceVersion: 'cloud',
    contractVersion: '3.0.0',
    allowedActions: ['view', 'retry'],
    authorityRevision: null,
    memoryGrowth: availableFieldV2(
      payload.memoryGrowth.map((point) => requireMemoryPointV2(point, reason)),
    ),
    projectStorage: availableFieldV2(
      payload.projectStorage.map((project) => requireCloudProjectStorageV2(project, reason)),
    ),
    summary: {
      totalMemories: availableFieldV2(summary.total_memories),
      totalStorageBytes: availableFieldV2(summary.total_storage_bytes),
      totalProjects: availableFieldV2(summary.total_projects),
      periodDays: summary.period_days,
    },
  } satisfies TenantAnalyticsSnapshot);
}

function projectLocalSnapshotV2(
  payload: unknown,
  scope: TenantAnalyticsScope,
): TenantAnalyticsSnapshot {
  const reason = 'local_tenant_analytics_contract_invalid';
  if (
    !isRecordV2(payload) ||
    payload.capability !== 'tenant_analytics' ||
    !isAvailabilityV2(payload.availability) ||
    !isNullableReasonV2(payload.reason_code) ||
    !isNonEmptyStringV2(payload.service_version) ||
    !isNonEmptyStringV2(payload.contract_version) ||
    !isStringArrayV2(payload.allowed_actions) ||
    !isRecordV2(payload.scope) ||
    payload.scope.tenant_id !== scope.tenantId ||
    !isNullableIdentifierV2(payload.scope.project_id) ||
    !isNullableIdentifierV2(payload.scope.workspace_id) ||
    !isNullableIdentifierV2(payload.scope.instance_id) ||
    !isNonnegativeIntegerV2(payload.authority_revision) ||
    !isRecordV2(payload.summary)
  ) {
    throw tenantAnalyticsContractErrorV2(reason);
  }
  const summary = payload.summary;
  if (summary.period_days !== PERIOD_DAYS_V2[scope.period]) {
    throw tenantAnalyticsContractErrorV2(reason);
  }
  return freezeDeepV2({
    scope: { ...scope },
    authority: 'local',
    availability: payload.availability,
    reasonCode: payload.reason_code,
    serviceVersion: payload.service_version,
    contractVersion: payload.contract_version,
    allowedActions: [...payload.allowed_actions],
    authorityRevision: payload.authority_revision,
    memoryGrowth: requireRawFieldV2(payload.memoryGrowth, reason, (value) =>
      requireRawMemoryPointsV2(value, reason),
    ),
    projectStorage: requireRawFieldV2(payload.projectStorage, reason, (value) =>
      requireRawProjectStorageListV2(value, reason),
    ),
    summary: {
      totalMemories: requireRawFieldV2(
        summary.total_memories,
        reason,
        (value) => requireNullableNonnegativeIntegerV2(value, reason),
      ),
      totalStorageBytes: requireRawFieldV2(
        summary.total_storage_bytes,
        reason,
        (value) => requireNullableFiniteNonnegativeV2(value, reason),
      ),
      totalProjects: requireRawFieldV2(
        summary.total_projects,
        reason,
        (value) => requireNullableNonnegativeIntegerV2(value, reason),
      ),
      periodDays: summary.period_days,
    },
  } satisfies TenantAnalyticsSnapshot);
}

function requireRawMemoryPointsV2(
  payload: unknown,
  reason: string,
): readonly TenantAnalyticsMemoryPoint[] {
  if (!Array.isArray(payload)) throw tenantAnalyticsContractErrorV2(reason);
  return payload.map((point) => requireMemoryPointV2(point, reason));
}

function requireProjectedMemoryPointsV2(
  payload: unknown,
  reason: string,
): readonly TenantAnalyticsMemoryPoint[] {
  if (!Array.isArray(payload)) throw tenantAnalyticsContractErrorV2(reason);
  return payload.map((point) => requireMemoryPointV2(point, reason));
}

function requireMemoryPointV2(
  payload: unknown,
  reason: string,
): TenantAnalyticsMemoryPoint {
  if (
    !isRecordV2(payload) ||
    !hasExactKeysV2(payload, new Set(['date', 'count'])) ||
    !isNonEmptyStringV2(payload.date) ||
    !isNonnegativeIntegerV2(payload.count)
  ) {
    throw tenantAnalyticsContractErrorV2(reason);
  }
  return { date: payload.date, count: payload.count };
}

function requireCloudProjectStorageV2(
  payload: unknown,
  reason: string,
): TenantAnalyticsProjectStorage {
  if (
    !isRecordV2(payload) ||
    !isNonEmptyStringV2(payload.name) ||
    !isFiniteNonnegativeV2(payload.storage_bytes) ||
    !isNonnegativeIntegerV2(payload.memory_count)
  ) {
    throw tenantAnalyticsContractErrorV2(reason);
  }
  return {
    name: payload.name,
    storageBytes: availableFieldV2(payload.storage_bytes),
    memoryCount: availableFieldV2(payload.memory_count),
  };
}

function requireRawProjectStorageListV2(
  payload: unknown,
  reason: string,
): readonly TenantAnalyticsProjectStorage[] {
  if (!Array.isArray(payload)) throw tenantAnalyticsContractErrorV2(reason);
  return payload.map((project) => {
    if (!isRecordV2(project) || !isNonEmptyStringV2(project.name)) {
      throw tenantAnalyticsContractErrorV2(reason);
    }
    return {
      name: project.name,
      storageBytes: requireRawFieldV2(
        project.storage_bytes,
        reason,
        (value) => requireNullableFiniteNonnegativeV2(value, reason),
      ),
      memoryCount: requireRawFieldV2(
        project.memory_count,
        reason,
        (value) => requireNullableNonnegativeIntegerV2(value, reason),
      ),
    };
  });
}

function requireProjectedProjectStorageListV2(
  payload: unknown,
  reason: string,
): readonly TenantAnalyticsProjectStorage[] {
  if (!Array.isArray(payload)) throw tenantAnalyticsContractErrorV2(reason);
  return payload.map((project) => {
    if (
      !isRecordV2(project) ||
      !hasExactKeysV2(project, new Set(['name', 'storageBytes', 'memoryCount'])) ||
      !isNonEmptyStringV2(project.name)
    ) {
      throw tenantAnalyticsContractErrorV2(reason);
    }
    return {
      name: project.name,
      storageBytes: requireProjectedFieldV2(
        project.storageBytes,
        reason,
        (value) => requireNullableFiniteNonnegativeV2(value, reason),
      ),
      memoryCount: requireProjectedFieldV2(
        project.memoryCount,
        reason,
        (value) => requireNullableNonnegativeIntegerV2(value, reason),
      ),
    };
  });
}

function requireRawFieldV2<T>(
  payload: unknown,
  reason: string,
  readValue: (value: unknown) => T,
): TenantAnalyticsField<T> {
  if (
    !isRecordV2(payload) ||
    !isAvailabilityV2(payload.availability) ||
    !isNullableReasonV2(payload.reason_code) ||
    !Object.hasOwn(payload, 'value')
  ) {
    throw tenantAnalyticsContractErrorV2(reason);
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
): TenantAnalyticsField<T> {
  if (
    !isRecordV2(payload) ||
    !hasExactKeysV2(payload, new Set(['availability', 'reasonCode', 'value'])) ||
    !isAvailabilityV2(payload.availability) ||
    !isNullableReasonV2(payload.reasonCode) ||
    !Object.hasOwn(payload, 'value')
  ) {
    throw tenantAnalyticsContractErrorV2(reason);
  }
  return {
    availability: payload.availability,
    reasonCode: payload.reasonCode,
    value: readValue(payload.value),
  };
}

function availableFieldV2<T>(value: T): TenantAnalyticsField<T> {
  return { availability: 'available', reasonCode: null, value };
}

function isProjectedScopeV2(
  payload: unknown,
  expectedScope: TenantAnalyticsScope,
): boolean {
  return (
    isRecordV2(payload) &&
    hasExactKeysV2(payload, new Set(['authority', 'tenantId', 'period'])) &&
    payload.authority === expectedScope.authority &&
    payload.tenantId === expectedScope.tenantId &&
    payload.period === expectedScope.period
  );
}

function requireNullableNonnegativeIntegerV2(
  value: unknown,
  reason: string,
): number | null {
  if (value === null || isNonnegativeIntegerV2(value)) return value;
  throw tenantAnalyticsContractErrorV2(reason);
}

function requireNullableFiniteNonnegativeV2(
  value: unknown,
  reason: string,
): number | null {
  if (value === null || isFiniteNonnegativeV2(value)) return value;
  throw tenantAnalyticsContractErrorV2(reason);
}

function freezeDeepV2<T>(value: T): T {
  if (value === null || typeof value !== 'object') return value;
  for (const nested of Object.values(value)) freezeDeepV2(nested);
  return Object.isFrozen(value) ? value : Object.freeze(value);
}

function hasExactKeysV2(
  value: Record<string, unknown>,
  expected: ReadonlySet<string>,
): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function isAvailabilityV2(value: unknown): value is TenantAnalyticsAvailability {
  return (
    value === 'available' ||
    value === 'degraded' ||
    value === 'unavailable' ||
    value === 'not_applicable'
  );
}

function isNullableReasonV2(value: unknown): value is string | null {
  return value === null || isNonEmptyStringV2(value);
}

function isNullableIdentifierV2(value: unknown): value is string | null {
  return value === null || isNonEmptyStringV2(value);
}

function isNullableRevisionV2(value: unknown): value is number | null {
  return value === null || isNonnegativeIntegerV2(value);
}

function isStringArrayV2(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isNonEmptyStringV2);
}

function isNonnegativeIntegerV2(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function isFiniteNonnegativeV2(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}

function isNonEmptyStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isRecordV2(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
