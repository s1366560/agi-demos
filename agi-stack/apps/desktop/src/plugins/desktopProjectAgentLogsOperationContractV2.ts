import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type { ProjectAgentLogsSnapshot } from '../features/project-agent/projectAgentLogsClient';
import type { ProjectAgentScope } from '../features/project-agent/projectAgentClient';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopProjectAgentLogsOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProjectAgentScope;
  status?: string;
  limit?: number;
  signal?: AbortSignal;
}>;

export type PreparedDesktopProjectAgentLogsOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProjectAgentScope;
  status?: string;
  limit: number;
  signal?: AbortSignal;
}>;

const INPUT_KEYS_V2 = new Set(['config', 'scope', 'status', 'limit', 'signal']);
const SCOPE_KEYS_V2 = new Set(['authority', 'tenantId', 'projectId']);
const SNAPSHOT_KEYS_V2 = new Set([
  'scope',
  'scopeRevision',
  'authority',
  'availability',
  'reasonCode',
  'allowedActions',
  'runs',
  'total',
]);
const RUN_KEYS_V2 = new Set(['id', 'title', 'detail', 'status', 'createdAt', 'summary']);
const DEFAULT_LIMIT_V2 = 100;
const MAX_LIMIT_V2 = 100;

export function prepareDesktopProjectAgentLogsOperationV2(
  input: DesktopProjectAgentLogsOperationInputV2
): PreparedDesktopProjectAgentLogsOperationV2 {
  if (
    !isPlainRecordV2(input) ||
    !hasAllowedKeysV2(input, INPUT_KEYS_V2) ||
    !Object.hasOwn(input, 'config') ||
    !Object.hasOwn(input, 'scope') ||
    (input.status !== undefined &&
      (!canonicalStringV2(input.status) || input.status.length > 512)) ||
    (input.limit !== undefined &&
      (!Number.isSafeInteger(input.limit) || input.limit < 1 || input.limit > MAX_LIMIT_V2)) ||
    (input.signal !== undefined && !isAbortSignalV2(input.signal))
  ) {
    throw invalidInputV2();
  }
  const config = cloneDesktopProjectAgentLogsRuntimeConfigV2(input.config);
  const scope = cloneDesktopProjectAgentLogsScopeV2(input.scope, config);
  return Object.freeze({
    config,
    scope,
    ...(input.status === undefined ? {} : { status: input.status }),
    limit: input.limit ?? DEFAULT_LIMIT_V2,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

export function cloneDesktopProjectAgentLogsRuntimeConfigV2(
  config: DesktopRuntimeConfig
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

export function cloneDesktopProjectAgentLogsScopeV2(
  scope: ProjectAgentScope,
  config: DesktopRuntimeConfig
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

export function requireDesktopProjectAgentLogsSnapshotV2(
  value: unknown,
  scope: ProjectAgentScope
): ProjectAgentLogsSnapshot {
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
    !Array.isArray(value.runs) ||
    value.runs.some((run) => !validRunV2(run)) ||
    !Number.isSafeInteger(value.total) ||
    Number(value.total) < value.runs.length
  ) {
    throw invalidServiceContractV2();
  }
  return deepFreezeV2(structuredClone(value)) as ProjectAgentLogsSnapshot;
}

function validRunV2(value: unknown): boolean {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, RUN_KEYS_V2) &&
    canonicalIdentifierV2(value.id) &&
    canonicalIdentifierV2(value.title) &&
    typeof value.detail === 'string' &&
    canonicalIdentifierV2(value.status) &&
    canonicalIdentifierV2(value.createdAt) &&
    (value.summary === null || typeof value.summary === 'string')
  );
}

function validAvailabilityReasonV2(availability: unknown, reasonCode: unknown): boolean {
  return availability === 'available' ? reasonCode === null : canonicalStringV2(reasonCode);
}

function invalidInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_agent_logs_operation_input_invalid',
    'desktop project agent logs operation input is invalid'
  );
}

function invalidServiceContractV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_agent_logs_service_contract_invalid',
    'desktop project agent logs authority returned an invalid result'
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
