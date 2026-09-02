import { RuntimeV2Error } from '@agistack/plugin-runtime';

import {
  createTenantProjectsMutationKey,
  type TenantProjectsListQuery,
  type TenantProjectsMutationAction,
  type TenantProjectsMutationInput,
  type TenantProjectsScope,
} from '../features/tenant/tenantProjectsClient';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopTenantProjectsOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TenantProjectsScope;
  signal?: AbortSignal;
}>;

export type DesktopTenantProjectsListInputV2 = DesktopTenantProjectsOperationInputV2 &
  Readonly<{ query?: TenantProjectsListQuery }>;
export type DesktopTenantProjectGetInputV2 = DesktopTenantProjectsOperationInputV2 &
  Readonly<{ projectId: string }>;
export type DesktopTenantProjectCreateInputV2 = DesktopTenantProjectsOperationInputV2 &
  Readonly<{
    input: TenantProjectsMutationInput;
    idempotencyKey?: string;
  }>;
export type DesktopTenantProjectUpdateInputV2 = DesktopTenantProjectCreateInputV2 &
  Readonly<{ projectId: string }>;
export type DesktopTenantProjectDeleteInputV2 = DesktopTenantProjectsOperationInputV2 &
  Readonly<{
    projectId: string;
    idempotencyKey?: string;
  }>;

export type PreparedTenantProjectsOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TenantProjectsScope;
  signal?: AbortSignal;
}>;
export type PreparedTenantProjectsListOperationV2 = PreparedTenantProjectsOperationV2 &
  Readonly<{ query?: TenantProjectsListQuery }>;
export type PreparedTenantProjectGetOperationV2 = PreparedTenantProjectsOperationV2 &
  Readonly<{ projectId: string }>;
export type PreparedTenantProjectCreateOperationV2 = PreparedTenantProjectsOperationV2 &
  Readonly<{
    input: TenantProjectsMutationInput;
    idempotencyKey: string;
  }>;
export type PreparedTenantProjectUpdateOperationV2 = PreparedTenantProjectCreateOperationV2 &
  Readonly<{ projectId: string }>;
export type PreparedTenantProjectDeleteOperationV2 = PreparedTenantProjectsOperationV2 &
  Readonly<{
    projectId: string;
    idempotencyKey: string;
  }>;

const BASE_KEYS_V2 = new Set(['config', 'scope', 'signal']);
const LIST_KEYS_V2 = new Set([...BASE_KEYS_V2, 'query']);
const GET_KEYS_V2 = new Set([...BASE_KEYS_V2, 'projectId']);
const CREATE_KEYS_V2 = new Set([...BASE_KEYS_V2, 'input', 'idempotencyKey']);
const UPDATE_KEYS_V2 = new Set([
  ...BASE_KEYS_V2,
  'projectId',
  'input',
  'idempotencyKey',
]);
const DELETE_KEYS_V2 = new Set([...BASE_KEYS_V2, 'projectId', 'idempotencyKey']);
const SCOPE_KEYS_V2 = new Set(['authority', 'tenantId']);

export function prepareTenantProjectsBaseOperationV2(
  input: DesktopTenantProjectsOperationInputV2,
): PreparedTenantProjectsOperationV2 {
  return prepareBaseOperationV2(input, BASE_KEYS_V2);
}

export function prepareTenantProjectsListOperationV2(
  input: DesktopTenantProjectsListInputV2,
): PreparedTenantProjectsListOperationV2 {
  const prepared = prepareBaseOperationV2(input, LIST_KEYS_V2);
  const query = input.query === undefined ? undefined : cloneListQueryV2(input.query);
  return Object.freeze({ ...prepared, ...(query === undefined ? {} : { query }) });
}

export function prepareTenantProjectGetOperationV2(
  input: DesktopTenantProjectGetInputV2,
): PreparedTenantProjectGetOperationV2 {
  const prepared = prepareBaseOperationV2(input, GET_KEYS_V2);
  return Object.freeze({ ...prepared, projectId: requireProjectIdV2(input.projectId) });
}

export function prepareTenantProjectCreateOperationV2(
  input: DesktopTenantProjectCreateInputV2,
): PreparedTenantProjectCreateOperationV2 {
  const prepared = prepareBaseOperationV2(input, CREATE_KEYS_V2);
  if (!Object.hasOwn(input, 'input')) throw invalidOperationInputV2();
  return Object.freeze({
    ...prepared,
    input: cloneMutationInputV2(input.input),
    idempotencyKey: cloneIdempotencyKeyV2('create', input.idempotencyKey),
  });
}

export function prepareTenantProjectUpdateOperationV2(
  input: DesktopTenantProjectUpdateInputV2,
): PreparedTenantProjectUpdateOperationV2 {
  const prepared = prepareBaseOperationV2(input, UPDATE_KEYS_V2);
  if (!Object.hasOwn(input, 'input')) throw invalidOperationInputV2();
  return Object.freeze({
    ...prepared,
    projectId: requireProjectIdV2(input.projectId),
    input: cloneMutationInputV2(input.input),
    idempotencyKey: cloneIdempotencyKeyV2('update', input.idempotencyKey),
  });
}

export function prepareTenantProjectDeleteOperationV2(
  input: DesktopTenantProjectDeleteInputV2,
): PreparedTenantProjectDeleteOperationV2 {
  const prepared = prepareBaseOperationV2(input, DELETE_KEYS_V2);
  return Object.freeze({
    ...prepared,
    projectId: requireProjectIdV2(input.projectId),
    idempotencyKey: cloneIdempotencyKeyV2('delete', input.idempotencyKey),
  });
}

export function cloneDesktopTenantProjectsRuntimeConfigV2(
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

export function cloneDesktopTenantProjectsScopeV2(
  scope: TenantProjectsScope,
  config: DesktopRuntimeConfig,
): TenantProjectsScope {
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
  input: DesktopTenantProjectsOperationInputV2,
  allowedKeys: ReadonlySet<string>,
): PreparedTenantProjectsOperationV2 {
  if (
    !isPlainRecordV2(input) ||
    !hasAllowedKeysV2(input, allowedKeys) ||
    !Object.hasOwn(input, 'config') ||
    !Object.hasOwn(input, 'scope') ||
    (input.signal !== undefined && !isAbortSignalV2(input.signal))
  ) {
    throw invalidOperationInputV2();
  }
  const config = cloneDesktopTenantProjectsRuntimeConfigV2(input.config);
  const scope = cloneDesktopTenantProjectsScopeV2(input.scope, config);
  return Object.freeze({
    config,
    scope,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

function cloneListQueryV2(query: TenantProjectsListQuery): TenantProjectsListQuery {
  if (!isPlainRecordV2(query) || !hasAllowedKeysV2(query, new Set([
    'page',
    'pageSize',
    'search',
    'visibility',
    'ownerId',
  ]))) {
    throw invalidOperationInputV2();
  }
  if (
    (query.page !== undefined && !isPositiveIntegerV2(query.page)) ||
    (query.pageSize !== undefined &&
      (!isPositiveIntegerV2(query.pageSize) || query.pageSize > 100)) ||
    (query.search !== undefined &&
      (typeof query.search !== 'string' || query.search.length > 2_000)) ||
    (query.visibility !== undefined &&
      query.visibility !== 'all' &&
      query.visibility !== 'public' &&
      query.visibility !== 'private') ||
    (query.ownerId !== undefined &&
      (typeof query.ownerId !== 'string' || query.ownerId.length > 512))
  ) {
    throw invalidOperationInputV2();
  }
  const search = query.search?.trim();
  const ownerId = query.ownerId?.trim();
  return Object.freeze({
    ...(query.page === undefined ? {} : { page: query.page }),
    ...(query.pageSize === undefined ? {} : { pageSize: query.pageSize }),
    ...(search ? { search } : {}),
    ...(query.visibility === undefined ? {} : { visibility: query.visibility }),
    ...(ownerId ? { ownerId } : {}),
  });
}

function cloneMutationInputV2(
  input: TenantProjectsMutationInput,
): TenantProjectsMutationInput {
  if (
    !isPlainRecordV2(input) ||
    !hasAllowedKeysV2(input, new Set(['name', 'description', 'isPublic'])) ||
    typeof input.name !== 'string' ||
    typeof input.description !== 'string' ||
    (input.isPublic !== undefined && typeof input.isPublic !== 'boolean')
  ) {
    throw invalidOperationInputV2();
  }
  const name = input.name.trim();
  const description = input.description.trim();
  if (!name || name.length > 200 || description.length > 4_000) {
    throw invalidOperationInputV2();
  }
  return Object.freeze({
    name,
    description,
    ...(input.isPublic === undefined ? {} : { isPublic: input.isPublic }),
  });
}

function requireProjectIdV2(value: unknown): string {
  if (!isCanonicalStringV2(value) || value.length > 512) {
    throw invalidOperationInputV2();
  }
  return value;
}

function cloneIdempotencyKeyV2(
  action: TenantProjectsMutationAction,
  provided: string | undefined,
): string {
  const value = provided ?? createTenantProjectsMutationKey(action);
  if (
    value.length < 8 ||
    value.length > 256 ||
    value !== value.trim() ||
    /[\u0000-\u001f\u007f]/u.test(value)
  ) {
    throw invalidOperationInputV2();
  }
  return value;
}

function invalidOperationInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_projects_operation_input_invalid',
    'desktop tenant projects operation input is invalid',
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

function isPositiveIntegerV2(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) > 0;
}

function isAbortSignalV2(value: unknown): value is AbortSignal {
  return typeof AbortSignal !== 'undefined' && value instanceof AbortSignal;
}
