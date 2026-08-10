import type { DesktopRuntimeConfig } from '../../types';
import {
  optionalText,
  requireIdentifier,
  requireText,
  tenantAdminError,
  type TenantAdminRole,
} from './tenantAdminHttp';
import {
  authorityFor,
  isRecord,
  observeTenantManagementRole,
  requestTenantManagementJson,
  requireRecord,
  requireRole,
  requireTenantManagementScope,
  withStableTenantManagementAuthority,
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

const MEMBER_ACTIONS = Object.freeze(['view', 'list', 'filter', 'inspect']);
const ADMIN_ACTIONS = Object.freeze([...MEMBER_ACTIONS, 'resolve-approval']);

export function createTenantDecisionRecordsClient(
  config: DesktopRuntimeConfig,
): TenantDecisionRecordsClient {
  const runtimeConfig = Object.freeze({ ...config });
  const scopeFor = (scope: TenantManagementWorkspaceScope) => {
    const currentScope = requireTenantManagementScope(
      runtimeConfig,
      scope,
      'cloud_only',
      TENANT_DECISION_RECORDS_LOCAL_REASON,
    );
    const workspaceId = requireIdentifier(
      currentScope.workspaceId,
      'tenant_decisions_workspace_scope_invalid',
    );
    if (workspaceId !== runtimeConfig.workspaceId) {
      throw tenantAdminError('tenant_decisions_workspace_scope_mismatch', 409);
    }
    return currentScope;
  };
  return Object.freeze({
    async load(scope, options) {
      const currentScope = scopeFor(scope);
      const params = new URLSearchParams({ workspace_id: currentScope.workspaceId });
      if (options?.filters?.agentId) params.set('agent_id', options.filters.agentId);
      if (options?.filters?.decisionType) {
        params.set('decision_type', options.filters.decisionType);
      }
      const observation = await withStableTenantManagementAuthority(
        runtimeConfig,
        currentScope,
        options,
        () =>
          requestTenantManagementJson(
            runtimeConfig,
            `${root(currentScope)}/decision-records?${params.toString()}`,
            options,
          ),
      );
      const membershipRole = observation.membershipRole;
      const payload = observation.value;
      if (!isRecord(payload) || !Array.isArray(payload.items)) {
        throw tenantAdminError('tenant_decisions_list_contract_invalid');
      }
      const data = Object.freeze({
        membershipRole,
        records: Object.freeze(payload.items.map((item) => parseRecord(item, currentScope))),
      });
      return Object.freeze({
        scope: currentScope,
        scopeRevision: observation.scopeRevision,
        authority: authorityFor(runtimeConfig),
        availability: 'available',
        reasonCode: null,
        contractVersion: '4.0.0',
        allowedActions:
          membershipRole === 'owner' || membershipRole === 'admin'
            ? ADMIN_ACTIONS
            : MEMBER_ACTIONS,
        data,
        ...data,
      });
    },
    async resolveApproval(scope, recordId, decision, options) {
      const currentScope = scopeFor(scope);
      const role = await observeTenantManagementRole(runtimeConfig, currentScope, options);
      requireRole(role, ['owner', 'admin'], 'tenant_decisions_resolve_forbidden');
      const payload = await requestTenantManagementJson(
        runtimeConfig,
        `${root(currentScope)}/approval-requests/${encodeURIComponent(
          requireIdentifier(recordId, 'tenant_decisions_record_id_required'),
        )}/resolve`,
        {
          ...options,
          method: 'POST',
          body: { decision: requireDecision(decision) },
        },
      );
      return parseRecord(payload, currentScope);
    },
  });
}

function root(scope: TenantManagementWorkspaceScope): string {
  return `/api/v1/tenants/${encodeURIComponent(scope.tenantId)}/trust`;
}

function parseRecord(
  value: unknown,
  scope: TenantManagementWorkspaceScope,
): TenantDecisionRecord {
  if (!isRecord(value)) throw tenantAdminError('tenant_decisions_record_contract_invalid');
  const tenantId = requireIdentifier(value.tenant_id, 'tenant_decisions_record_contract_invalid');
  const workspaceId = requireIdentifier(
    value.workspace_id,
    'tenant_decisions_record_contract_invalid',
  );
  if (tenantId !== scope.tenantId || workspaceId !== scope.workspaceId) {
    throw tenantAdminError('tenant_decisions_record_scope_mismatch', 409);
  }
  return Object.freeze({
    id: requireIdentifier(value.id, 'tenant_decisions_record_contract_invalid'),
    tenantId,
    workspaceId,
    agentInstanceId: requireIdentifier(
      value.agent_instance_id,
      'tenant_decisions_record_contract_invalid',
    ),
    decisionType: requireText(value.decision_type, 'tenant_decisions_record_contract_invalid'),
    contextSummary: optionalText(
      value.context_summary,
      'tenant_decisions_record_contract_invalid',
    ),
    proposal: requireRecord(value.proposal, 'tenant_decisions_record_contract_invalid'),
    outcome: requireOutcome(value.outcome),
    reviewerId: optionalText(value.reviewer_id, 'tenant_decisions_record_contract_invalid'),
    reviewType: optionalText(value.review_type, 'tenant_decisions_record_contract_invalid'),
    reviewComment: optionalText(
      value.review_comment,
      'tenant_decisions_record_contract_invalid',
    ),
    resolvedAt: optionalText(value.resolved_at, 'tenant_decisions_record_contract_invalid'),
    createdAt: requireText(value.created_at, 'tenant_decisions_record_contract_invalid'),
    updatedAt: optionalText(value.updated_at, 'tenant_decisions_record_contract_invalid'),
  });
}

function requireOutcome(value: unknown): TenantDecisionOutcome {
  const outcomes = new Set<TenantDecisionOutcome>([
    'pending',
    'approved',
    'denied',
    'success',
    'rejected',
  ]);
  if (typeof value !== 'string' || !outcomes.has(value as TenantDecisionOutcome)) {
    throw tenantAdminError('tenant_decisions_outcome_contract_invalid');
  }
  return value as TenantDecisionOutcome;
}

function requireDecision(value: unknown): TenantApprovalDecision {
  if (value !== 'allow_once' && value !== 'allow_always' && value !== 'deny') {
    throw tenantAdminError('tenant_decisions_resolution_invalid', 422);
  }
  return value;
}
