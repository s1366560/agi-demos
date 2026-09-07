import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  RuntimePoolQuery,
  RuntimePoolScope,
  RuntimePoolInstanceStatus,
  RuntimePoolTier,
} from '../features/runtime-pool/runtimePoolClient';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopRuntimePoolOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: RuntimePoolScope;
  signal?: AbortSignal;
}>;

export type DesktopRuntimePoolListOperationInputV2 = DesktopRuntimePoolOperationInputV2 &
  Readonly<{ query?: RuntimePoolQuery }>;

export type DesktopRuntimePoolInstanceOperationInputV2 = DesktopRuntimePoolOperationInputV2 &
  Readonly<{ instanceKey: string }>;

export type DesktopRuntimePoolTerminateOperationInputV2 =
  DesktopRuntimePoolInstanceOperationInputV2 & Readonly<{ graceful: boolean }>;

export type PreparedDesktopRuntimePoolOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: RuntimePoolScope;
  signal?: AbortSignal;
}>;

export type PreparedDesktopRuntimePoolListOperationV2 = PreparedDesktopRuntimePoolOperationV2 &
  Readonly<{ query: Required<RuntimePoolQuery> }>;

export type PreparedDesktopRuntimePoolInstanceOperationV2 = PreparedDesktopRuntimePoolOperationV2 &
  Readonly<{ instanceKey: string }>;

export type PreparedDesktopRuntimePoolTerminateOperationV2 =
  PreparedDesktopRuntimePoolInstanceOperationV2 & Readonly<{ graceful: boolean }>;

const BASE_INPUT_KEYS_V2 = new Set(['config', 'scope', 'signal']);
const LIST_INPUT_KEYS_V2 = new Set([...BASE_INPUT_KEYS_V2, 'query']);
const INSTANCE_INPUT_KEYS_V2 = new Set([...BASE_INPUT_KEYS_V2, 'instanceKey']);
const TERMINATE_INPUT_KEYS_V2 = new Set([...INSTANCE_INPUT_KEYS_V2, 'graceful']);
const SCOPE_KEYS_V2 = new Set(['authority', 'tenantId']);
const QUERY_KEYS_V2 = new Set(['tier', 'status', 'page', 'pageSize']);
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

export function prepareDesktopRuntimePoolOperationV2(
  input: DesktopRuntimePoolOperationInputV2,
): PreparedDesktopRuntimePoolOperationV2 {
  return prepareBaseOperationV2(input, BASE_INPUT_KEYS_V2);
}

export function prepareDesktopRuntimePoolListOperationV2(
  input: DesktopRuntimePoolListOperationInputV2,
): PreparedDesktopRuntimePoolListOperationV2 {
  const prepared = prepareBaseOperationV2(input, LIST_INPUT_KEYS_V2);
  const query = cloneRuntimePoolQueryV2(input.query ?? {});
  return Object.freeze({ ...prepared, query });
}

export function prepareDesktopRuntimePoolInstanceOperationV2(
  input: DesktopRuntimePoolInstanceOperationInputV2,
): PreparedDesktopRuntimePoolInstanceOperationV2 {
  const prepared = prepareBaseOperationV2(input, INSTANCE_INPUT_KEYS_V2);
  return Object.freeze({
    ...prepared,
    instanceKey: canonicalIdentifierV2(input.instanceKey),
  });
}

export function prepareDesktopRuntimePoolTerminateOperationV2(
  input: DesktopRuntimePoolTerminateOperationInputV2,
): PreparedDesktopRuntimePoolTerminateOperationV2 {
  const prepared = prepareBaseOperationV2(input, TERMINATE_INPUT_KEYS_V2);
  if (typeof input.graceful !== 'boolean') throw invalidOperationInputV2();
  return Object.freeze({
    ...prepared,
    instanceKey: canonicalIdentifierV2(input.instanceKey),
    graceful: input.graceful,
  });
}

export function cloneDesktopRuntimePoolConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw invalidOperationInputV2();
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
    !isCanonicalStringV2(copy.apiBaseUrl) ||
    !isCanonicalStringV2(copy.tenantId)
  ) {
    throw invalidOperationInputV2();
  }
  return Object.freeze(copy);
}

function prepareBaseOperationV2(
  input: DesktopRuntimePoolOperationInputV2,
  allowedKeys: ReadonlySet<string>,
): PreparedDesktopRuntimePoolOperationV2 {
  if (
    !isPlainRecordV2(input) ||
    !hasAllowedKeysV2(input, allowedKeys) ||
    !Object.hasOwn(input, 'config') ||
    !Object.hasOwn(input, 'scope') ||
    (input.signal !== undefined && !isAbortSignalV2(input.signal))
  ) {
    throw invalidOperationInputV2();
  }
  const config = cloneDesktopRuntimePoolConfigV2(input.config);
  const scope = cloneRuntimePoolScopeV2(input.scope, config);
  return Object.freeze({
    config,
    scope,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

function cloneRuntimePoolScopeV2(
  scope: RuntimePoolScope,
  config: DesktopRuntimeConfig,
): RuntimePoolScope {
  if (
    !isPlainRecordV2(scope) ||
    !hasExactKeysV2(scope, SCOPE_KEYS_V2) ||
    (scope.authority !== 'cloud' && scope.authority !== 'local') ||
    scope.authority !== config.mode ||
    !isCanonicalStringV2(scope.tenantId) ||
    scope.tenantId !== config.tenantId
  ) {
    throw invalidOperationInputV2();
  }
  return Object.freeze({
    authority: scope.authority,
    tenantId: scope.tenantId,
  });
}

function cloneRuntimePoolQueryV2(query: RuntimePoolQuery): Required<RuntimePoolQuery> {
  if (!isPlainRecordV2(query) || !hasAllowedKeysV2(query, QUERY_KEYS_V2)) {
    throw invalidOperationInputV2();
  }
  const tier = query.tier ?? 'all';
  const status = query.status ?? 'all';
  const page = query.page ?? 1;
  const pageSize = query.pageSize ?? 20;
  if (
    (tier !== 'all' && !TIERS_V2.has(tier)) ||
    (status !== 'all' && !STATUSES_V2.has(status)) ||
    !integerInRangeV2(page, 1, 100_000) ||
    !integerInRangeV2(pageSize, 1, 100)
  ) {
    throw invalidOperationInputV2();
  }
  return Object.freeze({ tier, status, page, pageSize });
}

function canonicalIdentifierV2(value: unknown): string {
  if (!isCanonicalStringV2(value)) throw invalidOperationInputV2();
  return value;
}

function invalidOperationInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_runtime_pool_operation_input_invalid',
    'desktop runtime pool operation input is invalid',
  );
}

function integerInRangeV2(value: unknown, minimum: number, maximum: number): value is number {
  return Number.isInteger(value) && Number(value) >= minimum && Number(value) <= maximum;
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

function isCanonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isAbortSignalV2(value: unknown): value is AbortSignal {
  return typeof AbortSignal !== 'undefined' && value instanceof AbortSignal;
}
