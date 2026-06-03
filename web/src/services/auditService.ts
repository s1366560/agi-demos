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
  actor?: string;
  from_date?: string;
  to_date?: string;
}

export interface RuntimeHookAuditListParams {
  page?: number;
  page_size?: number;
  action?: string;
  hook_name?: string;
  executor_kind?: string;
  hook_family?: string;
  isolation_mode?: string;
}

export interface RuntimeHookAuditSummary {
  total: number;
  action_counts: Record<string, number>;
  executor_counts: Record<string, number>;
  family_counts: Record<string, number>;
  isolation_mode_counts: Record<string, number>;
  latest_timestamp: string | null;
}

export type RuntimeHookAuditSummaryParams = Omit<RuntimeHookAuditListParams, 'page' | 'page_size'>;

interface BackendAuditListResponse {
  items: AuditEntry[];
  total: number;
  page?: number;
  page_size?: number;
  limit?: number;
  offset?: number;
}

function normalizeAuditListResponse(response: BackendAuditListResponse): AuditListResponse {
  const pageSize = response.page_size ?? response.limit ?? 20;
  const page =
    response.page ??
    (response.offset !== undefined ? Math.floor(response.offset / Math.max(pageSize, 1)) + 1 : 1);

  return {
    items: response.items,
    total: response.total,
    page,
    page_size: pageSize,
  };
}

function toPaginationParams(page = 1, pageSize = 20): Record<string, number> {
  return {
    limit: pageSize,
    offset: Math.max(page - 1, 0) * pageSize,
  };
}

// ============================================================================
// SERVICE
// ============================================================================

export const auditService = {
  list: async (tenantId: string, params?: AuditListParams) => {
    const page = params?.page ?? 1;
    const pageSize = params?.page_size ?? 20;
    const queryParams: Record<string, string | number> = {
      ...toPaginationParams(page, pageSize),
    };

    if (params?.action) queryParams.action = params.action;
    if (params?.resource_type) queryParams.resource_type = params.resource_type;
    if (params?.actor) queryParams.actor = params.actor;
    if (params?.from_date) queryParams.start_time = params.from_date;
    if (params?.to_date) queryParams.end_time = params.to_date;

    const hasFilters = Boolean(
      params?.action ||
      params?.resource_type ||
      params?.actor ||
      params?.from_date ||
      params?.to_date
    );
    const path = hasFilters
      ? `/tenants/${tenantId}/audit-logs/filter`
      : `/tenants/${tenantId}/audit-logs`;
    const response = await httpClient.get<BackendAuditListResponse>(path, { params: queryParams });

    return normalizeAuditListResponse(response);
  },

  listRuntimeHooks: async (tenantId: string, params?: RuntimeHookAuditListParams) => {
    const page = params?.page ?? 1;
    const pageSize = params?.page_size ?? 20;
    const queryParams: Record<string, string | number> = {
      ...toPaginationParams(page, pageSize),
    };

    if (params?.action) queryParams.action = params.action;
    if (params?.hook_name) queryParams.hook_name = params.hook_name;
    if (params?.executor_kind) queryParams.executor_kind = params.executor_kind;
    if (params?.hook_family) queryParams.hook_family = params.hook_family;
    if (params?.isolation_mode) queryParams.isolation_mode = params.isolation_mode;

    const response = await httpClient.get<BackendAuditListResponse>(
      `/tenants/${tenantId}/audit-logs/runtime-hooks`,
      { params: queryParams }
    );

    return normalizeAuditListResponse(response);
  },

  getRuntimeHookSummary: (tenantId: string, params?: RuntimeHookAuditSummaryParams) =>
    httpClient.get<RuntimeHookAuditSummary>(
      `/tenants/${tenantId}/audit-logs/runtime-hooks/summary`,
      {
        params,
      }
    ),

  exportLogs: (
    tenantId: string,
    format: 'csv' | 'json',
    params?: AuditListParams | RuntimeHookAuditListParams
  ) => {
    const exportParams = params as
      | Partial<AuditListParams & RuntimeHookAuditListParams>
      | undefined;
    const queryParams = new URLSearchParams();
    queryParams.set('format', format);
    if (exportParams?.action) queryParams.set('action', exportParams.action);
    if (exportParams?.resource_type) queryParams.set('resource_type', exportParams.resource_type);
    if (exportParams?.actor) queryParams.set('actor', exportParams.actor);
    if (exportParams?.from_date) queryParams.set('start_time', exportParams.from_date);
    if (exportParams?.to_date) queryParams.set('end_time', exportParams.to_date);
    if (exportParams?.hook_name) queryParams.set('hook_name', exportParams.hook_name);
    if (exportParams?.executor_kind) {
      queryParams.set('executor_kind', exportParams.executor_kind);
    }
    if (exportParams?.hook_family) queryParams.set('hook_family', exportParams.hook_family);
    if (exportParams?.isolation_mode) {
      queryParams.set('isolation_mode', exportParams.isolation_mode);
    }

    return httpClient.get<Blob>(
      `/tenants/${tenantId}/audit-logs/export?${queryParams.toString()}`,
      {
        responseType: 'blob',
      }
    );
  },
};
