import type { TenantAdminPresentationInput } from './tenantAdminController';
import type { TenantTrustData, TenantTrustPolicy, TenantTrustScope } from './tenantTrustClient';

export type TenantTrustViewModel = Readonly<{
  state: TenantAdminPresentationInput<TenantTrustScope, TenantTrustData>['state'];
  scope: TenantTrustScope;
  reasonCode: string | null;
  retryVisible: boolean;
  busyAction: string | null;
  allowedActions: readonly string[];
  membershipRole: string | null;
  policies: readonly TenantTrustPolicy[];
}>;

export function buildTenantTrustPresentation(
  input: TenantAdminPresentationInput<TenantTrustScope, TenantTrustData>,
): TenantTrustViewModel {
  return Object.freeze({
    state: input.state,
    scope: input.scope,
    reasonCode: input.reasonCode,
    retryVisible: input.retryVisible,
    busyAction: input.busyAction,
    allowedActions: input.snapshot?.allowedActions ?? Object.freeze([]),
    membershipRole: input.snapshot?.data.membershipRole ?? null,
    policies: input.snapshot?.data.policies ?? Object.freeze([]),
  });
}
