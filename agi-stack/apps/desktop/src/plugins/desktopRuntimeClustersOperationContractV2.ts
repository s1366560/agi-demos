import { RuntimeV2Error } from '@agistack/plugin-runtime';

import {
  RUNTIME_CLUSTERS_CLOUD_ACTIONS,
  RUNTIME_CLUSTERS_CLOUD_REASON,
  RUNTIME_CLUSTERS_LOCAL_REASON,
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

export type DesktopRuntimeClustersOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: RuntimeClustersScope;
  signal?: AbortSignal;
}>;

export type DesktopRuntimeClustersListOperationInputV2 =
  DesktopRuntimeClustersOperationInputV2 & Readonly<{ query?: RuntimeClustersQuery }>;

export type DesktopRuntimeClusterHealthOperationInputV2 =
  DesktopRuntimeClustersOperationInputV2 & Readonly<{ clusterId: string }>;

export type DesktopRuntimeClustersAuthorityOperationInputV2 =
  | (DesktopRuntimeClustersListOperationInputV2 & Readonly<{ kind: 'list' }>)
  | (DesktopRuntimeClusterHealthOperationInputV2 & Readonly<{ kind: 'health' }>)
  | (DesktopRuntimeClustersOperationInputV2 & Readonly<{ kind: 'probe' }>);

export type PreparedDesktopRuntimeClustersAuthorityOperationV2 =
  | Readonly<{
      kind: 'list';
      config: DesktopRuntimeConfig;
      scope: RuntimeClustersScope;
      query: Required<RuntimeClustersQuery>;
      signal?: AbortSignal;
    }>
  | Readonly<{
      kind: 'health';
      config: DesktopRuntimeConfig;
      scope: RuntimeClustersScope;
      clusterId: string;
      signal?: AbortSignal;
    }>
  | Readonly<{
      kind: 'probe';
      config: DesktopRuntimeConfig;
      scope: RuntimeClustersScope;
      signal?: AbortSignal;
    }>;

const BASE_KEYS_V2 = new Set(['kind', 'config', 'scope', 'signal']);
const LIST_KEYS_V2 = new Set([...BASE_KEYS_V2, 'query']);
const HEALTH_KEYS_V2 = new Set([...BASE_KEYS_V2, 'clusterId']);
const SCOPE_KEYS_V2 = new Set(['authority', 'tenantId']);
const QUERY_KEYS_V2 = new Set(['page', 'pageSize', 'search', 'status']);
const PAGE_KEYS_V2 = new Set(['clusters', 'total', 'page', 'pageSize']);
const CLUSTER_KEYS_V2 = new Set([
  'id',
  'name',
  'computeProvider',
  'proxyEndpoint',
  'status',
  'healthStatus',
  'lastHealthCheck',
  'createdAt',
  'updatedAt',
]);
const HEALTH_RESULT_KEYS_V2 = new Set([
  'status',
  'nodeCount',
  'cpuUsage',
  'memoryUsage',
  'checkedAt',
]);
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

export function prepareDesktopRuntimeClustersAuthorityOperationV2(
  input: DesktopRuntimeClustersAuthorityOperationInputV2,
): PreparedDesktopRuntimeClustersAuthorityOperationV2 {
  if (!isPlainRecordV2(input)) throw invalidInputV2();
  const allowedKeys =
    input.kind === 'list'
      ? LIST_KEYS_V2
      : input.kind === 'health'
        ? HEALTH_KEYS_V2
        : input.kind === 'probe'
          ? BASE_KEYS_V2
          : null;
  if (
    allowedKeys === null ||
    !hasAllowedKeysV2(input, allowedKeys) ||
    !Object.hasOwn(input, 'config') ||
    !Object.hasOwn(input, 'scope') ||
    (input.signal !== undefined && !isAbortSignalV2(input.signal))
  ) {
    throw invalidInputV2();
  }
  const config = cloneDesktopRuntimeClustersConfigV2(input.config);
  const scope = cloneDesktopRuntimeClustersScopeV2(input.scope, config);
  const signal = input.signal === undefined ? {} : { signal: input.signal };
  if (input.kind === 'list') {
    return Object.freeze({
      kind: 'list',
      config,
      scope,
      query: cloneRuntimeClustersQueryV2(input.query ?? {}),
      ...signal,
    });
  }
  if (input.kind === 'health') {
    return Object.freeze({
      kind: 'health',
      config,
      scope,
      clusterId: requireCanonicalIdentifierV2(input.clusterId),
      ...signal,
    });
  }
  return Object.freeze({ kind: 'probe', config, scope, ...signal });
}

export function cloneDesktopRuntimeClustersConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw invalidInputV2();
  const copy: DesktopRuntimeConfig = {
    apiBaseUrl: config.apiBaseUrl,
    deviceAuthorizationBaseUrl: config.deviceAuthorizationBaseUrl,
    apiKey: config.apiKey,
    localApiToken: config.localApiToken,
    tenantId: config.tenantId,
    projectId: config.projectId,
    workspaceId: config.workspaceId,
    mode: config.mode,
    workspaceRoot: config.workspaceRoot,
  };
  if (
    Object.values(copy).some((value) => typeof value !== 'string') ||
    (copy.mode !== 'cloud' && copy.mode !== 'local') ||
    !canonicalStringV2(copy.apiBaseUrl) ||
    !canonicalIdentifierV2(copy.tenantId)
  ) {
    throw invalidInputV2();
  }
  return Object.freeze(copy);
}

export function cloneDesktopRuntimeClustersScopeV2(
  scope: RuntimeClustersScope,
  config: DesktopRuntimeConfig,
): RuntimeClustersScope {
  if (
    !isPlainRecordV2(scope) ||
    !hasExactKeysV2(scope, SCOPE_KEYS_V2) ||
    (scope.authority !== 'cloud' && scope.authority !== 'local') ||
    scope.authority !== config.mode ||
    !canonicalIdentifierV2(scope.tenantId) ||
    scope.tenantId !== config.tenantId
  ) {
    throw invalidInputV2();
  }
  return Object.freeze({ authority: scope.authority, tenantId: scope.tenantId });
}

export function requireDesktopRuntimeClustersPageV2(
  value: unknown,
): RuntimeClustersPage {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, PAGE_KEYS_V2) ||
    !Array.isArray(value.clusters) ||
    !nonnegativeIntegerV2(value.total) ||
    !integerInRangeV2(value.page, 1, 100_000) ||
    !integerInRangeV2(value.pageSize, 1, 100) ||
    value.clusters.length > value.total ||
    value.clusters.length > value.pageSize
  ) {
    throw invalidServiceContractV2();
  }
  const identifiers = new Set<string>();
  const clusters = value.clusters.map((clusterValue) => {
    const cluster = requireRuntimeClusterSummaryV2(clusterValue);
    if (identifiers.has(cluster.id)) throw invalidServiceContractV2();
    identifiers.add(cluster.id);
    return cluster;
  });
  return Object.freeze({
    clusters: Object.freeze(clusters),
    total: value.total,
    page: value.page,
    pageSize: value.pageSize,
  });
}

export function requireDesktopRuntimeClusterHealthV2(
  value: unknown,
): RuntimeClusterHealth {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, HEALTH_RESULT_KEYS_V2) ||
    !canonicalStringV2(value.status) ||
    !nonnegativeIntegerV2(value.nodeCount) ||
    !nullableNonnegativeNumberV2(value.cpuUsage) ||
    !nullableNonnegativeNumberV2(value.memoryUsage) ||
    !nullableStringV2(value.checkedAt)
  ) {
    throw invalidServiceContractV2();
  }
  return Object.freeze({
    status: value.status,
    nodeCount: value.nodeCount,
    cpuUsage: value.cpuUsage,
    memoryUsage: value.memoryUsage,
    checkedAt: value.checkedAt,
  });
}

export function requireDesktopRuntimeClustersCapabilityV2(
  value: unknown,
  scope: RuntimeClustersScope,
): DesktopCapabilityAvailability {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, CAPABILITY_KEYS_V2) ||
    !sameCapabilityScopeV2(value.scope, scope) ||
    value.authority_revision !== null ||
    !Array.isArray(value.allowed_actions)
  ) {
    throw invalidServiceContractV2();
  }
  const local = scope.authority === 'local';
  if (
    local
      ? value.availability !== 'not_applicable' ||
        value.reason_code !== RUNTIME_CLUSTERS_LOCAL_REASON ||
        value.service_version !== null ||
        value.contract_version !== null ||
        value.allowed_actions.length !== 0
      : value.availability !== 'degraded' ||
        value.reason_code !== RUNTIME_CLUSTERS_CLOUD_REASON ||
        value.service_version !== '0.1.0' ||
        value.contract_version !== '3.0.0' ||
        !sameOrderedStringsV2(value.allowed_actions, RUNTIME_CLUSTERS_CLOUD_ACTIONS)
  ) {
    throw invalidServiceContractV2();
  }
  return deepFreezeV2(structuredClone(value)) as DesktopCapabilityAvailability;
}

function cloneRuntimeClustersQueryV2(
  query: RuntimeClustersQuery,
): Required<RuntimeClustersQuery> {
  if (!isPlainRecordV2(query) || !hasAllowedKeysV2(query, QUERY_KEYS_V2)) {
    throw invalidInputV2();
  }
  const page = query.page ?? 1;
  const pageSize = query.pageSize ?? 20;
  const search = query.search ?? '';
  const status = query.status ?? 'all';
  if (
    !integerInRangeV2(page, 1, 100_000) ||
    !integerInRangeV2(pageSize, 1, 100) ||
    typeof search !== 'string' ||
    search !== search.trim() ||
    search.length > 200 ||
    !canonicalStringV2(status)
  ) {
    throw invalidInputV2();
  }
  return Object.freeze({ page, pageSize, search, status });
}

function requireRuntimeClusterSummaryV2(value: unknown): RuntimeClusterSummary {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, CLUSTER_KEYS_V2) ||
    !canonicalIdentifierV2(value.id) ||
    !canonicalStringV2(value.name) ||
    !canonicalStringV2(value.computeProvider) ||
    !nullableStringV2(value.proxyEndpoint) ||
    !canonicalStringV2(value.status) ||
    !nullableStringV2(value.healthStatus) ||
    !nullableStringV2(value.lastHealthCheck) ||
    !canonicalStringV2(value.createdAt) ||
    !nullableStringV2(value.updatedAt)
  ) {
    throw invalidServiceContractV2();
  }
  return Object.freeze({
    id: value.id,
    name: value.name,
    computeProvider: value.computeProvider,
    proxyEndpoint: value.proxyEndpoint,
    status: value.status,
    healthStatus: value.healthStatus,
    lastHealthCheck: value.lastHealthCheck,
    createdAt: value.createdAt,
    updatedAt: value.updatedAt,
  });
}

function sameCapabilityScopeV2(value: unknown, scope: RuntimeClustersScope): boolean {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, CAPABILITY_SCOPE_KEYS_V2) &&
    value.tenant_id === scope.tenantId &&
    value.project_id === null &&
    value.workspace_id === null &&
    value.instance_id === null
  );
}

function sameOrderedStringsV2(
  value: readonly unknown[],
  expected: readonly string[],
): boolean {
  return (
    value.length === expected.length &&
    value.every((candidate, index) => candidate === expected[index])
  );
}

function invalidInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_runtime_clusters_operation_input_invalid',
    'desktop runtime clusters operation input is invalid',
  );
}

function invalidServiceContractV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_runtime_clusters_service_contract_invalid',
    'desktop runtime clusters service returned an invalid contract',
  );
}

function requireCanonicalIdentifierV2(value: unknown): string {
  if (!canonicalIdentifierV2(value)) throw invalidInputV2();
  return value;
}

function canonicalIdentifierV2(value: unknown): value is string {
  return canonicalStringV2(value) && !/\s/u.test(value);
}

function canonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function nullableStringV2(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function nullableNonnegativeNumberV2(value: unknown): value is number | null {
  return value === null || (typeof value === 'number' && Number.isFinite(value) && value >= 0);
}

function nonnegativeIntegerV2(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function integerInRangeV2(value: unknown, minimum: number, maximum: number): value is number {
  return Number.isSafeInteger(value) && Number(value) >= minimum && Number(value) <= maximum;
}

function hasAllowedKeysV2(value: Record<string, unknown>, allowed: ReadonlySet<string>): boolean {
  return Object.keys(value).every((key) => allowed.has(key));
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

function isAbortSignalV2(value: unknown): value is AbortSignal {
  return typeof AbortSignal !== 'undefined' && value instanceof AbortSignal;
}

function deepFreezeV2<T>(value: T): T {
  if (typeof value !== 'object' || value === null || Object.isFrozen(value)) return value;
  Object.freeze(value);
  for (const child of Object.values(value)) deepFreezeV2(child);
  return value;
}
