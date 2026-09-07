import type { TenantAdminRole } from './tenantAdminHttp';
import {
  type TenantManagementAuthoritySnapshot,
  type TenantManagementRequestOptions,
  type TenantManagementWorkspaceScope,
} from './tenantManagementHttp';

export const TENANT_DECISION_RECORDS_ROUTE_ID = 'tenant-tenant-decision-records' as const;
export const TENANT_DECISION_RECORDS_LOCAL_REASON =
  'cloud_tenant_decision_ledger_not_applicable' as const;

export type TenantDecisionOutcome = 'pending' | 'approved' | 'denied' | 'success' | 'rejected';
export type TenantApprovalDecision = 'allow_once' | 'allow_always' | 'deny';
export type TenantDecisionRecord = Readonly<{
  id: string;
  tenantId: string;
  workspaceId: string;
  agentInstanceId: string;
  decisionType: string;
  contextSummary: string | null;
  proposal: Readonly<Record<string, unknown>>;
  outcome: TenantDecisionOutcome;
  reviewerId: string | null;
  reviewType: string | null;
  reviewComment: string | null;
  resolvedAt: string | null;
  createdAt: string;
  updatedAt: string | null;
}>;
export type TenantDecisionFilters = Readonly<{
  agentId?: string;
  decisionType?: string;
}>;
export type TenantDecisionRecordsData = Readonly<{
  membershipRole: TenantAdminRole;
  records: readonly TenantDecisionRecord[];
}>;
export type TenantDecisionRecordsSnapshot = TenantManagementAuthoritySnapshot<
  TenantManagementWorkspaceScope,
  TenantDecisionRecordsData
> &
  TenantDecisionRecordsData;
export type TenantDecisionRecordsClient = Readonly<{
  load: (
    scope: TenantManagementWorkspaceScope,
    options?: TenantManagementRequestOptions & Readonly<{ filters?: TenantDecisionFilters }>,
  ) => Promise<TenantDecisionRecordsSnapshot>;
  resolveApproval: (
    scope: TenantManagementWorkspaceScope,
    recordId: string,
    decision: TenantApprovalDecision,
    options?: TenantManagementRequestOptions,
  ) => Promise<TenantDecisionRecord>;
}>;
