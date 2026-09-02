import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  RuntimePoolHealthStatus,
  RuntimePoolInstance,
  RuntimePoolInstancePage,
  RuntimePoolInstanceStatus,
  RuntimePoolMetrics,
  RuntimePoolScope,
  RuntimePoolStatus,
  RuntimePoolTier,
} from '../features/runtime-pool/runtimePoolClient';
import type { DesktopCapabilityAvailability } from '../features/runtime/capabilitySnapshot';

export const DESKTOP_RUNTIME_POOL_CLOUD_ACTIONS_V2 = Object.freeze([
  'view',
  'refresh',
  'toggle-auto-refresh',
  'list-instances',
  'search-current-page',
  'filter-by-tier',
  'paginate-instances',
  'pause-instance',
  'resume-instance',
  'terminate-instance',
  'retry-list-instances',
  'inspect-pool-status',
] as const);

const STATUS_KEYS_V2 = new Set([
  'enabled',
  'status',
  'totalInstances',
  'hotInstances',
  'warmInstances',
  'coldInstances',
  'readyInstances',
  'executingInstances',
  'unhealthyInstances',
  'prewarmPool',
  'resourceUsage',
  'reasonCode',
]);
const PREWARM_KEYS_V2 = new Set(['l1', 'l2', 'l3']);
const RESOURCE_KEYS_V2 = new Set([
  'totalMemoryMb',
  'usedMemoryMb',
  'totalCpuCores',
  'usedCpuCores',
]);
const PAGE_KEYS_V2 = new Set(['instances', 'total', 'page', 'pageSize']);
const INSTANCE_KEYS_V2 = new Set([
  'instanceKey',
  'tenantId',
  'projectId',
  'agentMode',
  'tier',
  'status',
  'createdAt',
  'lastRequestAt',
  'activeRequests',
  'totalRequests',
  'memoryUsedMb',
  'healthStatus',
]);
const METRICS_KEYS_V2 = new Set(['instances', 'unhealthyCount', 'prewarm', 'reasonCode']);
const METRIC_INSTANCES_KEYS_V2 = new Set(['total', 'byTier', 'byStatus']);
const TIER_COUNTS_KEYS_V2 = new Set(['hot', 'warm', 'cold']);
const STATUS_COUNTS_KEYS_V2 = new Set(['ready', 'executing', 'unhealthy']);
const CAPABILITY_KEYS_V2 = new Set([
  'availability',
  'reason_code',
  'service_version',
  'contract_version',
  'allowed_actions',
  'scope',
  'authority_revision',
]);
const CAPABILITY_SCOPE_KEYS_V2 = new Set([
  'tenant_id',
  'project_id',
  'workspace_id',
  'instance_id',
]);
const TIERS_V2 = new Set<RuntimePoolTier>(['hot', 'warm', 'cold']);
const STATUSES_V2 = new Set<RuntimePoolInstanceStatus>([
  'created',
  'initializing',
  'initialization_failed',
  'ready',
  'executing',
  'paused',
  'unhealthy',
  'degraded',
  'terminating',
  'terminated',
]);
const HEALTH_STATUSES_V2 = new Set<RuntimePoolHealthStatus>([
  'healthy',
  'degraded',
  'unhealthy',
  'unknown',
]);

export function requireDesktopRuntimePoolStatusV2(value: unknown): RuntimePoolStatus {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, STATUS_KEYS_V2) ||
    typeof value.enabled !== 'boolean' ||
    !isCanonicalStringV2(value.status) ||
    !isNonnegativeIntegerV2(value.totalInstances) ||
    !isNonnegativeIntegerV2(value.hotInstances) ||
    !isNonnegativeIntegerV2(value.warmInstances) ||
    !isNonnegativeIntegerV2(value.coldInstances) ||
    !isNonnegativeIntegerV2(value.readyInstances) ||
    !isNonnegativeIntegerV2(value.executingInstances) ||
    !isNonnegativeIntegerV2(value.unhealthyInstances) ||
    !isNullableReasonCodeV2(value.reasonCode)
  ) {
    throw contractErrorV2();
  }
  return Object.freeze({
    enabled: value.enabled,
    status: value.status,
    totalInstances: value.totalInstances,
    hotInstances: value.hotInstances,
    warmInstances: value.warmInstances,
    coldInstances: value.coldInstances,
    readyInstances: value.readyInstances,
    executingInstances: value.executingInstances,
    unhealthyInstances: value.unhealthyInstances,
    prewarmPool: requirePrewarmV2(value.prewarmPool),
    resourceUsage: requireResourceUsageV2(value.resourceUsage),
    reasonCode: value.reasonCode,
  });
}

export function requireDesktopRuntimePoolInstancePageV2(
  value: unknown,
  expectedScope: RuntimePoolScope,
): RuntimePoolInstancePage {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, PAGE_KEYS_V2) ||
    !Array.isArray(value.instances) ||
    !isNonnegativeIntegerV2(value.total) ||
    !isPositiveIntegerV2(value.page) ||
    !isPositiveIntegerV2(value.pageSize) ||
    value.instances.length > value.pageSize ||
    value.instances.length > value.total
  ) {
    throw contractErrorV2();
  }
  return Object.freeze({
    instances: Object.freeze(
      value.instances.map((instance) => requireRuntimePoolInstanceV2(instance, expectedScope)),
    ),
    total: value.total,
    page: value.page,
    pageSize: value.pageSize,
  });
}

export function requireDesktopRuntimePoolMetricsV2(value: unknown): RuntimePoolMetrics {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, METRICS_KEYS_V2) ||
    !isPlainRecordV2(value.instances) ||
    !hasExactKeysV2(value.instances, METRIC_INSTANCES_KEYS_V2) ||
    !isNonnegativeIntegerV2(value.instances.total) ||
    !isTierCountsV2(value.instances.byTier) ||
    !isStatusCountsV2(value.instances.byStatus) ||
    !isNonnegativeIntegerV2(value.unhealthyCount) ||
    !isNullableReasonCodeV2(value.reasonCode)
  ) {
    throw contractErrorV2();
  }
  return Object.freeze({
    instances: Object.freeze({
      total: value.instances.total,
      byTier: Object.freeze({
        hot: value.instances.byTier.hot,
        warm: value.instances.byTier.warm,
        cold: value.instances.byTier.cold,
      }),
      byStatus: Object.freeze({
        ready: value.instances.byStatus.ready,
        executing: value.instances.byStatus.executing,
        unhealthy: value.instances.byStatus.unhealthy,
      }),
    }),
    unhealthyCount: value.unhealthyCount,
    prewarm: requireNumberRecordV2(value.prewarm),
    reasonCode: value.reasonCode,
  });
}

export function requireDesktopRuntimePoolCapabilityV2(
  value: unknown,
  expectedScope: RuntimePoolScope,
): DesktopCapabilityAvailability {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, CAPABILITY_KEYS_V2) ||
    !isCapabilityScopeV2(value.scope, expectedScope) ||
    value.authority_revision !== null
  ) {
    throw contractErrorV2();
  }
  if (expectedScope.authority === 'local') {
    if (
      value.availability !== 'not_applicable' ||
      value.reason_code !== 'cloud_runtime_pool_not_applicable' ||
      value.service_version !== null ||
      value.contract_version !== null ||
      !Array.isArray(value.allowed_actions) ||
      value.allowed_actions.length !== 0
    ) {
      throw contractErrorV2();
    }
  } else if (
    value.availability !== 'degraded' ||
    value.reason_code !== 'global_pool_capacity_not_available_in_tenant_scope' ||
    value.service_version !== '0.1.0' ||
    value.contract_version !== '3.0.0' ||
    !sameOrderedStringsV2(value.allowed_actions, DESKTOP_RUNTIME_POOL_CLOUD_ACTIONS_V2)
  ) {
    throw contractErrorV2();
  }
  return Object.freeze({
    availability: value.availability,
    reason_code: value.reason_code,
    service_version: value.service_version,
    contract_version: value.contract_version,
    allowed_actions: Object.freeze([...value.allowed_actions]),
    scope: Object.freeze({
      tenant_id: expectedScope.tenantId,
      project_id: null,
      workspace_id: null,
      instance_id: null,
    }),
    authority_revision: null,
  }) as DesktopCapabilityAvailability;
}

export function requireDesktopRuntimePoolVoidResultV2(value: unknown): void {
  if (value !== undefined) throw contractErrorV2();
}

function requireRuntimePoolInstanceV2(
  value: unknown,
  expectedScope: RuntimePoolScope,
): RuntimePoolInstance {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, INSTANCE_KEYS_V2) ||
    !isCanonicalStringV2(value.instanceKey) ||
    value.tenantId !== expectedScope.tenantId ||
    !isCanonicalStringV2(value.projectId) ||
    !isCanonicalStringV2(value.agentMode) ||
    !isTierV2(value.tier) ||
    !isStatusV2(value.status) ||
    !isNullableStringV2(value.createdAt) ||
    !isNullableStringV2(value.lastRequestAt) ||
    !isNonnegativeIntegerV2(value.activeRequests) ||
    !isNonnegativeIntegerV2(value.totalRequests) ||
    !isFiniteNonnegativeV2(value.memoryUsedMb) ||
    !isHealthStatusV2(value.healthStatus)
  ) {
    throw contractErrorV2();
  }
  return Object.freeze({ ...value }) as RuntimePoolInstance;
}

function requirePrewarmV2(value: unknown): RuntimePoolStatus['prewarmPool'] {
  if (value === null) return null;
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, PREWARM_KEYS_V2) ||
    !isNonnegativeIntegerV2(value.l1) ||
    !isNonnegativeIntegerV2(value.l2) ||
    !isNonnegativeIntegerV2(value.l3)
  ) {
    throw contractErrorV2();
  }
  return Object.freeze({ l1: value.l1, l2: value.l2, l3: value.l3 });
}

function requireResourceUsageV2(value: unknown): RuntimePoolStatus['resourceUsage'] {
  if (value === null) return null;
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, RESOURCE_KEYS_V2) ||
    [...RESOURCE_KEYS_V2].some((key) => !isFiniteNonnegativeV2(value[key]))
  ) {
    throw contractErrorV2();
  }
  return Object.freeze({
    totalMemoryMb: Number(value.totalMemoryMb),
    usedMemoryMb: Number(value.usedMemoryMb),
    totalCpuCores: Number(value.totalCpuCores),
    usedCpuCores: Number(value.usedCpuCores),
  });
}

function requireNumberRecordV2(value: unknown): Readonly<Record<string, number>> | null {
  if (value === null) return null;
  if (
    !isPlainRecordV2(value) ||
    Object.values(value).some((item) => !isFiniteNonnegativeV2(item))
  ) {
    throw contractErrorV2();
  }
  return Object.freeze({ ...value }) as Readonly<Record<string, number>>;
}

function isTierCountsV2(value: unknown): value is Record<RuntimePoolTier, number> {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, TIER_COUNTS_KEYS_V2) &&
    [...TIER_COUNTS_KEYS_V2].every((key) => isNonnegativeIntegerV2(value[key]))
  );
}

function isStatusCountsV2(
  value: unknown,
): value is Record<'ready' | 'executing' | 'unhealthy', number> {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, STATUS_COUNTS_KEYS_V2) &&
    [...STATUS_COUNTS_KEYS_V2].every((key) => isNonnegativeIntegerV2(value[key]))
  );
}

function isCapabilityScopeV2(value: unknown, expectedScope: RuntimePoolScope): boolean {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, CAPABILITY_SCOPE_KEYS_V2) &&
    value.tenant_id === expectedScope.tenantId &&
    value.project_id === null &&
    value.workspace_id === null &&
    value.instance_id === null
  );
}

function sameOrderedStringsV2(value: unknown, expected: readonly string[]): value is string[] {
  return (
    Array.isArray(value) &&
    value.length === expected.length &&
    value.every((entry, index) => entry === expected[index])
  );
}

function contractErrorV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_runtime_pool_service_contract_invalid',
    'desktop runtime pool authority service contract is invalid',
  );
}

function isTierV2(value: unknown): value is RuntimePoolTier {
  return typeof value === 'string' && TIERS_V2.has(value as RuntimePoolTier);
}

function isStatusV2(value: unknown): value is RuntimePoolInstanceStatus {
  return typeof value === 'string' && STATUSES_V2.has(value as RuntimePoolInstanceStatus);
}

function isHealthStatusV2(value: unknown): value is RuntimePoolHealthStatus {
  return typeof value === 'string' && HEALTH_STATUSES_V2.has(value as RuntimePoolHealthStatus);
}

function hasExactKeysV2(value: Record<string, unknown>, expected: ReadonlySet<string>): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function isCanonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isNullableStringV2(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isNullableReasonCodeV2(value: unknown): value is string | null {
  return value === null || isCanonicalStringV2(value);
}

function isNonnegativeIntegerV2(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function isPositiveIntegerV2(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) > 0;
}

function isFiniteNonnegativeV2(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}
