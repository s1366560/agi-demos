import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  ProjectAdministrationScope,
  ProjectMembershipRole,
} from '../features/project-administration/projectAdministrationClient';
import {
  PROJECT_MAINTENANCE_DEGRADED_REASON,
  type ProjectEmbeddingStatus,
  type ProjectMaintenanceSnapshot,
  type ProjectMaintenanceStats,
  type ProjectMaintenanceStatus,
} from '../features/project-administration/projectMaintenanceClient';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopProjectMaintenanceLoadOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProjectAdministrationScope;
  signal?: AbortSignal;
}>;

export type DesktopProjectMaintenanceAuthorityOperationInputV2 =
  DesktopProjectMaintenanceLoadOperationInputV2 & Readonly<{ kind: 'load' }>;

export type PreparedDesktopProjectMaintenanceAuthorityOperationV2 =
  DesktopProjectMaintenanceAuthorityOperationInputV2;

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
  'stats',
  'maintenanceStatus',
  'embeddingStatus',
]);
const STATS_KEYS_V2 = new Set(['entityCount', 'episodeCount', 'communityCount', 'edgeCount']);
const STATUS_KEYS_V2 = new Set([
  'entities',
  'episodes',
  'communities',
  'oldEpisodes',
  'recommendations',
  'lastChecked',
]);
const EMBEDDING_KEYS_V2 = new Set([
  'currentProvider',
  'currentDimension',
  'existingDimension',
  'compatible',
  'missingEmbeddings',
]);
const ROLES_V2 = new Set<ProjectMembershipRole>(['owner', 'admin', 'member', 'viewer']);

export function prepareDesktopProjectMaintenanceAuthorityOperationV2(
  input: DesktopProjectMaintenanceAuthorityOperationInputV2,
): PreparedDesktopProjectMaintenanceAuthorityOperationV2 {
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
  const config = cloneDesktopProjectMaintenanceRuntimeConfigV2(input.config);
  const scope = cloneDesktopProjectMaintenanceScopeV2(input.scope, config);
  return Object.freeze({
    kind: 'load',
    config,
    scope,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

export function cloneDesktopProjectMaintenanceRuntimeConfigV2(
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

export function cloneDesktopProjectMaintenanceScopeV2(
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

export function requireDesktopProjectMaintenanceSnapshotV2(
  value: unknown,
  scope: ProjectAdministrationScope,
): ProjectMaintenanceSnapshot {
  if (
    scope.authority !== 'cloud' ||
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, SNAPSHOT_KEYS_V2) ||
    value.authority !== 'cloud' ||
    value.availability !== 'degraded' ||
    value.reasonCode !== PROJECT_MAINTENANCE_DEGRADED_REASON ||
    value.contractVersion !== '4.0.0' ||
    !exactActionsV2(value.allowedActions) ||
    !nonnegativeIntegerV2(value.scopeRevision) ||
    !sameScopeV2(value.scope, scope) ||
    !validRoleV2(value.membershipRole) ||
    !validStatsV2(value.stats) ||
    !validMaintenanceStatusV2(value.maintenanceStatus) ||
    !validEmbeddingStatusV2(value.embeddingStatus)
  ) {
    throw invalidServiceContractV2();
  }
  try {
    return deepFreezeV2(structuredClone(value)) as ProjectMaintenanceSnapshot;
  } catch {
    throw invalidServiceContractV2();
  }
}

function validStatsV2(value: unknown): value is ProjectMaintenanceStats {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, STATS_KEYS_V2) &&
    Object.values(value).every(nonnegativeIntegerV2)
  );
}

function validMaintenanceStatusV2(value: unknown): value is ProjectMaintenanceStatus {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, STATUS_KEYS_V2) &&
    nonnegativeIntegerV2(value.entities) &&
    nonnegativeIntegerV2(value.episodes) &&
    nonnegativeIntegerV2(value.communities) &&
    nonnegativeIntegerV2(value.oldEpisodes) &&
    Array.isArray(value.recommendations) &&
    value.recommendations.every(canonicalIdentifierV2) &&
    typeof value.lastChecked === 'string' &&
    value.lastChecked === value.lastChecked.trim() &&
    value.lastChecked.length <= 512
  );
}

function validEmbeddingStatusV2(value: unknown): value is ProjectEmbeddingStatus {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, EMBEDDING_KEYS_V2) &&
    canonicalIdentifierV2(value.currentProvider) &&
    nonnegativeIntegerV2(value.currentDimension) &&
    nonnegativeIntegerV2(value.existingDimension) &&
    typeof value.compatible === 'boolean' &&
    nonnegativeIntegerV2(value.missingEmbeddings)
  );
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
  return Array.isArray(value) && value.length === 1 && value[0] === 'view';
}

function validRoleV2(value: unknown): value is ProjectMembershipRole {
  return typeof value === 'string' && ROLES_V2.has(value as ProjectMembershipRole);
}

function nonnegativeIntegerV2(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function invalidInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_maintenance_operation_input_invalid',
    'desktop project maintenance operation input is invalid',
  );
}

function invalidServiceContractV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_maintenance_service_contract_invalid',
    'desktop project maintenance authority returned an invalid result',
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
