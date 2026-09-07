import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type { ProjectOverviewScope } from '../features/project/projectOverviewClient';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopProjectOverviewOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProjectOverviewScope;
  signal?: AbortSignal;
}>;

export type PreparedDesktopProjectOverviewOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProjectOverviewScope;
  signal?: AbortSignal;
}>;

const INPUT_KEYS_V2 = new Set(['config', 'scope', 'signal']);
const SCOPE_KEYS_V2 = new Set(['authority', 'tenantId', 'projectId']);

export function prepareDesktopProjectOverviewOperationV2(
  input: DesktopProjectOverviewOperationInputV2
): PreparedDesktopProjectOverviewOperationV2 {
  if (
    !isPlainRecordV2(input) ||
    !hasAllowedKeysV2(input, INPUT_KEYS_V2) ||
    !Object.hasOwn(input, 'config') ||
    !Object.hasOwn(input, 'scope') ||
    (input.signal !== undefined && !isAbortSignalV2(input.signal))
  ) {
    throw invalidOperationInputV2();
  }
  const config = cloneDesktopProjectOverviewRuntimeConfigV2(input.config);
  const scope = cloneDesktopProjectOverviewScopeV2(input.scope, config);
  return Object.freeze({
    config,
    scope,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

export function cloneDesktopProjectOverviewRuntimeConfigV2(
  config: DesktopRuntimeConfig
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
    !isCanonicalIdentifierV2(copy.tenantId) ||
    !isCanonicalIdentifierV2(copy.projectId)
  ) {
    throw invalidOperationInputV2();
  }
  return Object.freeze(copy);
}

export function cloneDesktopProjectOverviewScopeV2(
  scope: ProjectOverviewScope,
  config: DesktopRuntimeConfig
): ProjectOverviewScope {
  if (
    !isPlainRecordV2(scope) ||
    !hasExactKeysV2(scope, SCOPE_KEYS_V2) ||
    (scope.authority !== 'cloud' && scope.authority !== 'local') ||
    scope.authority !== config.mode ||
    !isCanonicalIdentifierV2(scope.tenantId) ||
    !isCanonicalIdentifierV2(scope.projectId) ||
    scope.tenantId !== config.tenantId ||
    scope.projectId !== config.projectId
  ) {
    throw invalidOperationInputV2();
  }
  return Object.freeze({
    authority: scope.authority,
    tenantId: scope.tenantId,
    projectId: scope.projectId,
  }) as ProjectOverviewScope;
}

function invalidOperationInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_overview_operation_input_invalid',
    'desktop project overview operation input is invalid'
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

function isCanonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isCanonicalIdentifierV2(value: unknown): value is string {
  return isCanonicalStringV2(value) && value.length <= 512;
}

function isAbortSignalV2(value: unknown): value is AbortSignal {
  return typeof AbortSignal !== 'undefined' && value instanceof AbortSignal;
}
