import type { TenantAdminRole } from './tenantAdminHttp';
import type {
  TenantManagementPresentationInput,
  TenantManagementViewState,
} from './tenantManagementController';
import type { TenantManagementScope } from './tenantManagementHttp';
import type { TenantPatternsData, TenantWorkflowPattern } from './tenantPatternsClient';

export type TenantPatternsViewModel = Readonly<{
  state: TenantManagementViewState;
  scope: TenantManagementScope;
  reasonCode: string | null;
  retryVisible: boolean;
  busyAction: string | null;
  allowedActions: readonly string[];
  membershipRole: TenantAdminRole | null;
  patterns: readonly TenantWorkflowPattern[];
  total: number;
}>;

export function buildTenantPatternsPresentation(
  input: TenantManagementPresentationInput<TenantManagementScope, TenantPatternsData>,
): TenantPatternsViewModel {
  return Object.freeze({
    state: input.state,
    scope: input.scope,
    reasonCode: input.reasonCode,
    retryVisible: input.retryVisible,
    busyAction: input.busyAction,
    allowedActions: input.snapshot?.allowedActions ?? Object.freeze([]),
    membershipRole: input.snapshot?.data.membershipRole ?? null,
    patterns: input.snapshot?.data.patterns ?? Object.freeze([]),
    total: input.snapshot?.data.total ?? 0,
  });
}
