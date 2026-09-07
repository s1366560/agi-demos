import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type { ProjectAgentScope } from '../features/project-agent/projectAgentClient';
import type {
  ProjectAgentPattern,
  ProjectAgentPatternsSnapshot,
} from '../features/project-agent/projectAgentPatternsClient';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopProjectAgentPatternsOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProjectAgentScope;
  signal?: AbortSignal;
}>;

export type PreparedDesktopProjectAgentPatternsOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProjectAgentScope;
  signal?: AbortSignal;
}>;

const INPUT_KEYS_V2 = new Set(['config', 'scope', 'signal']);
const SCOPE_KEYS_V2 = new Set(['authority', 'tenantId', 'projectId']);
const SNAPSHOT_KEYS_V2 = new Set([
  'scope',
  'scopeRevision',
  'authority',
  'availability',
  'reasonCode',
  'allowedActions',
  'scopeKind',
  'patterns',
  'total',
]);
const PATTERN_KEYS_V2 = new Set([
  'id',
  'tenantId',
  'name',
  'description',
  'successRate',
  'usageCount',
  'createdAt',
]);

export function prepareDesktopProjectAgentPatternsOperationV2(
  input: DesktopProjectAgentPatternsOperationInputV2,
): PreparedDesktopProjectAgentPatternsOperationV2 {
  if (
    !isPlainRecordV2(input) ||
    !hasAllowedKeysV2(input, INPUT_KEYS_V2) ||
    !Object.hasOwn(input, 'config') ||
    !Object.hasOwn(input, 'scope') ||
    (input.signal !== undefined && !isAbortSignalV2(input.signal))
  ) {
    throw invalidInputV2();
  }
  const config = cloneDesktopProjectAgentPatternsRuntimeConfigV2(input.config);
  const scope = cloneDesktopProjectAgentPatternsScopeV2(input.scope, config);
  return Object.freeze({
    config,
    scope,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

export function cloneDesktopProjectAgentPatternsRuntimeConfigV2(
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

export function cloneDesktopProjectAgentPatternsScopeV2(
  scope: ProjectAgentScope,
  config: DesktopRuntimeConfig,
): ProjectAgentScope {
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

export function requireDesktopProjectAgentPatternsSnapshotV2(
  value: unknown,
  scope: ProjectAgentScope,
): ProjectAgentPatternsSnapshot {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, SNAPSHOT_KEYS_V2) ||
    value.authority !== scope.authority ||
    (value.availability !== 'available' && value.availability !== 'degraded') ||
    !validAvailabilityReasonV2(value.availability, value.reasonCode) ||
    !Number.isSafeInteger(value.scopeRevision) ||
    Number(value.scopeRevision) < 0 ||
    !isPlainRecordV2(value.scope) ||
    !hasExactKeysV2(value.scope, SCOPE_KEYS_V2) ||
    value.scope.authority !== scope.authority ||
    value.scope.tenantId !== scope.tenantId ||
    value.scope.projectId !== scope.projectId ||
    !Array.isArray(value.allowedActions) ||
    new Set(value.allowedActions).size !== value.allowedActions.length ||
    value.allowedActions.some((action) => !canonicalStringV2(action)) ||
    value.scopeKind !== 'tenant_shared' ||
    !Array.isArray(value.patterns) ||
    value.patterns.some((pattern) => !validPatternV2(pattern, scope.tenantId)) ||
    !Number.isSafeInteger(value.total) ||
    Number(value.total) < value.patterns.length
  ) {
    throw invalidServiceContractV2();
  }
  return deepFreezeV2(structuredClone(value)) as ProjectAgentPatternsSnapshot;
}

function validPatternV2(value: unknown, tenantId: string): value is ProjectAgentPattern {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, PATTERN_KEYS_V2) &&
    canonicalIdentifierV2(value.id) &&
    value.tenantId === tenantId &&
    canonicalIdentifierV2(value.name) &&
    typeof value.description === 'string' &&
    typeof value.successRate === 'number' &&
    Number.isFinite(value.successRate) &&
    value.successRate >= 0 &&
    value.successRate <= 1 &&
    Number.isSafeInteger(value.usageCount) &&
    Number(value.usageCount) >= 0 &&
    canonicalIdentifierV2(value.createdAt)
  );
}

function validAvailabilityReasonV2(availability: unknown, reasonCode: unknown): boolean {
  return availability === 'available' ? reasonCode === null : canonicalStringV2(reasonCode);
}

function invalidInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_agent_patterns_operation_input_invalid',
    'desktop project agent patterns operation input is invalid',
  );
}

function invalidServiceContractV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_agent_patterns_service_contract_invalid',
    'desktop project agent patterns authority returned an invalid result',
  );
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
