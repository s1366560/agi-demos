import type { TenantAdminRole } from './tenantAdminHttp';
import type {
  TenantManagementPresentationInput,
  TenantManagementViewState,
} from './tenantManagementController';
import type { TenantManagementWorkspaceScope } from './tenantManagementHttp';
import type {
  TenantDecisionRecord,
  TenantDecisionRecordsData,
} from './tenantDecisionRecordsClient';

export type TenantDecisionRecordsViewModel = Readonly<{
  state: TenantManagementViewState;
  scope: TenantManagementWorkspaceScope;
  reasonCode: string | null;
  retryVisible: boolean;
  busyAction: string | null;
  allowedActions: readonly string[];
  membershipRole: TenantAdminRole | null;
  records: readonly TenantDecisionRecord[];
}>;

export function buildTenantDecisionRecordsPresentation(
  input: TenantManagementPresentationInput<
    TenantManagementWorkspaceScope,
    TenantDecisionRecordsData
  >,
): TenantDecisionRecordsViewModel {
  return Object.freeze({
    state: input.state,
    scope: input.scope,
    reasonCode: input.reasonCode,
    retryVisible: input.retryVisible,
    busyAction: input.busyAction,
    allowedActions: input.snapshot?.allowedActions ?? Object.freeze([]),
    membershipRole: input.snapshot?.data.membershipRole ?? null,
    records: input.snapshot?.data.records ?? Object.freeze([]),
  });
}
