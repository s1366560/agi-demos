import { httpClient } from './client/httpClient';

export interface TrustPolicy {
  id: string;
  tenant_id: string;
  workspace_id: string;
  agent_instance_id: string;
  action_type: string;
  granted_by: string;
  grant_type: string; // "once" | "always"
  created_at: string;
  deleted_at: string | null;
}

export interface TrustPolicyListResponse {
  items: TrustPolicy[];
}

export interface TrustPolicyCreate {
  workspace_id: string;
  agent_instance_id: string;
  action_type: string;
  grant_type: string;
}

export interface TrustCheckResponse {
  trusted: boolean;
}

export interface DecisionRecord {
  id: string;
  tenant_id: string;
  workspace_id: string;
  agent_instance_id: string;
  decision_type: string;
  context_summary: string | null;
  proposal: Record<string, unknown>;
  outcome: string;
  reviewer_id: string | null;
  review_type: string | null;
  review_comment: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string | null;
  deleted_at: string | null;
}

export interface DecisionRecordListResponse {
  items: DecisionRecord[];
}

export interface ApprovalRequestCreate {
  workspace_id: string;
  agent_instance_id: string;
  action_type: string;
  proposal?: Record<string, unknown>;
  context_summary?: string;
}

export interface ApprovalResolveRequest {
  decision: string; // "allow_once" | "allow_always" | "deny"
}

export const trustService = {
  listPolicies: (tenantId: string, params: { workspace_id: string; agent_instance_id?: string }) =>
    httpClient.get<TrustPolicyListResponse>(`/tenants/${tenantId}/trust/policies`, { params }),

  createPolicy: (tenantId: string, data: TrustPolicyCreate) =>
    httpClient.post<TrustPolicy>(`/tenants/${tenantId}/trust/policies`, data),

  checkTrust: (
    tenantId: string,
    params: { workspace_id: string; agent_instance_id: string; action_type: string }
  ) => httpClient.get<TrustCheckResponse>(`/tenants/${tenantId}/trust/policies/check`, { params }),

  submitApproval: (tenantId: string, data: ApprovalRequestCreate) =>
    httpClient.post<DecisionRecord>(`/tenants/${tenantId}/trust/approval-requests`, data),

  resolveApproval: (tenantId: string, recordId: string, data: ApprovalResolveRequest) =>
    httpClient.post<DecisionRecord>(
      `/tenants/${tenantId}/trust/approval-requests/${recordId}/resolve`,
      data
    ),

  listDecisions: (
    tenantId: string,
    params: { workspace_id: string; agent_id?: string; decision_type?: string }
  ) =>
    httpClient.get<DecisionRecordListResponse>(`/tenants/${tenantId}/trust/decision-records`, {
      params,
    }),

  getDecision: (tenantId: string, recordId: string, params: { workspace_id: string }) =>
    httpClient.get<DecisionRecord>(`/tenants/${tenantId}/trust/decision-records/${recordId}`, {
      params,
    }),
};
