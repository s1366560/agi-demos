import type { TenantAdminAuthoritySnapshot } from './tenantAdminController';
import type {
  TenantAdminRequestOptions,
  TenantAdminRole,
  TenantAdminScope,
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
    options?: TenantAdminRequestOptions
  ) => Promise<TenantBillingSnapshot>;
  upgradePlan: (
    scope: TenantAdminScope,
    plan: TenantBillingPlan,
    options?: TenantAdminRequestOptions
  ) => Promise<TenantBillingTenant>;
}>;
