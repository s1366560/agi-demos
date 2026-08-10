import {
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import { desktopApiFetch } from '../../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../../types';

export type RuntimePoolAuthority = 'cloud' | 'local';
export type RuntimePoolTier = 'hot' | 'warm' | 'cold';
export type RuntimePoolInstanceStatus =
  | 'created'
  | 'initializing'
  | 'initialization_failed'
  | 'ready'
  | 'executing'
  | 'paused'
  | 'unhealthy'
  | 'degraded'
  | 'terminating'
  | 'terminated';
export type RuntimePoolHealthStatus =
  | 'healthy'
  | 'degraded'
  | 'unhealthy'
  | 'unknown';

export type RuntimePoolScope = Readonly<{
  authority: RuntimePoolAuthority;
  tenantId: string;
}>;

export type RuntimePoolQuery = Readonly<{
  tier?: RuntimePoolTier | 'all';
  status?: RuntimePoolInstanceStatus | 'all';
  page?: number;
  pageSize?: number;
}>;

export type RuntimePoolStatus = Readonly<{
  enabled: boolean;
  status: string;
  totalInstances: number;
  hotInstances: number;
  warmInstances: number;
  coldInstances: number;
  readyInstances: number;
  executingInstances: number;
  unhealthyInstances: number;
  prewarmPool: Readonly<{ l1: number; l2: number; l3: number }> | null;
  resourceUsage: Readonly<{
    totalMemoryMb: number;
    usedMemoryMb: number;
    totalCpuCores: number;
    usedCpuCores: number;
  }> | null;
  reasonCode: string | null;
}>;

export type RuntimePoolInstance = Readonly<{
  instanceKey: string;
  tenantId: string;
  projectId: string;
  agentMode: string;
  tier: RuntimePoolTier;
  status: RuntimePoolInstanceStatus;
  createdAt: string | null;
  lastRequestAt: string | null;
  activeRequests: number;
  totalRequests: number;
  memoryUsedMb: number;
  healthStatus: RuntimePoolHealthStatus;
}>;

export type RuntimePoolInstancePage = Readonly<{
  instances: readonly RuntimePoolInstance[];
  total: number;
  page: number;
  pageSize: number;
}>;

export type RuntimePoolMetrics = Readonly<{
  instances: Readonly<{
    total: number;
    byTier: Readonly<Record<RuntimePoolTier, number>>;
    byStatus: Readonly<{
      ready: number;
      executing: number;
      unhealthy: number;
    }>;
  }>;
  unhealthyCount: number;
  prewarm: Readonly<Record<string, number>> | null;
  reasonCode: string | null;
}>;

export type RuntimePoolRequestOptions = Readonly<{ signal?: AbortSignal }>;

export type RuntimePoolClient = Readonly<{
  getStatus: (
    scope: RuntimePoolScope,
    options?: RuntimePoolRequestOptions,
  ) => Promise<RuntimePoolStatus>;
  listInstances: (
    scope: RuntimePoolScope,
    query?: RuntimePoolQuery,
    options?: RuntimePoolRequestOptions,
  ) => Promise<RuntimePoolInstancePage>;
  getMetrics: (
    scope: RuntimePoolScope,
    options?: RuntimePoolRequestOptions,
  ) => Promise<RuntimePoolMetrics>;
  pauseInstance: (
    scope: RuntimePoolScope,
    instanceKey: string,
    options?: RuntimePoolRequestOptions,
  ) => Promise<void>;
  resumeInstance: (
    scope: RuntimePoolScope,
    instanceKey: string,
    options?: RuntimePoolRequestOptions,
  ) => Promise<void>;
  terminateInstance: (
    scope: RuntimePoolScope,
    instanceKey: string,
    graceful: boolean,
    options?: RuntimePoolRequestOptions,
  ) => Promise<void>;
}>;

export class RuntimePoolUnavailableError extends Error {
  readonly reasonCode: string;

  constructor(reasonCode: string) {
    super(reasonCode);
    this.name = 'RuntimePoolUnavailableError';
    this.reasonCode = reasonCode;
  }
}

const BASE_PATH = '/api/v1/admin/pool';
const INSTANCE_STATUSES = new Set<RuntimePoolInstanceStatus>([
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
const HEALTH_STATUSES = new Set<RuntimePoolHealthStatus>([
  'healthy',
  'degraded',
  'unhealthy',
  'unknown',
]);
const TIERS = new Set<RuntimePoolTier>(['hot', 'warm', 'cold']);

export function createRuntimePoolHttpClient(
  config: DesktopRuntimeConfig,
): RuntimePoolClient {
  const runtimeConfig = Object.freeze({ ...config });
  return Object.freeze({
    async getStatus(scope, options) {
      requireCloudScope(runtimeConfig, scope);
      const payload = await requestJson(
        runtimeConfig,
        scopedPath(`${BASE_PATH}/status`, scope),
        'GET',
        options?.signal,
      );
      requireResponseScope(payload, scope);
      return parseStatus(payload);
    },
    async listInstances(scope, query = {}, options) {
      requireCloudScope(runtimeConfig, scope);
      const normalized = normalizeQuery(query);
      const params = scopeParams(scope);
      if (normalized.tier !== 'all') params.set('tier', normalized.tier);
      if (normalized.status !== 'all') params.set('status', normalized.status);
      params.set('page', String(normalized.page));
      params.set('page_size', String(normalized.pageSize));
      const payload = await requestJson(
        runtimeConfig,
        `${BASE_PATH}/instances?${params.toString()}`,
        'GET',
        options?.signal,
      );
      requireResponseScope(payload, scope);
      return parseInstancePage(payload);
    },
    async getMetrics(scope, options) {
      requireCloudScope(runtimeConfig, scope);
      const payload = await requestJson(
        runtimeConfig,
        scopedPath(`${BASE_PATH}/metrics`, scope),
        'GET',
        options?.signal,
      );
      requireResponseScope(payload, scope);
      return parseMetrics(payload);
    },
    pauseInstance: (scope, instanceKey, options) =>
      mutateInstance(
        runtimeConfig,
        scope,
        instanceKey,
        'pause',
        'POST',
        true,
        options?.signal,
      ),
    resumeInstance: (scope, instanceKey, options) =>
      mutateInstance(
        runtimeConfig,
        scope,
        instanceKey,
        'resume',
        'POST',
        true,
        options?.signal,
      ),
    terminateInstance: (scope, instanceKey, graceful, options) =>
      mutateInstance(
        runtimeConfig,
        scope,
        instanceKey,
        null,
        'DELETE',
        graceful,
        options?.signal,
      ),
  });
}

async function mutateInstance(
  config: DesktopRuntimeConfig,
  scope: RuntimePoolScope,
  instanceKey: string,
  action: 'pause' | 'resume' | null,
  method: 'POST' | 'DELETE',
  graceful = true,
  signal?: AbortSignal,
): Promise<void> {
  requireCloudScope(config, scope);
  const key = requireIdentifier(
    instanceKey,
    'runtime_pool_instance_key_invalid',
  );
  const suffix = action === null ? '' : `/${action}`;
  const path = scopedPath(
    `${BASE_PATH}/instances/${encodeURIComponent(key)}${suffix}`,
    scope,
  );
  const payload = await requestJson(
    config,
    action === null ? `${path}&graceful=${String(graceful)}` : path,
    method,
    signal,
  );
  requireResponseScope(payload, scope);
  if (!isRecord(payload) || payload.success !== true) throw contractError();
}

async function requestJson(
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
    throw new DesktopApiError(
      errorMessage(response.status, payload),
      response.status,
      payload,
    );
  }
  if (!isJson || payload === null) throw contractError();
  return payload;
}

function parseStatus(payload: unknown): RuntimePoolStatus {
  if (
    !isRecord(payload) ||
    typeof payload.enabled !== 'boolean' ||
    !isNonEmptyString(payload.status) ||
    !isNonnegativeInteger(payload.total_instances) ||
    !isNonnegativeInteger(payload.hot_instances) ||
    !isNonnegativeInteger(payload.warm_instances) ||
    !isNonnegativeInteger(payload.cold_instances) ||
    !isNonnegativeInteger(payload.ready_instances) ||
    !isNonnegativeInteger(payload.executing_instances) ||
    !isNonnegativeInteger(payload.unhealthy_instances) ||
    !isNullableReasonCode(payload.reason_code)
  ) {
    throw contractError();
  }
  return Object.freeze({
    enabled: payload.enabled,
    status: payload.status,
    totalInstances: payload.total_instances,
    hotInstances: payload.hot_instances,
    warmInstances: payload.warm_instances,
    coldInstances: payload.cold_instances,
    readyInstances: payload.ready_instances,
    executingInstances: payload.executing_instances,
    unhealthyInstances: payload.unhealthy_instances,
    prewarmPool: parsePrewarm(payload.prewarm_pool),
    resourceUsage: parseResourceUsage(payload.resource_usage),
    reasonCode: payload.reason_code,
  });
}

function parseInstancePage(payload: unknown): RuntimePoolInstancePage {
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.instances) ||
    !isNonnegativeInteger(payload.total) ||
    !isPositiveInteger(payload.page) ||
    !isPositiveInteger(payload.page_size)
  ) {
    throw contractError();
  }
  const instances = Object.freeze(payload.instances.map(parseInstance));
  if (instances.length > payload.page_size) throw contractError();
  return Object.freeze({
    instances,
    total: payload.total,
    page: payload.page,
    pageSize: payload.page_size,
  });
}

function parseInstance(value: unknown): RuntimePoolInstance {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value.instance_key) ||
    !isNonEmptyString(value.tenant_id) ||
    !isNonEmptyString(value.project_id) ||
    !isNonEmptyString(value.agent_mode) ||
    !isTier(value.tier) ||
    !isInstanceStatus(value.status) ||
    !isNullableString(value.created_at) ||
    !isNullableString(value.last_request_at) ||
    !isNonnegativeInteger(value.active_requests) ||
    !isNonnegativeInteger(value.total_requests) ||
    !isFiniteNonnegative(value.memory_used_mb) ||
    !isHealthStatus(value.health_status)
  ) {
    throw contractError();
  }
  return Object.freeze({
    instanceKey: value.instance_key,
    tenantId: value.tenant_id,
    projectId: value.project_id,
    agentMode: value.agent_mode,
    tier: value.tier,
    status: value.status,
    createdAt: value.created_at,
    lastRequestAt: value.last_request_at,
    activeRequests: value.active_requests,
    totalRequests: value.total_requests,
    memoryUsedMb: value.memory_used_mb,
    healthStatus: value.health_status,
  });
}

function parseMetrics(payload: unknown): RuntimePoolMetrics {
  if (
    !isRecord(payload) ||
    !isRecord(payload.instances) ||
    !isRecord(payload.instances.by_tier) ||
    !isRecord(payload.instances.by_status) ||
    !isRecord(payload.health) ||
    !isNonnegativeInteger(payload.instances.total) ||
    !hasTierCounts(payload.instances.by_tier) ||
    !hasStatusCounts(payload.instances.by_status) ||
    !isNonnegativeInteger(payload.health.unhealthy_count) ||
    !isNullableReasonCode(payload.reason_code)
  ) {
    throw contractError();
  }
  return Object.freeze({
    instances: Object.freeze({
      total: payload.instances.total,
      byTier: Object.freeze({
        hot: payload.instances.by_tier.hot,
        warm: payload.instances.by_tier.warm,
        cold: payload.instances.by_tier.cold,
      }),
      byStatus: Object.freeze({
        ready: payload.instances.by_status.ready,
        executing: payload.instances.by_status.executing,
        unhealthy: payload.instances.by_status.unhealthy,
      }),
    }),
    unhealthyCount: payload.health.unhealthy_count,
    prewarm: parseNumberRecord(payload.prewarm),
    reasonCode: payload.reason_code,
  });
}

function parsePrewarm(value: unknown): RuntimePoolStatus['prewarmPool'] {
  if (value === null) return null;
  if (
    !isRecord(value) ||
    !isNonnegativeInteger(value.l1) ||
    !isNonnegativeInteger(value.l2) ||
    !isNonnegativeInteger(value.l3)
  ) {
    throw contractError();
  }
  return Object.freeze({ l1: value.l1, l2: value.l2, l3: value.l3 });
}

function parseResourceUsage(
  value: unknown,
): RuntimePoolStatus['resourceUsage'] {
  if (value === null) return null;
  if (
    !isRecord(value) ||
    !isFiniteNonnegative(value.total_memory_mb) ||
    !isFiniteNonnegative(value.used_memory_mb) ||
    !isFiniteNonnegative(value.total_cpu_cores) ||
    !isFiniteNonnegative(value.used_cpu_cores)
  ) {
    throw contractError();
  }
  return Object.freeze({
    totalMemoryMb: value.total_memory_mb,
    usedMemoryMb: value.used_memory_mb,
    totalCpuCores: value.total_cpu_cores,
    usedCpuCores: value.used_cpu_cores,
  });
}

function parseNumberRecord(
  value: unknown,
): Readonly<Record<string, number>> | null {
  if (value === null) return null;
  if (
    !isRecord(value) ||
    Object.values(value).some((entry) => !isFiniteNonnegative(entry))
  ) {
    throw contractError();
  }
  return Object.freeze({ ...value }) as Readonly<Record<string, number>>;
}

function requireCloudScope(
  config: DesktopRuntimeConfig,
  scope: RuntimePoolScope,
): void {
  if (config.mode !== 'cloud' || scope.authority !== 'cloud') {
    throw new RuntimePoolUnavailableError('cloud_runtime_pool_not_applicable');
  }
  if (
    requireIdentifier(scope.tenantId, 'runtime_pool_scope_invalid') !==
    requireIdentifier(config.tenantId, 'runtime_pool_scope_invalid')
  ) {
    throw new Error('runtime_pool_scope_mismatch');
  }
}

function requireResponseScope(payload: unknown, scope: RuntimePoolScope): void {
  if (
    !isRecord(payload) ||
    payload.resolved_scope !== 'tenant' ||
    payload.tenant_id !== scope.tenantId
  ) {
    throw new DesktopApiError('runtime_pool_response_scope_mismatch', 502, {
      reason_code: 'runtime_pool_response_scope_mismatch',
    });
  }
}

function normalizeQuery(query: RuntimePoolQuery) {
  const tier = query.tier ?? 'all';
  const status = query.status ?? 'all';
  if (tier !== 'all' && !isTier(tier))
    throw new Error('runtime_pool_tier_invalid');
  if (status !== 'all' && !isInstanceStatus(status)) {
    throw new Error('runtime_pool_status_invalid');
  }
  return Object.freeze({
    tier,
    status,
    page: integerInRange(
      query.page ?? 1,
      1,
      100_000,
      'runtime_pool_page_invalid',
    ),
    pageSize: integerInRange(
      query.pageSize ?? 20,
      1,
      100,
      'runtime_pool_page_size_invalid',
    ),
  });
}

function scopedPath(path: string, scope: RuntimePoolScope): string {
  return `${path}?${scopeParams(scope).toString()}`;
}

function scopeParams(scope: RuntimePoolScope): URLSearchParams {
  return new URLSearchParams({ scope: 'tenant', tenant_id: scope.tenantId });
}

function requireIdentifier(value: string, reasonCode: string): string {
  if (typeof value !== 'string' || !value.trim() || value !== value.trim()) {
    throw new Error(reasonCode);
  }
  return value;
}

function integerInRange(
  value: number,
  minimum: number,
  maximum: number,
  reasonCode: string,
): number {
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    throw new Error(reasonCode);
  }
  return value;
}

function hasTierCounts(
  value: Record<string, unknown>,
): value is Record<RuntimePoolTier, number> {
  return (
    isNonnegativeInteger(value.hot) &&
    isNonnegativeInteger(value.warm) &&
    isNonnegativeInteger(value.cold)
  );
}

function hasStatusCounts(
  value: Record<string, unknown>,
): value is Record<'ready' | 'executing' | 'unhealthy', number> {
  return (
    isNonnegativeInteger(value.ready) &&
    isNonnegativeInteger(value.executing) &&
    isNonnegativeInteger(value.unhealthy)
  );
}

function contractError(): DesktopApiError {
  return new DesktopApiError('cloud_runtime_pool_contract_invalid', 502, {
    reason_code: 'cloud_runtime_pool_contract_invalid',
  });
}

function errorMessage(status: number, payload: unknown): string {
  if (isRecord(payload) && typeof payload.detail === 'string')
    return payload.detail;
  return `HTTP ${status}`;
}

function isTier(value: unknown): value is RuntimePoolTier {
  return typeof value === 'string' && TIERS.has(value as RuntimePoolTier);
}

function isInstanceStatus(value: unknown): value is RuntimePoolInstanceStatus {
  return (
    typeof value === 'string' &&
    INSTANCE_STATUSES.has(value as RuntimePoolInstanceStatus)
  );
}

function isHealthStatus(value: unknown): value is RuntimePoolHealthStatus {
  return (
    typeof value === 'string' &&
    HEALTH_STATUSES.has(value as RuntimePoolHealthStatus)
  );
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

function isNullableReasonCode(value: unknown): value is string | null {
  return value === null || isNonEmptyString(value);
}

function isNonnegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) > 0;
}

function isFiniteNonnegative(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}
