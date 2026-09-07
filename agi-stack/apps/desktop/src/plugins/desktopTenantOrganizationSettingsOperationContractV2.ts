import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  TenantGenePolicy,
  TenantGenePolicyInput,
  TenantOrganizationSettingsSnapshot,
  TenantRegistry,
  TenantRegistryInput,
  TenantSmtpConfig,
  TenantSmtpInput,
} from '../features/tenant-admin/tenantOrganizationSettingsClient';
import type { TenantManagementScope } from '../features/tenant-admin/tenantManagementHttp';
import type { TenantSettingsTenant } from '../features/tenant-admin/tenantSettingsClient';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopTenantOrganizationSettingsLoadInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TenantManagementScope;
  signal?: AbortSignal;
}>;
export type DesktopTenantOrganizationSettingsRegistryInputV2 =
  DesktopTenantOrganizationSettingsLoadInputV2 & Readonly<{ input: TenantRegistryInput }>;
export type DesktopTenantOrganizationSettingsRegistryIdInputV2 =
  DesktopTenantOrganizationSettingsLoadInputV2 & Readonly<{ registryId: string }>;
export type DesktopTenantOrganizationSettingsSmtpInputV2 =
  DesktopTenantOrganizationSettingsLoadInputV2 & Readonly<{ input: TenantSmtpInput }>;
export type DesktopTenantOrganizationSettingsSmtpTestInputV2 =
  DesktopTenantOrganizationSettingsLoadInputV2 & Readonly<{ recipientEmail: string }>;
export type DesktopTenantOrganizationSettingsGenePolicyInputV2 =
  DesktopTenantOrganizationSettingsLoadInputV2 & Readonly<{ input: TenantGenePolicyInput }>;
export type DesktopTenantOrganizationSettingsPolicyKeyInputV2 =
  DesktopTenantOrganizationSettingsLoadInputV2 & Readonly<{ policyKey: string }>;

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
const COMMON_KEYS = Object.freeze(['config', 'scope', 'signal']);
const REGISTRY_KEYS = Object.freeze([
  'id',
  'name',
  'registryType',
  'url',
  'username',
  'password',
  'isDefault',
]);
const SMTP_KEYS = Object.freeze([
  'smtpHost',
  'smtpPort',
  'smtpUsername',
  'smtpPassword',
  'fromEmail',
  'fromName',
  'useTls',
]);
const GENE_POLICY_KEYS = Object.freeze(['policyKey', 'policyValue', 'description']);
const MEMBER_ACTIONS = Object.freeze(['view', 'inspect-stats', 'inspect-smtp']);
const ADMIN_ACTIONS = Object.freeze([
  ...MEMBER_ACTIONS,
  'manage-registries',
  'update-smtp',
  'delete-smtp',
  'test-smtp',
  'manage-gene-policies',
]);
const TENANT_ROLES = new Set(['owner', 'admin', 'member', 'editor', 'viewer']);

export function prepareTenantOrganizationSettingsLoadV2(
  input: DesktopTenantOrganizationSettingsLoadInputV2,
): DesktopTenantOrganizationSettingsLoadInputV2 {
  return Object.freeze(prepareCommon(input, COMMON_KEYS));
}

export function prepareTenantOrganizationSettingsRegistryV2(
  input: DesktopTenantOrganizationSettingsRegistryInputV2,
): DesktopTenantOrganizationSettingsRegistryInputV2 {
  const common = prepareCommon(input, [...COMMON_KEYS, 'input']);
  if (!record(input.input) || !exactKeys(input.input, ['name', 'registryType', 'url'], REGISTRY_KEYS)) {
    throw invalidInput();
  }
  const prepared: TenantRegistryInput = Object.freeze({
    ...(input.input.id === undefined ? {} : { id: identifier(input.input.id) }),
    name: identifier(input.input.name),
    registryType: identifier(input.input.registryType),
    url: identifier(input.input.url),
    ...(input.input.username === undefined
      ? {}
      : { username: nullableString(input.input.username) }),
    ...(input.input.password === undefined
      ? {}
      : { password: nullableString(input.input.password) }),
    ...(input.input.isDefault === undefined
      ? {}
      : { isDefault: boolean(input.input.isDefault) }),
  });
  return Object.freeze({ ...common, input: prepared });
}

export function prepareTenantOrganizationSettingsRegistryIdV2(
  input: DesktopTenantOrganizationSettingsRegistryIdInputV2,
): DesktopTenantOrganizationSettingsRegistryIdInputV2 {
  const common = prepareCommon(input, [...COMMON_KEYS, 'registryId']);
  return Object.freeze({ ...common, registryId: identifier(input.registryId) });
}

export function prepareTenantOrganizationSettingsSmtpV2(
  input: DesktopTenantOrganizationSettingsSmtpInputV2,
): DesktopTenantOrganizationSettingsSmtpInputV2 {
  const common = prepareCommon(input, [...COMMON_KEYS, 'input']);
  if (
    !record(input.input) ||
    !exactKeys(
      input.input,
      ['smtpHost', 'smtpPort', 'smtpUsername', 'smtpPassword', 'fromEmail'],
      SMTP_KEYS,
    )
  ) {
    throw invalidInput();
  }
  const prepared: TenantSmtpInput = Object.freeze({
    smtpHost: identifier(input.input.smtpHost),
    smtpPort: positivePort(input.input.smtpPort),
    smtpUsername: identifier(input.input.smtpUsername),
    smtpPassword: identifier(input.input.smtpPassword),
    fromEmail: identifier(input.input.fromEmail),
    ...(input.input.fromName === undefined
      ? {}
      : { fromName: nullableString(input.input.fromName) }),
    ...(input.input.useTls === undefined ? {} : { useTls: boolean(input.input.useTls) }),
  });
  return Object.freeze({ ...common, input: prepared });
}

export function prepareTenantOrganizationSettingsSmtpTestV2(
  input: DesktopTenantOrganizationSettingsSmtpTestInputV2,
): DesktopTenantOrganizationSettingsSmtpTestInputV2 {
  const common = prepareCommon(input, [...COMMON_KEYS, 'recipientEmail']);
  return Object.freeze({ ...common, recipientEmail: identifier(input.recipientEmail) });
}

export function prepareTenantOrganizationSettingsGenePolicyV2(
  input: DesktopTenantOrganizationSettingsGenePolicyInputV2,
): DesktopTenantOrganizationSettingsGenePolicyInputV2 {
  const common = prepareCommon(input, [...COMMON_KEYS, 'input']);
  if (
    !record(input.input) ||
    !exactKeys(input.input, ['policyKey', 'policyValue'], GENE_POLICY_KEYS) ||
    !record(input.input.policyValue)
  ) {
    throw invalidInput();
  }
  const prepared: TenantGenePolicyInput = Object.freeze({
    policyKey: identifier(input.input.policyKey),
    policyValue: freezeJsonRecord(input.input.policyValue),
    ...(input.input.description === undefined
      ? {}
      : { description: nullableString(input.input.description) }),
  });
  return Object.freeze({ ...common, input: prepared });
}

export function prepareTenantOrganizationSettingsPolicyKeyV2(
  input: DesktopTenantOrganizationSettingsPolicyKeyInputV2,
): DesktopTenantOrganizationSettingsPolicyKeyInputV2 {
  const common = prepareCommon(input, [...COMMON_KEYS, 'policyKey']);
  return Object.freeze({ ...common, policyKey: identifier(input.policyKey) });
}

export function freezeTenantOrganizationSettingsConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (
    !record(config) ||
    Object.keys(config).length !== CONFIG_KEYS.length ||
    CONFIG_KEYS.some((key) => !Object.hasOwn(config, key)) ||
    (config.mode !== 'cloud' && config.mode !== 'local')
  ) {
    throw invalidInput();
  }
  for (const key of CONFIG_KEYS) {
    if (key !== 'mode' && typeof config[key as keyof DesktopRuntimeConfig] !== 'string') {
      throw invalidInput();
    }
  }
  identifier(config.tenantId);
  return Object.freeze({ ...config });
}

export function requireTenantOrganizationSettingsSnapshotV2(
  value: unknown,
  scope: TenantManagementScope,
): TenantOrganizationSettingsSnapshot {
  if (
    !record(value) ||
    !record(value.scope) ||
    !record(value.data) ||
    value.scope.authority !== scope.authority ||
    value.scope.tenantId !== scope.tenantId ||
    value.authority !== (scope.authority === 'cloud' ? 'cloud' : 'sidecar') ||
    !nonnegativeInteger(value.scopeRevision) ||
    value.availability !== 'available' ||
    value.reasonCode !== null ||
    value.contractVersion !== '4.0.0' ||
    !TENANT_ROLES.has(value.data.membershipRole as string) ||
    value.membershipRole !== value.data.membershipRole ||
    value.tenant !== value.data.tenant ||
    value.stats !== value.data.stats ||
    value.registries !== value.data.registries ||
    value.smtp !== value.data.smtp ||
    value.genePolicies !== value.data.genePolicies ||
    !record(value.data.stats) ||
    !Array.isArray(value.data.registries) ||
    !Array.isArray(value.data.genePolicies)
  ) {
    throw invalidResponse();
  }
  const expectedActions =
    value.data.membershipRole === 'owner' || value.data.membershipRole === 'admin'
      ? ADMIN_ACTIONS
      : MEMBER_ACTIONS;
  if (!sameStrings(value.allowedActions, expectedActions)) throw invalidResponse();
  requireTenant(value.data.tenant, scope);
  value.data.registries.forEach((item) => requireTenantOrganizationSettingsRegistryV2(item, scope));
  if (value.data.smtp !== null) requireTenantOrganizationSettingsSmtpConfigV2(value.data.smtp, scope);
  value.data.genePolicies.forEach((item) =>
    requireTenantOrganizationSettingsGenePolicyV2(item, scope),
  );
  return value as unknown as TenantOrganizationSettingsSnapshot;
}

export function requireTenantOrganizationSettingsRegistryV2(
  value: unknown,
  scope: TenantManagementScope,
): TenantRegistry {
  if (
    !record(value) ||
    identifierResponse(value.id) === null ||
    value.tenantId !== scope.tenantId ||
    typeof value.name !== 'string' ||
    typeof value.type !== 'string' ||
    typeof value.url !== 'string' ||
    !optionalStringResponse(value.username) ||
    typeof value.isDefault !== 'boolean' ||
    typeof value.status !== 'string' ||
    !optionalStringResponse(value.lastChecked) ||
    typeof value.createdAt !== 'string' ||
    !optionalStringResponse(value.updatedAt)
  ) {
    throw invalidResponse();
  }
  return value as unknown as TenantRegistry;
}

export function requireTenantOrganizationSettingsSmtpConfigV2(
  value: unknown,
  scope: TenantManagementScope,
): TenantSmtpConfig {
  if (
    !record(value) ||
    identifierResponse(value.id) === null ||
    value.tenantId !== scope.tenantId ||
    typeof value.smtpHost !== 'string' ||
    !nonnegativeInteger(value.smtpPort) ||
    typeof value.smtpUsername !== 'string' ||
    typeof value.smtpPasswordMasked !== 'string' ||
    typeof value.fromEmail !== 'string' ||
    !optionalStringResponse(value.fromName) ||
    typeof value.useTls !== 'boolean'
  ) {
    throw invalidResponse();
  }
  return value as unknown as TenantSmtpConfig;
}

export function requireTenantOrganizationSettingsGenePolicyV2(
  value: unknown,
  scope: TenantManagementScope,
): TenantGenePolicy {
  if (
    !record(value) ||
    identifierResponse(value.id) === null ||
    value.tenantId !== scope.tenantId ||
    identifierResponse(value.policyKey) === null ||
    !record(value.policyValue) ||
    !optionalStringResponse(value.description) ||
    typeof value.createdAt !== 'string' ||
    !optionalStringResponse(value.updatedAt)
  ) {
    throw invalidResponse();
  }
  validateJson(value.policyValue, new WeakSet<object>());
  return value as unknown as TenantGenePolicy;
}

export function requireTenantOrganizationSettingsTestResultV2(
  value: unknown,
): Readonly<Record<string, unknown>> {
  if (!record(value)) throw invalidResponse();
  try {
    return freezeJsonRecord(value);
  } catch {
    throw invalidResponse();
  }
}

function prepareCommon(
  input: DesktopTenantOrganizationSettingsLoadInputV2,
  allowedKeys: readonly string[],
): DesktopTenantOrganizationSettingsLoadInputV2 {
  if (!record(input) || !exactKeys(input, ['config', 'scope'], allowedKeys)) throw invalidInput();
  const config = freezeTenantOrganizationSettingsConfigV2(input.config);
  if (
    !record(input.scope) ||
    !exactKeys(input.scope, ['authority', 'tenantId'], ['authority', 'tenantId']) ||
    input.scope.authority !== config.mode ||
    identifier(input.scope.tenantId) !== config.tenantId
  ) {
    throw invalidInput();
  }
  if (input.signal !== undefined && !abortSignal(input.signal)) throw invalidInput();
  return {
    config,
    scope: Object.freeze({ authority: input.scope.authority, tenantId: input.scope.tenantId }),
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  };
}

function requireTenant(value: unknown, scope: TenantManagementScope): TenantSettingsTenant {
  if (
    !record(value) ||
    value.id !== scope.tenantId ||
    typeof value.name !== 'string' ||
    typeof value.slug !== 'string' ||
    !optionalStringResponse(value.description) ||
    identifierResponse(value.ownerId) === null ||
    typeof value.plan !== 'string' ||
    !nonnegativeInteger(value.maxProjects) ||
    !nonnegativeInteger(value.maxUsers) ||
    !nonnegativeInteger(value.maxStorage) ||
    typeof value.createdAt !== 'string' ||
    !optionalStringResponse(value.updatedAt)
  ) {
    throw invalidResponse();
  }
  return value as unknown as TenantSettingsTenant;
}

function freezeJsonRecord(value: Record<string, unknown>): Readonly<Record<string, unknown>> {
  return freezeJson(value, new WeakSet<object>()) as Readonly<Record<string, unknown>>;
}

function freezeJson(value: unknown, ancestors: WeakSet<object>): unknown {
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'boolean' ||
    (typeof value === 'number' && Number.isFinite(value))
  ) {
    return value;
  }
  if (typeof value !== 'object' || ancestors.has(value)) throw invalidInput();
  ancestors.add(value);
  try {
    if (Array.isArray(value)) {
      return Object.freeze(value.map((item) => freezeJson(item, ancestors)));
    }
    if (!record(value)) throw invalidInput();
    const clone: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value)) clone[key] = freezeJson(item, ancestors);
    return Object.freeze(clone);
  } finally {
    ancestors.delete(value);
  }
}

function validateJson(value: unknown, ancestors: WeakSet<object>): void {
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'boolean' ||
    (typeof value === 'number' && Number.isFinite(value))
  ) {
    return;
  }
  if (typeof value !== 'object' || ancestors.has(value)) throw invalidResponse();
  ancestors.add(value);
  try {
    if (Array.isArray(value)) {
      value.forEach((item) => validateJson(item, ancestors));
      return;
    }
    if (!record(value)) throw invalidResponse();
    Object.values(value).forEach((item) => validateJson(item, ancestors));
  } finally {
    ancestors.delete(value);
  }
}

function exactKeys(
  value: Record<string, unknown>,
  required: readonly string[],
  allowed: readonly string[],
): boolean {
  return (
    required.every((key) => Object.hasOwn(value, key)) &&
    Object.keys(value).every((key) => allowed.includes(key))
  );
}

function identifier(value: unknown): string {
  if (typeof value !== 'string' || !value || value !== value.trim()) throw invalidInput();
  return value;
}

function identifierResponse(value: unknown): string | null {
  return typeof value === 'string' && value && value === value.trim() ? value : null;
}

function nullableString(value: unknown): string | null {
  if (value === null || typeof value === 'string') return value;
  throw invalidInput();
}

function optionalStringResponse(value: unknown): boolean {
  return value === null || typeof value === 'string';
}

function boolean(value: unknown): boolean {
  if (typeof value !== 'boolean') throw invalidInput();
  return value;
}

function positivePort(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 1 || value > 65_535) {
    throw invalidInput();
  }
  return value;
}

function nonnegativeInteger(value: unknown): boolean {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

function abortSignal(value: unknown): value is AbortSignal {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as AbortSignal).aborted === 'boolean' &&
    typeof (value as AbortSignal).addEventListener === 'function'
  );
}

function sameStrings(value: unknown, expected: readonly string[]): boolean {
  return (
    Array.isArray(value) &&
    value.length === expected.length &&
    value.every((item, index) => item === expected[index])
  );
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function invalidInput(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_organization_settings_operation_input_invalid',
    'desktop tenant organization settings operation input invalid',
  );
}

function invalidResponse(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_organization_settings_operation_response_invalid',
    'desktop tenant organization settings operation response invalid',
  );
}
