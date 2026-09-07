import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  BackendStoreCreateInput,
  BackendStorePlane,
  BackendStoreTestInput,
  BackendStoreUpdateInput,
} from '../features/backend-stores/backendStoresClient';
import type {
  TenantManagementRequestOptions,
  TenantManagementScope,
} from '../features/tenant-admin/tenantManagementHttp';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopBackendStoresOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TenantManagementScope;
  options?: TenantManagementRequestOptions;
}>;
export type DesktopBackendStoresPlaneOperationInputV2 = DesktopBackendStoresOperationInputV2 &
  Readonly<{ plane: BackendStorePlane }>;
export type DesktopBackendStoreCreateOperationInputV2 = DesktopBackendStoresPlaneOperationInputV2 &
  Readonly<{ input: BackendStoreCreateInput }>;
export type DesktopBackendStoreUpdateOperationInputV2 = DesktopBackendStoresPlaneOperationInputV2 &
  Readonly<{ storeId: string; input: BackendStoreUpdateInput }>;
export type DesktopBackendStoreRemoveOperationInputV2 = DesktopBackendStoresPlaneOperationInputV2 &
  Readonly<{ storeId: string }>;
export type DesktopBackendStoreTestDraftOperationInputV2 =
  DesktopBackendStoresPlaneOperationInputV2 & Readonly<{ input: BackendStoreTestInput }>;
export type DesktopBackendStoreTestExistingOperationInputV2 =
  DesktopBackendStoresPlaneOperationInputV2 & Readonly<{ storeId: string }>;

export type DesktopBackendStoresAuthorityOperationInputV2 =
  | (DesktopBackendStoresOperationInputV2 & Readonly<{ kind: 'load' | 'probe' }>)
  | (DesktopBackendStoreCreateOperationInputV2 & Readonly<{ kind: 'create' }>)
  | (DesktopBackendStoreUpdateOperationInputV2 & Readonly<{ kind: 'update' }>)
  | (DesktopBackendStoreRemoveOperationInputV2 & Readonly<{ kind: 'remove' }>)
  | (DesktopBackendStoreTestDraftOperationInputV2 & Readonly<{ kind: 'testDraft' }>)
  | (DesktopBackendStoreTestExistingOperationInputV2 & Readonly<{ kind: 'testExisting' }>);

export type PreparedDesktopBackendStoresAuthorityOperationV2 = Readonly<{
  kind: DesktopBackendStoresAuthorityOperationInputV2['kind'];
  config: DesktopRuntimeConfig;
  scope: TenantManagementScope;
  options?: TenantManagementRequestOptions;
  plane?: BackendStorePlane;
  storeId?: string;
  input?: BackendStoreCreateInput | BackendStoreUpdateInput | BackendStoreTestInput;
}>;

const BASE_KEYS = new Set(['kind', 'config', 'scope', 'options']);
const PLANE_KEYS = new Set([...BASE_KEYS, 'plane']);
const INPUT_KEYS = new Set([...PLANE_KEYS, 'input']);
const STORE_KEYS = new Set([...PLANE_KEYS, 'storeId']);
const UPDATE_KEYS = new Set([...STORE_KEYS, 'input']);
const SCOPE_KEYS = new Set(['authority', 'tenantId']);
const OPTIONS_KEYS = new Set(['signal']);

export function prepareDesktopBackendStoresAuthorityOperationV2(
  value: DesktopBackendStoresAuthorityOperationInputV2,
): PreparedDesktopBackendStoresAuthorityOperationV2 {
  if (!isRecord(value)) throw invalidInput();
  const allowed =
    value.kind === 'load' || value.kind === 'probe'
      ? BASE_KEYS
      : value.kind === 'create' || value.kind === 'testDraft'
        ? INPUT_KEYS
        : value.kind === 'update'
          ? UPDATE_KEYS
          : value.kind === 'remove' || value.kind === 'testExisting'
            ? STORE_KEYS
            : null;
  if (allowed === null || !hasAllowedKeys(value, allowed)) throw invalidInput();
  const config = cloneDesktopBackendStoresConfigV2(value.config);
  const scope = cloneDesktopBackendStoresScopeV2(value.scope, config);
  const options = cloneOptions(value.options);
  const record = value as unknown as Record<string, unknown>;
  const base = {
    kind: value.kind,
    config,
    scope,
    ...(options ? { options } : {}),
  };
  if (value.kind === 'load' || value.kind === 'probe') return Object.freeze(base);
  const plane = requirePlane(record.plane);
  if (value.kind === 'remove' || value.kind === 'testExisting') {
    return Object.freeze({
      ...base,
      plane,
      storeId: requireIdentifier(record.storeId),
    });
  }
  if (value.kind === 'create') {
    return Object.freeze({
      ...base,
      plane,
      input: cloneCreateInput(record.input),
    });
  }
  if (value.kind === 'update') {
    return Object.freeze({
      ...base,
      plane,
      storeId: requireIdentifier(record.storeId),
      input: cloneUpdateInput(record.input),
    });
  }
  return Object.freeze({ ...base, plane, input: cloneTestInput(record.input) });
}

export function cloneDesktopBackendStoresConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (!isRecord(config)) throw invalidInput();
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
    Object.values(copy).some((item) => typeof item !== 'string') ||
    (copy.mode !== 'cloud' && copy.mode !== 'local') ||
    !canonical(copy.apiBaseUrl) ||
    !identifier(copy.tenantId)
  )
    throw invalidInput();
  return Object.freeze(copy);
}

function cloneDesktopBackendStoresScopeV2(
  scope: TenantManagementScope,
  config: DesktopRuntimeConfig,
): TenantManagementScope {
  if (
    !isRecord(scope) ||
    !exactKeys(scope, SCOPE_KEYS) ||
    (scope.authority !== 'cloud' && scope.authority !== 'local') ||
    !identifier(scope.tenantId) ||
    scope.tenantId !== config.tenantId
  )
    throw invalidInput();
  return Object.freeze({
    authority: scope.authority,
    tenantId: scope.tenantId,
  });
}

function cloneOptions(
  options: TenantManagementRequestOptions | undefined,
): TenantManagementRequestOptions | undefined {
  if (options === undefined) return undefined;
  if (
    !isRecord(options) ||
    !hasAllowedKeys(options, OPTIONS_KEYS) ||
    (options.signal !== undefined && !isAbortSignal(options.signal))
  )
    throw invalidInput();
  return Object.freeze(options.signal === undefined ? {} : { signal: options.signal });
}

function cloneCreateInput(value: unknown): BackendStoreCreateInput {
  if (
    !isRecord(value) ||
    !exactKeysOneOf(value, [
      ['name', 'engineType', 'connectionConfig'],
      ['name', 'engineType', 'connectionConfig', 'indexConfig'],
    ])
  )
    throw invalidInput();
  const connectionConfig = cloneSecretRecord(value.connectionConfig);
  return Object.freeze({
    name: requireIdentifier(value.name),
    engineType: requireIdentifier(value.engineType),
    connectionConfig,
    ...(value.indexConfig === undefined ? {} : { indexConfig: cloneRecord(value.indexConfig) }),
  });
}

function cloneUpdateInput(value: unknown): BackendStoreUpdateInput {
  const allowed = new Set(['name', 'connectionConfig', 'indexConfig']);
  if (!isRecord(value) || !hasAllowedKeys(value, allowed) || Object.keys(value).length === 0)
    throw invalidInput();
  return Object.freeze({
    ...(value.name === undefined ? {} : { name: requireIdentifier(value.name) }),
    ...(value.connectionConfig === undefined
      ? {}
      : { connectionConfig: cloneSecretRecord(value.connectionConfig) }),
    ...(value.indexConfig === undefined ? {} : { indexConfig: cloneRecord(value.indexConfig) }),
  });
}

function cloneTestInput(value: unknown): BackendStoreTestInput {
  if (!isRecord(value) || !exactKeys(value, new Set(['engineType', 'connectionConfig'])))
    throw invalidInput();
  return Object.freeze({
    engineType: requireIdentifier(value.engineType),
    connectionConfig: cloneSecretRecord(value.connectionConfig),
  });
}

function cloneSecretRecord(value: unknown): Readonly<Record<string, unknown>> {
  const result = cloneRecord(value);
  if (containsMaskedSecret(result))
    throw new RuntimeV2Error(
      'backend_stores_masked_secret_rejected',
      'masked backend store secrets cannot be submitted',
    );
  return result;
}

function cloneRecord(value: unknown): Readonly<Record<string, unknown>> {
  if (!isRecord(value)) throw invalidInput();
  return Object.freeze(
    Object.fromEntries(Object.entries(value).map(([key, item]) => [key, cloneJson(item)])),
  );
}

function cloneJson(value: unknown): unknown {
  if (Array.isArray(value)) return Object.freeze(value.map(cloneJson));
  if (isRecord(value)) return cloneRecord(value);
  if (value === null || ['string', 'number', 'boolean'].includes(typeof value)) {
    if (typeof value === 'number' && !Number.isFinite(value)) throw invalidInput();
    return value;
  }
  throw invalidInput();
}

function containsMaskedSecret(value: unknown): boolean {
  if (value === '***') return true;
  if (Array.isArray(value)) return value.some(containsMaskedSecret);
  return isRecord(value) && Object.values(value).some(containsMaskedSecret);
}

function requirePlane(value: unknown): BackendStorePlane {
  if (value !== 'graph' && value !== 'retrieval') throw invalidInput();
  return value;
}
function requireIdentifier(value: unknown): string {
  if (!identifier(value)) throw invalidInput();
  return value;
}
function identifier(value: unknown): value is string {
  return (
    canonical(value) &&
    value.length <= 256 &&
    /^[A-Za-z0-9](?:[A-Za-z0-9._:-]*[A-Za-z0-9])?$/u.test(value)
  );
}
function canonical(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}
function isAbortSignal(value: unknown): value is AbortSignal {
  return (
    isRecord(value) &&
    typeof value.aborted === 'boolean' &&
    typeof value.addEventListener === 'function'
  );
}
function hasAllowedKeys(value: Record<string, unknown>, keys: ReadonlySet<string>): boolean {
  return Object.keys(value).every((key) => keys.has(key));
}
function exactKeys(value: Record<string, unknown>, keys: ReadonlySet<string>): boolean {
  return Object.keys(value).length === keys.size && hasAllowedKeys(value, keys);
}
function exactKeysOneOf(
  value: Record<string, unknown>,
  sets: readonly (readonly string[])[],
): boolean {
  return sets.some((keys) => exactKeys(value, new Set(keys)));
}
function isRecord(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}
function invalidInput(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_backend_stores_operation_input_invalid',
    'desktop backend stores operation input is invalid',
  );
}
