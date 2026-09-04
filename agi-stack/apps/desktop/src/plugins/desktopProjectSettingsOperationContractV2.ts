import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  ProjectAdministrationScope,
  ProjectMembershipRole,
} from '../features/project-administration/projectAdministrationClient';
import {
  PROJECT_SETTINGS_DEGRADED_REASON,
  type ProjectSettingsProject,
  type ProjectSettingsSandbox,
  type ProjectSettingsSandboxStats,
  type ProjectSettingsSnapshot,
} from '../features/project-administration/projectSettingsClient';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopProjectSettingsLoadOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProjectAdministrationScope;
  signal?: AbortSignal;
}>;

export type DesktopProjectSettingsAuthorityOperationInputV2 =
  DesktopProjectSettingsLoadOperationInputV2 & Readonly<{ kind: 'load' }>;

export type PreparedDesktopProjectSettingsAuthorityOperationV2 =
  DesktopProjectSettingsAuthorityOperationInputV2;

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
  'project',
  'sandbox',
  'sandboxStats',
]);
const PROJECT_KEYS_V2 = new Set([
  'id',
  'tenantId',
  'name',
  'description',
  'ownerId',
  'isPublic',
  'memoryRules',
  'graphConfig',
  'sandboxType',
  'conversationMode',
  'createdAt',
  'updatedAt',
]);
const MEMORY_RULE_KEYS_V2 = new Set([
  'maxEpisodes',
  'retentionDays',
  'autoRefresh',
  'refreshInterval',
]);
const GRAPH_CONFIG_KEYS_V2 = new Set([
  'maxNodes',
  'maxEdges',
  'similarityThreshold',
  'communityDetection',
]);
const SANDBOX_KEYS_V2 = new Set(['id', 'status', 'healthy', 'createdAt']);
const SANDBOX_STATS_KEYS_V2 = new Set([
  'sandboxId',
  'status',
  'cpuPercent',
  'memoryUsage',
  'memoryLimit',
  'memoryPercent',
  'pids',
  'collectedAt',
]);
const ROLES_V2 = new Set<ProjectMembershipRole>(['owner', 'admin', 'member', 'viewer']);

export function prepareDesktopProjectSettingsAuthorityOperationV2(
  input: DesktopProjectSettingsAuthorityOperationInputV2,
): PreparedDesktopProjectSettingsAuthorityOperationV2 {
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
  const config = cloneDesktopProjectSettingsRuntimeConfigV2(input.config);
  const scope = cloneDesktopProjectSettingsScopeV2(input.scope, config);
  return Object.freeze({
    kind: 'load',
    config,
    scope,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

export function cloneDesktopProjectSettingsRuntimeConfigV2(
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

export function cloneDesktopProjectSettingsScopeV2(
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

export function requireDesktopProjectSettingsSnapshotV2(
  value: unknown,
  scope: ProjectAdministrationScope,
): ProjectSettingsSnapshot {
  if (
    scope.authority !== 'cloud' ||
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, SNAPSHOT_KEYS_V2) ||
    value.authority !== 'cloud' ||
    value.availability !== 'degraded' ||
    value.reasonCode !== PROJECT_SETTINGS_DEGRADED_REASON ||
    value.contractVersion !== '4.0.0' ||
    !exactActionsV2(value.allowedActions) ||
    !nonnegativeIntegerV2(value.scopeRevision) ||
    !sameScopeV2(value.scope, scope) ||
    !validRoleV2(value.membershipRole) ||
    !validProjectV2(value.project, scope) ||
    !validSandboxV2(value.sandbox) ||
    !validSandboxStatsV2(value.sandboxStats) ||
    !consistentSandboxV2(value.sandbox, value.sandboxStats)
  ) {
    throw invalidServiceContractV2();
  }
  try {
    return deepFreezeV2(structuredClone(value)) as ProjectSettingsSnapshot;
  } catch {
    throw invalidServiceContractV2();
  }
}

function validProjectV2(
  value: unknown,
  scope: ProjectAdministrationScope,
): value is ProjectSettingsProject {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, PROJECT_KEYS_V2) &&
    value.id === scope.projectId &&
    value.tenantId === scope.tenantId &&
    canonicalIdentifierV2(value.name) &&
    optionalTextV2(value.description) &&
    canonicalIdentifierV2(value.ownerId) &&
    typeof value.isPublic === 'boolean' &&
    validMemoryRulesV2(value.memoryRules) &&
    validGraphConfigV2(value.graphConfig) &&
    canonicalIdentifierV2(value.sandboxType) &&
    canonicalIdentifierV2(value.conversationMode) &&
    canonicalIdentifierV2(value.createdAt) &&
    optionalTextV2(value.updatedAt)
  );
}

function validMemoryRulesV2(value: unknown): boolean {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, MEMORY_RULE_KEYS_V2) &&
    nonnegativeIntegerV2(value.maxEpisodes) &&
    nonnegativeIntegerV2(value.retentionDays) &&
    typeof value.autoRefresh === 'boolean' &&
    nonnegativeIntegerV2(value.refreshInterval)
  );
}

function validGraphConfigV2(value: unknown): boolean {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, GRAPH_CONFIG_KEYS_V2) &&
    nonnegativeIntegerV2(value.maxNodes) &&
    nonnegativeIntegerV2(value.maxEdges) &&
    finiteNumberV2(value.similarityThreshold) &&
    typeof value.communityDetection === 'boolean'
  );
}

function validSandboxV2(value: unknown): value is ProjectSettingsSandbox | null {
  return (
    value === null ||
    (isPlainRecordV2(value) &&
      hasExactKeysV2(value, SANDBOX_KEYS_V2) &&
      canonicalIdentifierV2(value.id) &&
      canonicalIdentifierV2(value.status) &&
      typeof value.healthy === 'boolean' &&
      canonicalIdentifierV2(value.createdAt))
  );
}

function validSandboxStatsV2(value: unknown): value is ProjectSettingsSandboxStats | null {
  return (
    value === null ||
    (isPlainRecordV2(value) &&
      hasExactKeysV2(value, SANDBOX_STATS_KEYS_V2) &&
      canonicalIdentifierV2(value.sandboxId) &&
      canonicalIdentifierV2(value.status) &&
      finiteNumberV2(value.cpuPercent) &&
      finiteNumberV2(value.memoryUsage) &&
      finiteNumberV2(value.memoryLimit) &&
      finiteNumberV2(value.memoryPercent) &&
      nonnegativeIntegerV2(value.pids) &&
      canonicalIdentifierV2(value.collectedAt))
  );
}

function consistentSandboxV2(
  sandbox: ProjectSettingsSandbox | null,
  stats: ProjectSettingsSandboxStats | null,
): boolean {
  return stats === null || (sandbox !== null && stats.sandboxId === sandbox.id);
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

function finiteNumberV2(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function optionalTextV2(value: unknown): boolean {
  return value === null || typeof value === 'string';
}

function invalidInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_settings_operation_input_invalid',
    'desktop project settings operation input is invalid',
  );
}

function invalidServiceContractV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_settings_service_contract_invalid',
    'desktop project settings authority returned an invalid result',
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
