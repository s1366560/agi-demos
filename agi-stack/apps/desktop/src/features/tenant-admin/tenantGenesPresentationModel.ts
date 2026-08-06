import type { TenantAdminRole } from './tenantAdminHttp';
import type {
  TenantManagementPresentationInput,
  TenantManagementViewState,
} from './tenantManagementController';
import type { TenantManagementScope } from './tenantManagementHttp';
import type { TenantGene, TenantGenesData } from './tenantGenesClient';

export type TenantGenesViewModel = Readonly<{
  state: TenantManagementViewState;
  scope: TenantManagementScope;
  reasonCode: string | null;
  retryVisible: boolean;
  busyAction: string | null;
  allowedActions: readonly string[];
  membershipRole: TenantAdminRole | null;
  genes: readonly TenantGene[];
  total: number;
  page: number;
  pageSize: number;
}>;

export function buildTenantGenesPresentation(
  input: TenantManagementPresentationInput<TenantManagementScope, TenantGenesData>,
): TenantGenesViewModel {
  return Object.freeze({
    state: input.state,
    scope: input.scope,
    reasonCode: input.reasonCode,
    retryVisible: input.retryVisible,
    busyAction: input.busyAction,
    allowedActions: input.snapshot?.allowedActions ?? Object.freeze([]),
    membershipRole: input.snapshot?.data.membershipRole ?? null,
    genes: input.snapshot?.data.genes ?? Object.freeze([]),
    total: input.snapshot?.data.total ?? 0,
    page: input.snapshot?.data.page ?? 1,
    pageSize: input.snapshot?.data.pageSize ?? 20,
  });
}
