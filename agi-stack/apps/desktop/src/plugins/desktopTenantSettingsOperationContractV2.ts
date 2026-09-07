import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  TenantSettingsSnapshot,
  TenantSettingsTenant,
  TenantSettingsUpdate,
} from '../features/tenant-admin/tenantSettingsClient';
import type { TenantManagementScope } from '../features/tenant-admin/tenantManagementHttp';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopTenantSettingsLoadInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TenantManagementScope;
  signal?: AbortSignal;
}>;
export type DesktopTenantSettingsUpdateInputV2 = DesktopTenantSettingsLoadInputV2 &
  Readonly<{ update: TenantSettingsUpdate }>;

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
const UPDATE_KEYS = Object.freeze([
  'name',
  'description',
  'plan',
  'maxProjects',
  'maxUsers',
  'maxStorage',
]);

export function prepareTenantSettingsLoadV2(
  input: DesktopTenantSettingsLoadInputV2
): DesktopTenantSettingsLoadInputV2 {
  return Object.freeze(prepareCommon(input));
}
export function prepareTenantSettingsUpdateV2(
  input: DesktopTenantSettingsUpdateInputV2
): DesktopTenantSettingsUpdateInputV2 {
  const common = prepareCommon(input);
  if (
    !record(input.update) ||
    Object.keys(input.update).length === 0 ||
    Object.keys(input.update).some((key) => !UPDATE_KEYS.includes(key))
  )
    throw invalidInput();
  const update: Record<string, string | number | null> = {};
  if (input.update.name !== undefined) update.name = identifier(input.update.name);
  if (input.update.description !== undefined) {
    if (input.update.description !== null && typeof input.update.description !== 'string')
      throw invalidInput();
    update.description = input.update.description;
  }
  if (input.update.plan !== undefined) update.plan = identifier(input.update.plan);
  for (const key of ['maxProjects', 'maxUsers', 'maxStorage'] as const) {
    const value = input.update[key];
    if (value !== undefined) {
      if (!nonnegative(value)) throw invalidInput();
      update[key] = value;
    }
  }
  return Object.freeze({ ...common, update: Object.freeze(update) });
}
export function freezeTenantSettingsConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  if (
    !record(config) ||
    Object.keys(config).length !== CONFIG_KEYS.length ||
    CONFIG_KEYS.some((key) => !Object.hasOwn(config, key)) ||
    (config.mode !== 'cloud' && config.mode !== 'local')
  )
    throw invalidInput();
  for (const key of CONFIG_KEYS)
    if (key !== 'mode' && typeof config[key as keyof DesktopRuntimeConfig] !== 'string')
      throw invalidInput();
  identifier(config.tenantId);
  return Object.freeze({ ...config });
}
export function requireTenantSettingsSnapshotV2(
  value: unknown,
  scope: TenantManagementScope
): TenantSettingsSnapshot {
  if (
    !record(value) ||
    !record(value.scope) ||
    !record(value.data) ||
    value.scope.authority !== scope.authority ||
    value.scope.tenantId !== scope.tenantId ||
    value.authority !== scope.authority ||
    !nonnegative(value.scopeRevision) ||
    value.availability !== 'available' ||
    value.reasonCode !== null ||
    value.contractVersion !== '4.0.0' ||
    !Array.isArray(value.allowedActions) ||
    !value.allowedActions.every((item) => typeof item === 'string') ||
    typeof value.data.membershipRole !== 'string' ||
    !record(value.data.stats) ||
    value.membershipRole !== value.data.membershipRole ||
    value.tenant !== value.data.tenant ||
    value.stats !== value.data.stats
  )
    throw invalidResponse();
  requireTenantSettingsTenantV2(value.data.tenant, scope);
  return value as unknown as TenantSettingsSnapshot;
}
export function requireTenantSettingsTenantV2(
  value: unknown,
  scope: TenantManagementScope
): TenantSettingsTenant {
  if (
    !record(value) ||
    value.id !== scope.tenantId ||
    typeof value.name !== 'string' ||
    typeof value.slug !== 'string' ||
    typeof value.ownerId !== 'string' ||
    typeof value.plan !== 'string' ||
    !nonnegative(value.maxProjects) ||
    !nonnegative(value.maxUsers) ||
    !nonnegative(value.maxStorage) ||
    typeof value.createdAt !== 'string'
  )
    throw invalidResponse();
  return value as unknown as TenantSettingsTenant;
}
function prepareCommon(input: DesktopTenantSettingsLoadInputV2) {
  if (!record(input)) throw invalidInput();
  const config = freezeTenantSettingsConfigV2(input.config);
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
    'desktop_tenant_settings_operation_input_invalid',
    'desktop tenant settings operation input invalid'
  );
}
function invalidResponse(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_settings_operation_response_invalid',
    'desktop tenant settings operation response invalid'
  );
}
