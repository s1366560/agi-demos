import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type { TenantPatternsSnapshot } from '../features/tenant-admin/tenantPatternsClient';
import type { TenantManagementScope } from '../features/tenant-admin/tenantManagementHttp';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopTenantPatternsLoadInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TenantManagementScope;
  signal?: AbortSignal;
}>;
export type DesktopTenantPatternsDeleteInputV2 = DesktopTenantPatternsLoadInputV2 &
  Readonly<{ patternId: string }>;

const CONFIG_KEYS = Object.freeze([
  'apiBaseUrl',
  'deviceAuthorizationBaseUrl',
  'apiKey',
  'localApiToken',
  'tenantId',
  'projectId',
  'workspaceId',
  'mode',
  'workspaceRoot',
]);

export function prepareTenantPatternsLoadV2(
  input: DesktopTenantPatternsLoadInputV2
): DesktopTenantPatternsLoadInputV2 {
  const common = prepareCommon(input);
  return Object.freeze(common);
}

export function prepareTenantPatternsDeleteV2(
  input: DesktopTenantPatternsDeleteInputV2
): DesktopTenantPatternsDeleteInputV2 {
  const common = prepareCommon(input);
  return Object.freeze({ ...common, patternId: identifier(input.patternId) });
}

export function freezeTenantPatternsConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  if (
    !record(config) ||
    Object.keys(config).length !== CONFIG_KEYS.length ||
    CONFIG_KEYS.some((key) => !Object.hasOwn(config, key)) ||
    (config.mode !== 'cloud' && config.mode !== 'local')
  )
    throw invalidInput();
  for (const key of CONFIG_KEYS) {
    if (key !== 'mode' && typeof config[key as keyof DesktopRuntimeConfig] !== 'string') {
      throw invalidInput();
    }
  }
  identifier(config.tenantId);
  return Object.freeze({ ...config });
}

export function requireTenantPatternsSnapshotV2(
  value: unknown,
  scope: TenantManagementScope
): TenantPatternsSnapshot {
  if (!record(value) || !record(value.scope) || !record(value.data)) throw invalidResponse();
  const data = value.data;
  if (
    value.scope.authority !== scope.authority ||
    value.scope.tenantId !== scope.tenantId ||
    value.authority !== scope.authority ||
    !nonnegative(value.scopeRevision) ||
    value.availability !== 'available' ||
    value.reasonCode !== null ||
    value.contractVersion !== '4.0.0' ||
    !Array.isArray(value.allowedActions) ||
    !value.allowedActions.every((action) => typeof action === 'string') ||
    typeof data.membershipRole !== 'string' ||
    !Array.isArray(data.patterns) ||
    !nonnegative(data.total) ||
    !nonnegative(data.page) ||
    !nonnegative(data.pageSize) ||
    value.membershipRole !== data.membershipRole ||
    value.patterns !== data.patterns ||
    value.total !== data.total ||
    value.page !== data.page ||
    value.pageSize !== data.pageSize
  )
    throw invalidResponse();
  return value as unknown as TenantPatternsSnapshot;
}

function prepareCommon(input: DesktopTenantPatternsLoadInputV2) {
  if (!record(input)) throw invalidInput();
  const config = freezeTenantPatternsConfigV2(input.config);
  if (
    !record(input.scope) ||
    Object.keys(input.scope).length !== 2 ||
    input.scope.authority !== config.mode ||
    identifier(input.scope.tenantId) !== config.tenantId
  )
    throw invalidInput();
  if (
    input.signal !== undefined &&
    (!record(input.signal) ||
      typeof input.signal.aborted !== 'boolean' ||
      typeof input.signal.addEventListener !== 'function')
  )
    throw invalidInput();
  return {
    config,
    scope: Object.freeze({ authority: input.scope.authority, tenantId: input.scope.tenantId }),
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  };
}
function identifier(value: unknown): string {
  if (typeof value !== 'string' || !value || value !== value.trim()) throw invalidInput();
  return value;
}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function nonnegative(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}
function invalidInput(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_patterns_operation_input_invalid',
    'desktop tenant patterns operation input invalid'
  );
}
function invalidResponse(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_patterns_operation_response_invalid',
    'desktop tenant patterns operation response invalid'
  );
}
