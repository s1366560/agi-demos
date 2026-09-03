import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  ProjectAdministrationScope,
  ProjectMembershipRole,
} from '../features/project-administration/projectAdministrationClient';
import {
  PROJECT_SCHEMA_DEGRADED_REASON,
  type ProjectSchemaMapping,
  type ProjectSchemaSnapshot,
  type ProjectSchemaType,
} from '../features/project-administration/projectSchemaClient';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopProjectSchemaLoadOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProjectAdministrationScope;
  signal?: AbortSignal;
}>;

export type DesktopProjectSchemaAuthorityOperationInputV2 =
  DesktopProjectSchemaLoadOperationInputV2 & Readonly<{ kind: 'load' }>;

export type PreparedDesktopProjectSchemaAuthorityOperationV2 =
  DesktopProjectSchemaAuthorityOperationInputV2;

const INPUT_KEYS_V2 = new Set(['kind', 'config', 'scope', 'signal']);
const SCOPE_KEYS_V2 = new Set(['authority', 'tenantId', 'projectId']);
const SNAPSHOT_KEYS_V2 = new Set([
  'scope',
  'scopeRevision',
  'authority',
  'availability',
  'reasonCode',
  'contractVersion',
  'allowedActions',
  'membershipRole',
  'entityTypes',
  'edgeTypes',
  'mappings',
]);
const TYPE_KEYS_V2 = new Set([
  'id',
  'projectId',
  'name',
  'description',
  'schema',
  'status',
  'source',
  'createdAt',
  'updatedAt',
]);
const MAPPING_KEYS_V2 = new Set([
  'id',
  'projectId',
  'sourceType',
  'targetType',
  'edgeType',
  'status',
  'source',
  'createdAt',
]);
const ROLES_V2 = new Set<ProjectMembershipRole>(['owner', 'admin', 'member', 'viewer']);

export function prepareDesktopProjectSchemaAuthorityOperationV2(
  input: DesktopProjectSchemaAuthorityOperationInputV2,
): PreparedDesktopProjectSchemaAuthorityOperationV2 {
  if (
    !isPlainRecordV2(input) ||
    input.kind !== 'load' ||
    !hasExactOptionalKeysV2(input, INPUT_KEYS_V2) ||
    !Object.hasOwn(input, 'config') ||
    !Object.hasOwn(input, 'scope') ||
    (input.signal !== undefined && !isAbortSignalV2(input.signal))
  ) {
    throw invalidInputV2();
  }
  const config = cloneDesktopProjectSchemaRuntimeConfigV2(input.config);
  const scope = cloneDesktopProjectSchemaScopeV2(input.scope, config);
  return Object.freeze({
    kind: 'load',
    config,
    scope,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

export function cloneDesktopProjectSchemaRuntimeConfigV2(
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
    !canonicalIdentifierV2(copy.tenantId) ||
    !canonicalIdentifierV2(copy.projectId)
  ) {
    throw invalidInputV2();
  }
  return Object.freeze(copy);
}

export function cloneDesktopProjectSchemaScopeV2(
  scope: ProjectAdministrationScope,
  config: DesktopRuntimeConfig,
): ProjectAdministrationScope {
  if (
    !isPlainRecordV2(scope) ||
    !hasExactKeysV2(scope, SCOPE_KEYS_V2) ||
    scope.authority !== config.mode ||
    !canonicalIdentifierV2(scope.tenantId) ||
    !canonicalIdentifierV2(scope.projectId) ||
    scope.tenantId !== config.tenantId ||
    scope.projectId !== config.projectId
  ) {
    throw invalidInputV2();
  }
  return Object.freeze({
    authority: scope.authority,
    tenantId: scope.tenantId,
    projectId: scope.projectId,
  });
}

export function requireDesktopProjectSchemaSnapshotV2(
  value: unknown,
  scope: ProjectAdministrationScope,
): ProjectSchemaSnapshot {
  if (
    scope.authority !== 'cloud' ||
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, SNAPSHOT_KEYS_V2) ||
    value.authority !== 'cloud' ||
    value.availability !== 'degraded' ||
    value.reasonCode !== PROJECT_SCHEMA_DEGRADED_REASON ||
    value.contractVersion !== '4.0.0' ||
    !exactActionsV2(value.allowedActions) ||
    !Number.isSafeInteger(value.scopeRevision) ||
    Number(value.scopeRevision) < 0 ||
    !sameScopeV2(value.scope, scope) ||
    !validRoleV2(value.membershipRole) ||
    !validTypesV2(value.entityTypes, scope.projectId) ||
    !validTypesV2(value.edgeTypes, scope.projectId) ||
    !validMappingsV2(value.mappings, scope.projectId)
  ) {
    throw invalidServiceContractV2();
  }
  try {
    return deepFreezeV2(structuredClone(value)) as ProjectSchemaSnapshot;
  } catch {
    throw invalidServiceContractV2();
  }
}

function validTypesV2(value: unknown, projectId: string): value is readonly ProjectSchemaType[] {
  if (!Array.isArray(value)) return false;
  const ids = new Set<string>();
  for (const item of value) {
    if (!validTypeV2(item, projectId) || ids.has(item.id)) return false;
    ids.add(item.id);
  }
  return true;
}

function validTypeV2(value: unknown, projectId: string): value is ProjectSchemaType {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, TYPE_KEYS_V2) &&
    canonicalIdentifierV2(value.id) &&
    value.projectId === projectId &&
    canonicalIdentifierV2(value.name) &&
    (value.description === null || typeof value.description === 'string') &&
    validJsonObjectV2(value.schema) &&
    canonicalIdentifierV2(value.status) &&
    canonicalIdentifierV2(value.source) &&
    canonicalIdentifierV2(value.createdAt) &&
    (value.updatedAt === null || canonicalIdentifierV2(value.updatedAt))
  );
}

function validMappingsV2(
  value: unknown,
  projectId: string,
): value is readonly ProjectSchemaMapping[] {
  if (!Array.isArray(value)) return false;
  const ids = new Set<string>();
  for (const item of value) {
    if (!validMappingV2(item, projectId) || ids.has(item.id)) return false;
    ids.add(item.id);
  }
  return true;
}

function validMappingV2(value: unknown, projectId: string): value is ProjectSchemaMapping {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, MAPPING_KEYS_V2) &&
    canonicalIdentifierV2(value.id) &&
    value.projectId === projectId &&
    canonicalIdentifierV2(value.sourceType) &&
    canonicalIdentifierV2(value.targetType) &&
    canonicalIdentifierV2(value.edgeType) &&
    canonicalIdentifierV2(value.status) &&
    canonicalIdentifierV2(value.source) &&
    canonicalIdentifierV2(value.createdAt)
  );
}

function validJsonObjectV2(value: unknown): value is Readonly<Record<string, unknown>> {
  return isPlainRecordV2(value) && validJsonValueV2(value, new WeakSet());
}

function validJsonValueV2(value: unknown, ancestors: WeakSet<object>): boolean {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return true;
  if (typeof value === 'number') return Number.isFinite(value);
  if (!Array.isArray(value) && !isPlainRecordV2(value)) return false;
  if (ancestors.has(value)) return false;
  ancestors.add(value);
  const valid = Array.isArray(value)
    ? value.every((item) => validJsonValueV2(item, ancestors))
    : Object.values(value).every((item) => validJsonValueV2(item, ancestors));
  ancestors.delete(value);
  return valid;
}

function sameScopeV2(value: unknown, scope: ProjectAdministrationScope): boolean {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, SCOPE_KEYS_V2) &&
    value.authority === scope.authority &&
    value.tenantId === scope.tenantId &&
    value.projectId === scope.projectId
  );
}

function exactActionsV2(value: unknown): boolean {
  return (
    Array.isArray(value) &&
    value.length === 2 &&
    value[0] === 'view' &&
    value[1] === 'list-entity-types'
  );
}

function validRoleV2(value: unknown): value is ProjectMembershipRole {
  return typeof value === 'string' && ROLES_V2.has(value as ProjectMembershipRole);
}

function invalidInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_schema_operation_input_invalid',
    'desktop project schema operation input is invalid',
  );
}

function invalidServiceContractV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_schema_service_contract_invalid',
    'desktop project schema authority returned an invalid result',
  );
}

function hasExactOptionalKeysV2(
  value: Record<string, unknown>,
  allowed: ReadonlySet<string>,
): boolean {
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

function canonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function canonicalIdentifierV2(value: unknown): value is string {
  return canonicalStringV2(value) && value.length <= 512;
}

function isAbortSignalV2(value: unknown): value is AbortSignal {
  return typeof AbortSignal !== 'undefined' && value instanceof AbortSignal;
}

function deepFreezeV2<T>(value: T): T {
  if (value !== null && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const nested of Object.values(value)) deepFreezeV2(nested);
  }
  return value;
}
