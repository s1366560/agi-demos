import type { TenantAdminPresentationInput } from './tenantAdminController';
import type { TenantAdminScope } from './tenantAdminHttp';
import type {
  TenantBillingData,
  TenantBillingTenant,
  TenantBillingUsage,
  TenantInvoice,
} from './tenantBillingClient';

export type TenantBillingViewModel = Readonly<{
  state: TenantAdminPresentationInput<TenantAdminScope, TenantBillingData>['state'];
  scope: TenantAdminScope;
  reasonCode: string | null;
  retryVisible: boolean;
  busyAction: string | null;
  allowedActions: readonly string[];
  membershipRole: string | null;
  tenant: TenantBillingTenant | null;
  usage: TenantBillingUsage | null;
  invoices: readonly TenantInvoice[];
}>;

export function buildTenantBillingPresentation(
  input: TenantAdminPresentationInput<TenantAdminScope, TenantBillingData>,
): TenantBillingViewModel {
  return Object.freeze({
    state: input.state,
    scope: input.scope,
    reasonCode: input.reasonCode,
    retryVisible: input.retryVisible,
    busyAction: input.busyAction,
    allowedActions: input.snapshot?.allowedActions ?? Object.freeze([]),
    membershipRole: input.snapshot?.data.membershipRole ?? null,
    tenant: input.snapshot?.data.tenant ?? null,
    usage: input.snapshot?.data.usage ?? null,
    invoices: input.snapshot?.data.invoices ?? Object.freeze([]),
  });
}
