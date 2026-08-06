import type { DesktopRuntimeConfig } from '../../types';
import type { TenantAdminAuthoritySnapshot } from './tenantAdminController';
import {
  isRecord,
  observeTenantMembership,
  optionalText,
  requestTenantAdminJson,
  requireCloudTenantScope,
  requireFiniteNumber,
  requireIdentifier,
  requireNonnegativeInteger,
  requireText,
  tenantAdminError,
  type TenantAdminRequestOptions,
  type TenantAdminRole,
  type TenantAdminScope,
} from './tenantAdminHttp';

export const TENANT_BILLING_ROUTE_ID = 'tenant-tenant-billing' as const;
export const TENANT_BILLING_LOCAL_REASON = 'cloud_billing_authority_not_applicable' as const;
export const TENANT_BILLING_FILE_REASON =
  'tenant_billing_invoice_download_file_ipc_unavailable' as const;

export type TenantBillingPlan = 'free' | 'pro' | 'enterprise';
export type TenantBillingTenant = Readonly<{
  id: string;
  name: string | null;
  plan: TenantBillingPlan;
  storageLimit: number;
}>;
export type TenantBillingUsage = Readonly<{
  projects: number;
  memories: number;
  users: number;
  storage: number;
}>;
export type TenantInvoice = Readonly<{
  id: string;
  amount: number;
  currency: string;
  status: string;
  periodStart: string;
  periodEnd: string;
  createdAt: string;
  paidAt: string | null;
  invoiceUrl: string | null;
}>;
export type TenantBillingData = Readonly<{
  membershipRole: TenantAdminRole;
  tenant: TenantBillingTenant;
  usage: TenantBillingUsage;
  invoices: readonly TenantInvoice[];
}>;
export type TenantBillingSnapshot = TenantAdminAuthoritySnapshot<
  TenantAdminScope,
  TenantBillingData
> &
  TenantBillingData;

export type TenantBillingClient = Readonly<{
  load: (
    scope: TenantAdminScope,
    options?: TenantAdminRequestOptions,
  ) => Promise<TenantBillingSnapshot>;
  upgradePlan: (
    scope: TenantAdminScope,
    plan: TenantBillingPlan,
    options?: TenantAdminRequestOptions,
  ) => Promise<TenantBillingTenant>;
}>;

const CONTRACT_VERSION = '4.0.0' as const;
const PLANS = new Set<TenantBillingPlan>(['free', 'pro', 'enterprise']);
const ADMIN_ACTIONS = Object.freeze(['view', 'inspect-usage', 'list-invoices']);
const OWNER_ACTIONS = Object.freeze([...ADMIN_ACTIONS, 'upgrade-plan']);

export function createTenantBillingClient(config: DesktopRuntimeConfig): TenantBillingClient {
  const runtimeConfig = Object.freeze({ ...config });
  return Object.freeze({
    async load(scope, options) {
      const currentScope = requireCloudTenantScope(
        runtimeConfig,
        scope,
        TENANT_BILLING_LOCAL_REASON,
      );
      const membershipRole = await observeTenantMembership(runtimeConfig, currentScope, options);
      requireBillingRole(membershipRole, false);
      const [billingPayload, invoicesPayload] = await Promise.all([
        requestTenantAdminJson(runtimeConfig, `${tenantPath(currentScope)}/billing`, options),
        requestTenantAdminJson(runtimeConfig, `${tenantPath(currentScope)}/invoices`, options),
      ]);
      const billing = parseBilling(billingPayload, currentScope.tenantId);
      const invoices = parseInvoices(invoicesPayload);
      const data = Object.freeze({
        membershipRole,
        tenant: billing.tenant,
        usage: billing.usage,
        invoices,
      });
      return Object.freeze({
        scope: currentScope,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: TENANT_BILLING_FILE_REASON,
        contractVersion: CONTRACT_VERSION,
        allowedActions: membershipRole === 'owner' ? OWNER_ACTIONS : ADMIN_ACTIONS,
        data,
        ...data,
      });
    },
    async upgradePlan(scope, plan, options) {
      const currentScope = requireCloudTenantScope(
        runtimeConfig,
        scope,
        TENANT_BILLING_LOCAL_REASON,
      );
      const membershipRole = await observeTenantMembership(runtimeConfig, currentScope, options);
      requireBillingRole(membershipRole, true);
      const payload = await requestTenantAdminJson(
        runtimeConfig,
        `${tenantPath(currentScope)}/upgrade`,
        { ...options, method: 'POST', body: { plan: requirePlan(plan) } },
      );
      if (!isRecord(payload)) throw tenantAdminError('tenant_billing_upgrade_contract_invalid');
      return parseTenant(payload.tenant, currentScope.tenantId);
    },
  });
}

function requireBillingRole(role: TenantAdminRole, ownerOnly: boolean): void {
  const allowed = ownerOnly ? role === 'owner' : role === 'owner' || role === 'admin';
  if (!allowed) throw tenantAdminError('tenant_billing_forbidden', 403);
}

function tenantPath(scope: TenantAdminScope): string {
  return `/api/v1/tenants/${encodeURIComponent(scope.tenantId)}`;
}

function parseBilling(
  payload: unknown,
  tenantId: string,
): Readonly<{ tenant: TenantBillingTenant; usage: TenantBillingUsage }> {
  if (!isRecord(payload) || !isRecord(payload.usage) || !Array.isArray(payload.invoices)) {
    throw tenantAdminError('tenant_billing_contract_invalid');
  }
  // The summary response also contains the latest invoices. Parse them even though
  // the complete invoice list is loaded from its dedicated authority below.
  payload.invoices.forEach(parseInvoice);
  return Object.freeze({
    tenant: parseTenant(payload.tenant, tenantId),
    usage: Object.freeze({
      projects: requireNonnegativeInteger(
        payload.usage.projects,
        'tenant_billing_contract_invalid',
      ),
      memories: requireNonnegativeInteger(
        payload.usage.memories,
        'tenant_billing_contract_invalid',
      ),
      users: requireNonnegativeInteger(payload.usage.users, 'tenant_billing_contract_invalid'),
      storage: requireNonnegativeInteger(payload.usage.storage, 'tenant_billing_contract_invalid'),
    }),
  });
}

function parseInvoices(payload: unknown): readonly TenantInvoice[] {
  if (!isRecord(payload) || !Array.isArray(payload.invoices)) {
    throw tenantAdminError('tenant_billing_invoices_contract_invalid');
  }
  return Object.freeze(payload.invoices.map(parseInvoice));
}

function parseTenant(value: unknown, tenantId: string): TenantBillingTenant {
  if (!isRecord(value)) throw tenantAdminError('tenant_billing_tenant_contract_invalid');
  const observedId = requireIdentifier(value.id, 'tenant_billing_tenant_contract_invalid');
  if (observedId !== tenantId) throw tenantAdminError('tenant_billing_scope_mismatch', 409);
  return Object.freeze({
    id: observedId,
    name: optionalText(value.name, 'tenant_billing_tenant_contract_invalid'),
    plan: requirePlan(value.plan),
    storageLimit: requireNonnegativeInteger(
      value.storage_limit,
      'tenant_billing_tenant_contract_invalid',
    ),
  });
}

function parseInvoice(value: unknown): TenantInvoice {
  if (!isRecord(value)) throw tenantAdminError('tenant_billing_invoice_contract_invalid');
  return Object.freeze({
    id: requireIdentifier(value.id, 'tenant_billing_invoice_contract_invalid'),
    amount: requireFiniteNumber(value.amount, 'tenant_billing_invoice_contract_invalid'),
    currency: requireText(value.currency, 'tenant_billing_invoice_contract_invalid'),
    status: requireText(value.status, 'tenant_billing_invoice_contract_invalid'),
    periodStart: requireText(value.period_start, 'tenant_billing_invoice_contract_invalid'),
    periodEnd: requireText(value.period_end, 'tenant_billing_invoice_contract_invalid'),
    createdAt: requireText(value.created_at, 'tenant_billing_invoice_contract_invalid'),
    paidAt: optionalText(value.paid_at, 'tenant_billing_invoice_contract_invalid'),
    invoiceUrl: optionalText(value.invoice_url, 'tenant_billing_invoice_contract_invalid'),
  });
}

function requirePlan(value: unknown): TenantBillingPlan {
  if (typeof value !== 'string' || !PLANS.has(value as TenantBillingPlan)) {
    throw tenantAdminError('tenant_billing_plan_invalid', 422);
  }
  return value as TenantBillingPlan;
}
