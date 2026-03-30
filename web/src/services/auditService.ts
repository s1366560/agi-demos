import { httpClient } from './client/httpClient';

// ============================================================================
// TYPES
// ============================================================================

export interface AuditEntry {
  id: string;
  timestamp: string;
  actor: string | null;
  actor_name: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  tenant_id: string | null;
  details: Record<string, unknown> | null;
  ip_address: string | null;
  user_agent: string | null;
}

export interface AuditListResponse {
  items: AuditEntry[];
  total: number;
  page: number;
  page_size: number;
}

export interface AuditListParams {
  page?: number;
  page_size?: number;
  action?: string;
  resource_type?: string;
  from_date?: string;
  to_date?: string;
}

// ============================================================================
// SERVICE
// ============================================================================

export const auditService = {
  list: (tenantId: string, params?: AuditListParams) =>
    httpClient.get<AuditListResponse>(`/tenants/${tenantId}/audit-logs`, { params }),

  exportLogs: (tenantId: string, format: 'csv' | 'json', params?: AuditListParams) => {
    const queryParams = new URLSearchParams();
    queryParams.set('format', format);
    if (params?.action) queryParams.set('action', params.action);
    if (params?.resource_type) queryParams.set('resource_type', params.resource_type);
    if (params?.from_date) queryParams.set('from_date', params.from_date);
    if (params?.to_date) queryParams.set('to_date', params.to_date);

    return httpClient.get<Blob>(
      `/tenants/${tenantId}/audit-logs/export?${queryParams.toString()}`,
      {
        responseType: 'blob',
      }
    );
  },
};
