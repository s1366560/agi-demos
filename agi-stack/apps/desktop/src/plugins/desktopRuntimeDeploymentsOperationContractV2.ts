import { RuntimeV2Error } from '@agistack/plugin-runtime';

import {
  RUNTIME_DEPLOYMENTS_CLOUD_ACTIONS,
  RUNTIME_DEPLOYMENTS_CLOUD_REASON,
  RUNTIME_DEPLOYMENTS_LOCAL_REASON,
} from '../features/runtime-deployments/runtimeDeploymentsContract';
import type {
  RuntimeDeployment,
  RuntimeDeploymentProgressEvent,
  RuntimeDeploymentsPage,
  RuntimeDeploymentsQuery,
  RuntimeDeploymentsScope,
} from '../features/runtime-deployments/runtimeDeploymentsTypes';
import type { DesktopCapabilityAvailability } from '../features/runtime/capabilitySnapshot';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopRuntimeDeploymentsOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: RuntimeDeploymentsScope;
  signal?: AbortSignal;
}>;

export type DesktopRuntimeDeploymentsListOperationInputV2 =
  DesktopRuntimeDeploymentsOperationInputV2 &
    Readonly<{ query?: RuntimeDeploymentsQuery }>;

export type DesktopRuntimeDeploymentGetOperationInputV2 =
  DesktopRuntimeDeploymentsOperationInputV2 &
    Readonly<{ deploymentId: string }>;

export type DesktopRuntimeDeploymentStreamOperationInputV2 =
  DesktopRuntimeDeploymentGetOperationInputV2 &
    Readonly<{
      onEvent: (
        event: RuntimeDeploymentProgressEvent,
      ) => void | Promise<void>;
    }>;

export type DesktopRuntimeDeploymentsAuthorityOperationInputV2 =
  | (DesktopRuntimeDeploymentsListOperationInputV2 & Readonly<{ kind: 'list' }>)
  | (DesktopRuntimeDeploymentGetOperationInputV2 & Readonly<{ kind: 'get' }>)
  | (DesktopRuntimeDeploymentStreamOperationInputV2 &
      Readonly<{ kind: 'streamProgress' }>)
  | (DesktopRuntimeDeploymentsOperationInputV2 & Readonly<{ kind: 'probe' }>);

export type PreparedDesktopRuntimeDeploymentsAuthorityOperationV2 =
  | Readonly<{
      kind: 'list';
      config: DesktopRuntimeConfig;
      scope: RuntimeDeploymentsScope;
      query: Required<RuntimeDeploymentsQuery>;
      signal?: AbortSignal;
    }>
  | Readonly<{
      kind: 'get';
      config: DesktopRuntimeConfig;
      scope: RuntimeDeploymentsScope;
      deploymentId: string;
      signal?: AbortSignal;
    }>
  | Readonly<{
      kind: 'streamProgress';
      config: DesktopRuntimeConfig;
      scope: RuntimeDeploymentsScope;
      deploymentId: string;
      onEvent: (
        event: RuntimeDeploymentProgressEvent,
      ) => void | Promise<void>;
      signal?: AbortSignal;
    }>
  | Readonly<{
      kind: 'probe';
      config: DesktopRuntimeConfig;
      scope: RuntimeDeploymentsScope;
      signal?: AbortSignal;
    }>;

const BASE_KEYS_V2 = new Set(['kind', 'config', 'scope', 'signal']);
const LIST_KEYS_V2 = new Set([...BASE_KEYS_V2, 'query']);
const GET_KEYS_V2 = new Set([...BASE_KEYS_V2, 'deploymentId']);
const STREAM_KEYS_V2 = new Set([...GET_KEYS_V2, 'onEvent']);
const SCOPE_KEYS_V2 = new Set(['authority', 'tenantId', 'instanceId']);
const QUERY_KEYS_V2 = new Set(['page', 'pageSize']);
const PAGE_KEYS_V2 = new Set(['deployments', 'total', 'page', 'pageSize']);
const DEPLOYMENT_KEYS_V2 = new Set([
  'id',
  'instanceId',
  'action',
  'revision',
  'status',
  'imageVersion',
  'replicas',
  'startedAt',
  'finishedAt',
  'createdAt',
]);
const PROGRESS_KEYS_V2 = new Set(['type', 'status', 'deployId']);
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

export function prepareDesktopRuntimeDeploymentsAuthorityOperationV2(
  input: DesktopRuntimeDeploymentsAuthorityOperationInputV2,
): PreparedDesktopRuntimeDeploymentsAuthorityOperationV2 {
  if (!isPlainRecordV2(input)) throw invalidInputV2();
  const allowedKeys =
    input.kind === 'list'
      ? LIST_KEYS_V2
      : input.kind === 'get'
        ? GET_KEYS_V2
        : input.kind === 'streamProgress'
          ? STREAM_KEYS_V2
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
  const config = cloneDesktopRuntimeDeploymentsConfigV2(input.config);
  const scope = cloneDesktopRuntimeDeploymentsScopeV2(input.scope, config);
  const signal = input.signal === undefined ? {} : { signal: input.signal };
  if (input.kind === 'list') {
    return Object.freeze({
      kind: 'list',
      config,
      scope,
      query: cloneRuntimeDeploymentsQueryV2(input.query ?? {}),
      ...signal,
    });
  }
  if (input.kind === 'get') {
    return Object.freeze({
      kind: 'get',
      config,
      scope,
      deploymentId: requireCanonicalIdentifierV2(input.deploymentId),
      ...signal,
    });
  }
  if (input.kind === 'streamProgress') {
    if (typeof input.onEvent !== 'function') throw invalidInputV2();
    return Object.freeze({
      kind: 'streamProgress',
      config,
      scope,
      deploymentId: requireCanonicalIdentifierV2(input.deploymentId),
      onEvent: input.onEvent,
      ...signal,
    });
  }
  return Object.freeze({ kind: 'probe', config, scope, ...signal });
}

export function cloneDesktopRuntimeDeploymentsConfigV2(
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

export function cloneDesktopRuntimeDeploymentsScopeV2(
  scope: RuntimeDeploymentsScope,
  config: DesktopRuntimeConfig,
): RuntimeDeploymentsScope {
  if (
    !isPlainRecordV2(scope) ||
    !hasExactKeysV2(scope, SCOPE_KEYS_V2) ||
    (scope.authority !== 'cloud' && scope.authority !== 'local') ||
    scope.authority !== config.mode ||
    !canonicalIdentifierV2(scope.tenantId) ||
    scope.tenantId !== config.tenantId ||
    (scope.instanceId !== null && !canonicalIdentifierV2(scope.instanceId))
  ) {
    throw invalidInputV2();
  }
  return Object.freeze({
    authority: scope.authority,
    tenantId: scope.tenantId,
    instanceId: scope.instanceId,
  });
}

export function requireDesktopRuntimeDeploymentsPageV2(
  value: unknown,
  scope: RuntimeDeploymentsScope,
): RuntimeDeploymentsPage {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, PAGE_KEYS_V2) ||
    !Array.isArray(value.deployments) ||
    !nonnegativeIntegerV2(value.total) ||
    !integerInRangeV2(value.page, 1, 100_000) ||
    !integerInRangeV2(value.pageSize, 1, 100) ||
    value.deployments.length > value.total ||
    value.deployments.length > value.pageSize
  ) {
    throw invalidServiceContractV2();
  }
  const identifiers = new Set<string>();
  const deployments = value.deployments.map((candidate) => {
    const deployment = requireDesktopRuntimeDeploymentV2(candidate, scope);
    if (identifiers.has(deployment.id)) throw invalidServiceContractV2();
    identifiers.add(deployment.id);
    return deployment;
  });
  return Object.freeze({
    deployments: Object.freeze(deployments),
    total: value.total,
    page: value.page,
    pageSize: value.pageSize,
  });
}

export function requireDesktopRuntimeDeploymentV2(
  value: unknown,
  scope: RuntimeDeploymentsScope,
): RuntimeDeployment {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, DEPLOYMENT_KEYS_V2) ||
    !canonicalIdentifierV2(value.id) ||
    !canonicalIdentifierV2(value.instanceId) ||
    (scope.instanceId !== null && value.instanceId !== scope.instanceId) ||
    !canonicalStringV2(value.action) ||
    !nonnegativeIntegerV2(value.revision) ||
    !isDeploymentStatusV2(value.status) ||
    !nullableStringV2(value.imageVersion) ||
    !nullableNonnegativeIntegerV2(value.replicas) ||
    !nullableStringV2(value.startedAt) ||
    !nullableStringV2(value.finishedAt) ||
    !canonicalStringV2(value.createdAt)
  ) {
    throw invalidServiceContractV2();
  }
  return Object.freeze({
    id: value.id,
    instanceId: value.instanceId,
    action: value.action,
    revision: value.revision,
    status: value.status,
    imageVersion: value.imageVersion,
    replicas: value.replicas,
    startedAt: value.startedAt,
    finishedAt: value.finishedAt,
    createdAt: value.createdAt,
  });
}

export function requireDesktopRuntimeDeploymentProgressEventV2(
  value: unknown,
  deploymentId: string,
): RuntimeDeploymentProgressEvent {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, PROGRESS_KEYS_V2) ||
    !canonicalStringV2(value.type) ||
    !nullableCanonicalStringV2(value.status) ||
    !nullableCanonicalIdentifierV2(value.deployId) ||
    (value.deployId !== null && value.deployId !== deploymentId)
  ) {
    throw invalidServiceContractV2();
  }
  return Object.freeze({
    type: value.type,
    status: value.status,
    deployId: value.deployId,
  });
}

export function requireDesktopRuntimeDeploymentsStreamResultV2(value: unknown): void {
  if (value !== undefined) throw invalidServiceContractV2();
}

export function requireDesktopRuntimeDeploymentsCapabilityV2(
  value: unknown,
  scope: RuntimeDeploymentsScope,
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
        value.reason_code !== RUNTIME_DEPLOYMENTS_LOCAL_REASON ||
        value.service_version !== null ||
        value.contract_version !== null ||
        value.allowed_actions.length !== 0
      : value.availability !== 'degraded' ||
        value.reason_code !== RUNTIME_DEPLOYMENTS_CLOUD_REASON ||
        value.service_version !== '0.1.0' ||
        value.contract_version !== '3.0.0' ||
        !sameOrderedStringsV2(value.allowed_actions, RUNTIME_DEPLOYMENTS_CLOUD_ACTIONS)
  ) {
    throw invalidServiceContractV2();
  }
  return deepFreezeV2(structuredClone(value)) as DesktopCapabilityAvailability;
}

function cloneRuntimeDeploymentsQueryV2(
  query: RuntimeDeploymentsQuery,
): Required<RuntimeDeploymentsQuery> {
  if (!isPlainRecordV2(query) || !hasAllowedKeysV2(query, QUERY_KEYS_V2)) {
    throw invalidInputV2();
  }
  const page = query.page ?? 1;
  const pageSize = query.pageSize ?? 10;
  if (!integerInRangeV2(page, 1, 100_000) || !integerInRangeV2(pageSize, 1, 100)) {
    throw invalidInputV2();
  }
  return Object.freeze({ page, pageSize });
}

function sameCapabilityScopeV2(value: unknown, scope: RuntimeDeploymentsScope): boolean {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, CAPABILITY_SCOPE_KEYS_V2) &&
    value.tenant_id === scope.tenantId &&
    value.project_id === null &&
    value.workspace_id === null &&
    value.instance_id === null
  );
}

function sameOrderedStringsV2(value: readonly unknown[], expected: readonly string[]): boolean {
  return value.length === expected.length && value.every((item, index) => item === expected[index]);
}

function invalidInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_runtime_deployments_operation_input_invalid',
    'desktop runtime deployments operation input is invalid',
  );
}

function invalidServiceContractV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_runtime_deployments_service_contract_invalid',
    'desktop runtime deployments service returned an invalid contract',
  );
}

function requireCanonicalIdentifierV2(value: unknown): string {
  if (!canonicalIdentifierV2(value)) throw invalidInputV2();
  return value;
}

function isDeploymentStatusV2(value: unknown): value is RuntimeDeployment['status'] {
  return (
    value === 'pending' ||
    value === 'running' ||
    value === 'success' ||
    value === 'failed' ||
    value === 'cancelled'
  );
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

function nullableCanonicalStringV2(value: unknown): value is string | null {
  return value === null || canonicalStringV2(value);
}

function nullableCanonicalIdentifierV2(value: unknown): value is string | null {
  return value === null || canonicalIdentifierV2(value);
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
