import type { TenantAdminRole } from './tenantAdminHttp';
import type {
  TenantManagementPresentationInput,
  TenantManagementViewState,
} from './tenantManagementController';
import type { TenantManagementScope } from './tenantManagementHttp';
import type {
  TenantAcpAgent,
  TenantAcpData,
  TenantAcpRunnerPool,
  TenantAcpStatus,
} from './tenantAcpClient';

export type TenantAcpViewModel = Readonly<{
  state: TenantManagementViewState;
  scope: TenantManagementScope;
  reasonCode: string | null;
  retryVisible: boolean;
  busyAction: string | null;
  allowedActions: readonly string[];
  membershipRole: TenantAdminRole | null;
  status: TenantAcpStatus | null;
  agents: readonly TenantAcpAgent[];
  runnerPools: readonly TenantAcpRunnerPool[];
}>;

export function buildTenantAcpPresentation(
  input: TenantManagementPresentationInput<TenantManagementScope, TenantAcpData>,
): TenantAcpViewModel {
  return Object.freeze({
    state: input.state,
    scope: input.scope,
    reasonCode: input.reasonCode,
    retryVisible: input.retryVisible,
    busyAction: input.busyAction,
    allowedActions: input.snapshot?.allowedActions ?? Object.freeze([]),
    membershipRole: input.snapshot?.data.membershipRole ?? null,
    status: input.snapshot?.data.status ?? null,
    agents: input.snapshot?.data.status.agents ?? Object.freeze([]),
    runnerPools: input.snapshot?.data.runnerPools ?? Object.freeze([]),
  });
}
