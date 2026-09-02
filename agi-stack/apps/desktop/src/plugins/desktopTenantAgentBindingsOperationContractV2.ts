import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  CreateTenantAgentBindingInput,
  TenantAgentBindingsListQuery,
  TenantAgentBindingsScope,
  TestTenantAgentBindingInput,
} from '../features/tenant/tenantAgentBindingsClient';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopTenantAgentBindingsOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TenantAgentBindingsScope;
  signal?: AbortSignal;
}>;

export type DesktopTenantAgentBindingsListInputV2 =
  DesktopTenantAgentBindingsOperationInputV2 &
    Readonly<{ query?: TenantAgentBindingsListQuery }>;

export type DesktopTenantAgentBindingCreateInputV2 =
  DesktopTenantAgentBindingsOperationInputV2 &
    Readonly<{
      input: CreateTenantAgentBindingInput;
      idempotencyKey?: string;
    }>;

export type DesktopTenantAgentBindingDeleteInputV2 =
  DesktopTenantAgentBindingsOperationInputV2 &
    Readonly<{
      bindingId: string;
      idempotencyKey?: string;
    }>;

export type DesktopTenantAgentBindingSetEnabledInputV2 =
  DesktopTenantAgentBindingDeleteInputV2 & Readonly<{ enabled: boolean }>;

export type DesktopTenantAgentBindingTestInputV2 =
  DesktopTenantAgentBindingsOperationInputV2 &
    Readonly<{
      input: TestTenantAgentBindingInput;
      idempotencyKey?: string;
    }>;

export type PreparedTenantAgentBindingsOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TenantAgentBindingsScope;
  signal?: AbortSignal;
}>;
export type PreparedTenantAgentBindingsListOperationV2 =
  PreparedTenantAgentBindingsOperationV2 &
    Readonly<{ query?: TenantAgentBindingsListQuery }>;
export type PreparedTenantAgentBindingCreateOperationV2 =
  PreparedTenantAgentBindingsOperationV2 &
    Readonly<{ input: CreateTenantAgentBindingInput; idempotencyKey?: string }>;
export type PreparedTenantAgentBindingDeleteOperationV2 =
  PreparedTenantAgentBindingsOperationV2 &
    Readonly<{ bindingId: string; idempotencyKey?: string }>;
export type PreparedTenantAgentBindingSetEnabledOperationV2 =
  PreparedTenantAgentBindingDeleteOperationV2 & Readonly<{ enabled: boolean }>;
export type PreparedTenantAgentBindingTestOperationV2 =
  PreparedTenantAgentBindingsOperationV2 &
    Readonly<{ input: TestTenantAgentBindingInput; idempotencyKey?: string }>;

const BASE_KEYS_V2 = new Set(['config', 'scope', 'signal']);
const LIST_KEYS_V2 = new Set([...BASE_KEYS_V2, 'query']);
const CREATE_KEYS_V2 = new Set([...BASE_KEYS_V2, 'input', 'idempotencyKey']);
const DELETE_KEYS_V2 = new Set([...BASE_KEYS_V2, 'bindingId', 'idempotencyKey']);
const SET_ENABLED_KEYS_V2 = new Set([
  ...BASE_KEYS_V2,
  'bindingId',
  'enabled',
  'idempotencyKey',
]);
const TEST_KEYS_V2 = new Set([...BASE_KEYS_V2, 'input', 'idempotencyKey']);
const SCOPE_KEYS_V2 = new Set(['authority', 'tenantId']);
const CREATE_INPUT_KEYS_V2 = new Set([
  'agentId',
  'channelType',
  'channelId',
  'accountId',
  'peerId',
  'groupId',
  'priority',
]);
const TEST_INPUT_KEYS_V2 = new Set([
  'channelType',
  'channelId',
  'accountId',
  'peerId',
]);

export function prepareTenantAgentBindingsBaseOperationV2(
  input: DesktopTenantAgentBindingsOperationInputV2,
): PreparedTenantAgentBindingsOperationV2 {
  return prepareBaseOperationV2(input, BASE_KEYS_V2);
}

export function prepareTenantAgentBindingsListOperationV2(
  input: DesktopTenantAgentBindingsListInputV2,
): PreparedTenantAgentBindingsListOperationV2 {
  const prepared = prepareBaseOperationV2(input, LIST_KEYS_V2);
  const query = input.query === undefined ? undefined : cloneListQueryV2(input.query);
  return Object.freeze({ ...prepared, ...(query === undefined ? {} : { query }) });
}

export function prepareTenantAgentBindingCreateOperationV2(
  input: DesktopTenantAgentBindingCreateInputV2,
): PreparedTenantAgentBindingCreateOperationV2 {
  const prepared = prepareBaseOperationV2(input, CREATE_KEYS_V2);
  if (!Object.hasOwn(input, 'input')) throw invalidOperationInputV2();
  return Object.freeze({
    ...prepared,
    input: cloneCreateInputV2(input.input),
    ...cloneIdempotencyKeyV2(input.idempotencyKey),
  });
}

export function prepareTenantAgentBindingDeleteOperationV2(
  input: DesktopTenantAgentBindingDeleteInputV2,
): PreparedTenantAgentBindingDeleteOperationV2 {
  return prepareDeleteOperationV2(input, DELETE_KEYS_V2);
}

export function prepareTenantAgentBindingSetEnabledOperationV2(
  input: DesktopTenantAgentBindingSetEnabledInputV2,
): PreparedTenantAgentBindingSetEnabledOperationV2 {
  const prepared = prepareDeleteOperationV2(input, SET_ENABLED_KEYS_V2);
  if (!Object.hasOwn(input, 'enabled') || typeof input.enabled !== 'boolean') {
    throw invalidOperationInputV2();
  }
  return Object.freeze({ ...prepared, enabled: input.enabled });
}

export function prepareTenantAgentBindingTestOperationV2(
  input: DesktopTenantAgentBindingTestInputV2,
): PreparedTenantAgentBindingTestOperationV2 {
  const prepared = prepareBaseOperationV2(input, TEST_KEYS_V2);
  if (!Object.hasOwn(input, 'input')) throw invalidOperationInputV2();
  return Object.freeze({
    ...prepared,
    input: cloneTestInputV2(input.input),
    ...cloneIdempotencyKeyV2(input.idempotencyKey),
  });
}

export function cloneDesktopTenantAgentBindingsRuntimeConfigV2(
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
    !isCanonicalStringV2(copy.tenantId)
  ) {
    throw invalidOperationInputV2();
  }
  return Object.freeze(copy);
}

export function cloneDesktopTenantAgentBindingsScopeV2(
  scope: TenantAgentBindingsScope,
  config: DesktopRuntimeConfig,
): TenantAgentBindingsScope {
  if (
    !isPlainRecordV2(scope) ||
    !hasExactKeysV2(scope, SCOPE_KEYS_V2) ||
    scope.authority !== config.mode ||
    !isCanonicalStringV2(scope.tenantId) ||
    scope.tenantId !== config.tenantId
  ) {
    throw invalidOperationInputV2();
  }
  return Object.freeze({ authority: scope.authority, tenantId: scope.tenantId });
}

function prepareBaseOperationV2(
  input: DesktopTenantAgentBindingsOperationInputV2,
  allowedKeys: ReadonlySet<string>,
): PreparedTenantAgentBindingsOperationV2 {
  if (
    !isPlainRecordV2(input) ||
    !hasAllowedKeysV2(input, allowedKeys) ||
    !Object.hasOwn(input, 'config') ||
    !Object.hasOwn(input, 'scope') ||
    (input.signal !== undefined && !isAbortSignalV2(input.signal))
  ) {
    throw invalidOperationInputV2();
  }
  const config = cloneDesktopTenantAgentBindingsRuntimeConfigV2(input.config);
  const scope = cloneDesktopTenantAgentBindingsScopeV2(input.scope, config);
  return Object.freeze({
    config,
    scope,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

function prepareDeleteOperationV2(
  input: DesktopTenantAgentBindingDeleteInputV2,
  allowedKeys: ReadonlySet<string>,
): PreparedTenantAgentBindingDeleteOperationV2 {
  const prepared = prepareBaseOperationV2(input, allowedKeys);
  if (!Object.hasOwn(input, 'bindingId') || !isCanonicalStringV2(input.bindingId)) {
    throw invalidOperationInputV2();
  }
  return Object.freeze({
    ...prepared,
    bindingId: input.bindingId,
    ...cloneIdempotencyKeyV2(input.idempotencyKey),
  });
}

function cloneListQueryV2(query: TenantAgentBindingsListQuery): TenantAgentBindingsListQuery {
  if (
    !isPlainRecordV2(query) ||
    !hasAllowedKeysV2(query, new Set(['agentId', 'enabledOnly'])) ||
    (query.agentId !== undefined && !isCanonicalStringV2(query.agentId)) ||
    (query.enabledOnly !== undefined && typeof query.enabledOnly !== 'boolean')
  ) {
    throw invalidOperationInputV2();
  }
  return Object.freeze({
    ...(query.agentId === undefined ? {} : { agentId: query.agentId }),
    ...(query.enabledOnly === undefined ? {} : { enabledOnly: query.enabledOnly }),
  });
}

function cloneCreateInputV2(
  input: CreateTenantAgentBindingInput,
): CreateTenantAgentBindingInput {
  if (
    !isPlainRecordV2(input) ||
    !hasExactKeysV2(input, CREATE_INPUT_KEYS_V2) ||
    !isCanonicalStringV2(input.agentId) ||
    !isOptionalCanonicalStringV2(input.channelType) ||
    !isOptionalCanonicalStringV2(input.channelId) ||
    !isOptionalCanonicalStringV2(input.accountId) ||
    !isOptionalCanonicalStringV2(input.peerId) ||
    !isOptionalCanonicalStringV2(input.groupId) ||
    !Number.isSafeInteger(input.priority)
  ) {
    throw invalidOperationInputV2();
  }
  return Object.freeze({ ...input });
}

function cloneTestInputV2(input: TestTenantAgentBindingInput): TestTenantAgentBindingInput {
  if (
    !isPlainRecordV2(input) ||
    !hasExactKeysV2(input, TEST_INPUT_KEYS_V2) ||
    !isCanonicalStringV2(input.channelType) ||
    !isOptionalCanonicalStringV2(input.channelId) ||
    !isOptionalCanonicalStringV2(input.accountId) ||
    !isOptionalCanonicalStringV2(input.peerId)
  ) {
    throw invalidOperationInputV2();
  }
  return Object.freeze({ ...input });
}

function cloneIdempotencyKeyV2(
  value: string | undefined,
): Readonly<{ idempotencyKey?: string }> {
  if (value === undefined) return Object.freeze({});
  if (
    value.length < 8 ||
    value.length > 256 ||
    value !== value.trim() ||
    /[\u0000-\u001f\u007f]/u.test(value)
  ) {
    throw invalidOperationInputV2();
  }
  return Object.freeze({ idempotencyKey: value });
}

function invalidOperationInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_agent_bindings_operation_input_invalid',
    'desktop tenant agent bindings operation input is invalid',
  );
}

function hasAllowedKeysV2(
  value: Record<string, unknown>,
  allowed: ReadonlySet<string>,
): boolean {
  return Object.keys(value).every((key) => allowed.has(key));
}

function hasExactKeysV2(
  value: Record<string, unknown>,
  expected: ReadonlySet<string>,
): boolean {
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

function isOptionalCanonicalStringV2(value: unknown): value is string | null {
  return value === null || isCanonicalStringV2(value);
}

function isAbortSignalV2(value: unknown): value is AbortSignal {
  return typeof AbortSignal !== 'undefined' && value instanceof AbortSignal;
}
