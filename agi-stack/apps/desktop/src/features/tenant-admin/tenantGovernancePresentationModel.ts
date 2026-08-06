import type { TenantAdminPresentationInput } from './tenantAdminController';
import type { TenantAdminScope } from './tenantAdminHttp';
import type {
  TenantGovernanceData,
  TenantInvitation,
  TenantMember,
} from './tenantGovernanceClient';

export type TenantGovernanceViewModel = Readonly<{
  state: TenantAdminPresentationInput<TenantAdminScope, TenantGovernanceData>['state'];
  scope: TenantAdminScope;
  reasonCode: string | null;
  retryVisible: boolean;
  busyAction: string | null;
  allowedActions: readonly string[];
  membershipRole: string | null;
  members: readonly TenantMember[];
  invitations: readonly TenantInvitation[];
  pendingInvitationTotal: number | null;
}>;

export function buildTenantGovernancePresentation(
  input: TenantAdminPresentationInput<TenantAdminScope, TenantGovernanceData>,
): TenantGovernanceViewModel {
  return Object.freeze({
    state: input.state,
    scope: input.scope,
    reasonCode: input.reasonCode,
    retryVisible: input.retryVisible,
    busyAction: input.busyAction,
    allowedActions: input.snapshot?.allowedActions ?? Object.freeze([]),
    membershipRole: input.snapshot?.data.membershipRole ?? null,
    members: input.snapshot?.data.members ?? Object.freeze([]),
    invitations: input.snapshot?.data.invitations ?? Object.freeze([]),
    pendingInvitationTotal: input.snapshot?.data.pendingInvitationTotal ?? null,
  });
}
