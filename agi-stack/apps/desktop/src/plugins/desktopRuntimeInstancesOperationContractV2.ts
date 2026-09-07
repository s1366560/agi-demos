import { RuntimeV2Error } from '@agistack/plugin-runtime';

import {
  RUNTIME_INSTANCES_CLOUD_ACTIONS,
  RUNTIME_INSTANCES_CLOUD_REASON,
  RUNTIME_INSTANCES_LOCAL_ACTIONS,
  RUNTIME_INSTANCES_LOCAL_REASON,
} from '../features/runtime-instances/runtimeInstancesContract';
import type {
  RuntimeInstanceSummary,
  RuntimeInstancesPage,
  RuntimeInstancesQuery,
  RuntimeInstancesScope,
} from '../features/runtime-instances/runtimeInstancesTypes';
import type { DesktopCapabilityAvailability } from '../features/runtime/capabilitySnapshot';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopRuntimeInstancesOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: RuntimeInstancesScope;
  signal?: AbortSignal;
}>;

export type DesktopRuntimeInstancesListOperationInputV2 =
  DesktopRuntimeInstancesOperationInputV2 & Readonly<{ query?: RuntimeInstancesQuery }>;

export type DesktopRuntimeInstanceMutationOperationInputV2 =
  DesktopRuntimeInstancesOperationInputV2 & Readonly<{ instanceId: string }>;

export type DesktopRuntimeInstancesAuthorityOperationInputV2 =
  | (DesktopRuntimeInstancesListOperationInputV2 & Readonly<{ kind: 'list' }>)
  | (DesktopRuntimeInstanceMutationOperationInputV2 & Readonly<{ kind: 'restart' | 'delete' }>)
  | (DesktopRuntimeInstancesOperationInputV2 & Readonly<{ kind: 'probe' }>);

export type PreparedDesktopRuntimeInstancesAuthorityOperationV2 =
  | Readonly<{
      kind: 'list';
      config: DesktopRuntimeConfig;
      scope: RuntimeInstancesScope;
      query: Required<RuntimeInstancesQuery>;
      signal?: AbortSignal;
    }>
  | Readonly<{
      kind: 'restart' | 'delete';
      config: DesktopRuntimeConfig;
      scope: RuntimeInstancesScope;
      instanceId: string;
      signal?: AbortSignal;
    }>
  | Readonly<{
      kind: 'probe';
      config: DesktopRuntimeConfig;
      scope: RuntimeInstancesScope;
      signal?: AbortSignal;
    }>;

const BASE_KEYS_V2 = new Set(['kind', 'config', 'scope', 'signal']);
const LIST_KEYS_V2 = new Set([...BASE_KEYS_V2, 'query']);
const MUTATION_KEYS_V2 = new Set([...BASE_KEYS_V2, 'instanceId']);
const SCOPE_KEYS_V2 = new Set(['authority', 'tenantId']);
const QUERY_KEYS_V2 = new Set(['page', 'pageSize', 'search', 'status']);
const PAGE_KEYS_V2 = new Set(['instances', 'total', 'page', 'pageSize']);
const INSTANCE_KEYS_V2 = new Set([
  'id',
  'name',
  'status',
  'healthStatus',
  'imageVersion',
  'replicas',
  'availableReplicas',
  'clusterId',
  'createdAt',
  'updatedAt',
  'projection',
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

export function prepareDesktopRuntimeInstancesAuthorityOperationV2(
  input: DesktopRuntimeInstancesAuthorityOperationInputV2,
): PreparedDesktopRuntimeInstancesAuthorityOperationV2 {
  if (!isPlainRecordV2(input)) throw invalidInputV2();
  const allowedKeys =
    input.kind === 'list'
      ? LIST_KEYS_V2
      : input.kind === 'restart' || input.kind === 'delete'
        ? MUTATION_KEYS_V2
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
  const config = cloneDesktopRuntimeInstancesConfigV2(input.config);
  const scope = cloneDesktopRuntimeInstancesScopeV2(input.scope, config);
  const signal = input.signal === undefined ? {} : { signal: input.signal };
  if (input.kind === 'list') {
    return Object.freeze({
      kind: 'list',
      config,
      scope,
      query: cloneRuntimeInstancesQueryV2(input.query ?? {}),
      ...signal,
    });
  }
  if (input.kind === 'restart' || input.kind === 'delete') {
    return Object.freeze({
      kind: input.kind,
      config,
      scope,
      instanceId: requireCanonicalIdentifierV2(input.instanceId),
      ...signal,
    });
  }
  return Object.freeze({ kind: 'probe', config, scope, ...signal });
}

export function cloneDesktopRuntimeInstancesConfigV2(
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

export function cloneDesktopRuntimeInstancesScopeV2(
  scope: RuntimeInstancesScope,
  config: DesktopRuntimeConfig,
): RuntimeInstancesScope {
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

export function requireDesktopRuntimeInstancesPageV2(
  value: unknown,
): RuntimeInstancesPage {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, PAGE_KEYS_V2) ||
    !Array.isArray(value.instances) ||
    !nonnegativeIntegerV2(value.total) ||
    !integerInRangeV2(value.page, 1, 100_000) ||
    !integerInRangeV2(value.pageSize, 1, 100) ||
    value.instances.length > value.total ||
    value.instances.length > value.pageSize
  ) {
    throw invalidServiceContractV2();
  }
  const identifiers = new Set<string>();
  const instances = value.instances.map((instanceValue) => {
    const instance = requireRuntimeInstanceSummaryV2(instanceValue);
    if (identifiers.has(instance.id)) throw invalidServiceContractV2();
    identifiers.add(instance.id);
    return instance;
  });
  return Object.freeze({
    instances: Object.freeze(instances),
    total: value.total,
    page: value.page,
    pageSize: value.pageSize,
  });
}

export function requireDesktopRuntimeInstancesMutationResultV2(value: unknown): void {
  if (value !== undefined) throw invalidServiceContractV2();
}

export function requireDesktopRuntimeInstancesCapabilityV2(
  value: unknown,
  scope: RuntimeInstancesScope,
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
      ? value.availability !== 'degraded' ||
        value.reason_code !== RUNTIME_INSTANCES_LOCAL_REASON ||
        value.service_version !== '0.1.0' ||
        value.contract_version !== '3.0.0' ||
        !sameOrderedStringsV2(value.allowed_actions, RUNTIME_INSTANCES_LOCAL_ACTIONS)
      : value.availability !== 'degraded' ||
        value.reason_code !== RUNTIME_INSTANCES_CLOUD_REASON ||
        value.service_version !== '0.1.0' ||
        value.contract_version !== '3.0.0' ||
        !sameOrderedStringsV2(value.allowed_actions, RUNTIME_INSTANCES_CLOUD_ACTIONS)
  ) {
    throw invalidServiceContractV2();
  }
  return deepFreezeV2(structuredClone(value)) as DesktopCapabilityAvailability;
}

function cloneRuntimeInstancesQueryV2(
  query: RuntimeInstancesQuery,
): Required<RuntimeInstancesQuery> {
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

function requireRuntimeInstanceSummaryV2(value: unknown): RuntimeInstanceSummary {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, INSTANCE_KEYS_V2) ||
    !canonicalIdentifierV2(value.id) ||
    !canonicalStringV2(value.name) ||
    !canonicalStringV2(value.status) ||
    !nullableStringV2(value.healthStatus) ||
    !nullableStringV2(value.imageVersion) ||
    !nullableNonnegativeIntegerV2(value.replicas) ||
    !nullableNonnegativeIntegerV2(value.availableReplicas) ||
    !nullableStringV2(value.clusterId) ||
    !nullableStringV2(value.createdAt) ||
    !nullableStringV2(value.updatedAt) ||
    (value.projection !== 'cloud' && value.projection !== 'local_sidecar')
  ) {
    throw invalidServiceContractV2();
  }
  return Object.freeze({
    id: value.id,
    name: value.name,
    status: value.status,
    healthStatus: value.healthStatus,
    imageVersion: value.imageVersion,
    replicas: value.replicas,
    availableReplicas: value.availableReplicas,
    clusterId: value.clusterId,
    createdAt: value.createdAt,
    updatedAt: value.updatedAt,
    projection: value.projection,
  });
}

function sameCapabilityScopeV2(value: unknown, scope: RuntimeInstancesScope): boolean {
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
    'desktop_runtime_instances_operation_input_invalid',
    'desktop runtime instances operation input is invalid',
  );
}

function invalidServiceContractV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_runtime_instances_service_contract_invalid',
    'desktop runtime instances service returned an invalid contract',
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

function nullableNonnegativeIntegerV2(value: unknown): value is number | null {
  return value === null || nonnegativeIntegerV2(value);
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
