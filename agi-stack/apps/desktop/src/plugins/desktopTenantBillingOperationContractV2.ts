import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  TenantBillingPlan,
  TenantBillingSnapshot,
  TenantBillingTenant,
} from '../features/tenant-admin/tenantBillingClient';
import type { TenantAdminScope } from '../features/tenant-admin/tenantAdminHttp';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopTenantBillingLoadInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TenantAdminScope;
  signal?: AbortSignal;
}>;
export type DesktopTenantBillingUpgradeInputV2 = DesktopTenantBillingLoadInputV2 &
  Readonly<{ plan: TenantBillingPlan }>;

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
const PLANS = Object.freeze(['free', 'pro', 'enterprise']);

export function prepareTenantBillingLoadV2(
  input: DesktopTenantBillingLoadInputV2
): DesktopTenantBillingLoadInputV2 {
  return Object.freeze(common(input));
}
export function prepareTenantBillingUpgradeV2(
  input: DesktopTenantBillingUpgradeInputV2
): DesktopTenantBillingUpgradeInputV2 {
  const prepared = common(input);
  if (!PLANS.includes(input.plan)) throw invalidInput();
  return Object.freeze({ ...prepared, plan: input.plan });
}
export function freezeTenantBillingConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
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
export function requireTenantBillingSnapshotV2(
  value: unknown,
  scope: TenantAdminScope
): TenantBillingSnapshot {
  if (
    !record(value) ||
    !record(value.scope) ||
    !record(value.data) ||
    value.scope.authority !== scope.authority ||
    value.scope.tenantId !== scope.tenantId ||
    value.authority !== 'cloud' ||
    value.availability !== 'degraded' ||
    value.reasonCode !== 'tenant_billing_invoice_download_file_ipc_unavailable' ||
    value.contractVersion !== '4.0.0' ||
    !Array.isArray(value.allowedActions) ||
    !value.allowedActions.every((item) => typeof item === 'string') ||
    typeof value.data.membershipRole !== 'string' ||
    !record(value.data.usage) ||
    !Array.isArray(value.data.invoices) ||
    value.membershipRole !== value.data.membershipRole ||
    value.tenant !== value.data.tenant ||
    value.usage !== value.data.usage ||
    value.invoices !== value.data.invoices
  )
    throw invalidResponse();
  requireTenantBillingTenantV2(value.data.tenant, scope);
  for (const key of ['projects', 'memories', 'users', 'storage'])
    if (!nonnegative(value.data.usage[key])) throw invalidResponse();
  for (const invoice of value.data.invoices) requireInvoice(invoice);
  return value as unknown as TenantBillingSnapshot;
}
export function requireTenantBillingTenantV2(
  value: unknown,
  scope: TenantAdminScope
): TenantBillingTenant {
  if (
    !record(value) ||
    value.id !== scope.tenantId ||
    (value.name !== null && typeof value.name !== 'string') ||
    typeof value.plan !== 'string' ||
    !PLANS.includes(value.plan) ||
    !nonnegative(value.storageLimit)
  )
    throw invalidResponse();
  return value as unknown as TenantBillingTenant;
}
function requireInvoice(value: unknown): void {
  if (
    !record(value) ||
    typeof value.id !== 'string' ||
    typeof value.amount !== 'number' ||
    !Number.isFinite(value.amount) ||
    typeof value.currency !== 'string' ||
    typeof value.status !== 'string' ||
    typeof value.periodStart !== 'string' ||
    typeof value.periodEnd !== 'string' ||
    typeof value.createdAt !== 'string' ||
    (value.paidAt !== null && typeof value.paidAt !== 'string') ||
    (value.invoiceUrl !== null && typeof value.invoiceUrl !== 'string')
  )
    throw invalidResponse();
}
function common(input: DesktopTenantBillingLoadInputV2) {
  if (!record(input)) throw invalidInput();
  const config = freezeTenantBillingConfigV2(input.config);
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
    'desktop_tenant_billing_operation_input_invalid',
    'desktop tenant billing operation input invalid'
  );
}
function invalidResponse(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_billing_operation_response_invalid',
    'desktop tenant billing operation response invalid'
  );
}
