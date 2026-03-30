import { httpClient } from './client/httpClient';

// ============================================================================
// TYPES
// ============================================================================

export interface Invitation {
  id: string;
  tenant_id: string;
  email: string;
  role: string;
  status: string;
  invited_by: string;
  expires_at: string;
  created_at: string;
}

export interface InvitationListResponse {
  items: Invitation[];
  total: number;
  limit: number;
  offset: number;
}

export interface InvitationVerifyResponse {
  valid: boolean;
  email?: string;
  tenant_id?: string;
  role?: string;
  expires_at?: string;
}

export interface CreateInvitationParams {
  email: string;
  role?: string;
  message?: string;
}

// ============================================================================
// SERVICE
// ============================================================================

export const invitationService = {
  create: (tenantId: string, params: CreateInvitationParams) =>
    httpClient.post<Invitation>(`/tenants/${tenantId}/invitations`, params),

  listPending: (tenantId: string, limit = 50, offset = 0) =>
    httpClient.get<InvitationListResponse>(`/tenants/${tenantId}/invitations`, {
      params: { limit, offset },
    }),

  cancel: (tenantId: string, invitationId: string) =>
    httpClient.delete(`/tenants/${tenantId}/invitations/${invitationId}`),

  verify: (token: string) =>
    httpClient.get<InvitationVerifyResponse>(`/invitations/verify/${token}`),

  accept: (token: string, displayName?: string) => {
    const body: Record<string, string> = {};
    if (displayName) {
      body.display_name = displayName;
    }
    return httpClient.post<Invitation>(`/invitations/accept/${token}`, body);
  },
};
