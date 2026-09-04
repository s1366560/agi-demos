import { type TenantAdminRole } from './tenantAdminHttp';
import {
  type TenantManagementAuthoritySnapshot,
  type TenantManagementRequestOptions,
  type TenantManagementScope,
} from './tenantManagementHttp';

export const TENANT_PATTERNS_ROUTE_ID = 'tenant-tenant-patterns' as const;
export const TENANT_PATTERNS_LOCAL_REASON =
  'local_workflow_patterns_authority_unavailable' as const;

export type TenantWorkflowPatternStep = Readonly<{
  toolName: string;
  toolParameters: Readonly<Record<string, unknown>>;
}>;
export type TenantWorkflowPattern = Readonly<{
  id: string;
  name: string;
  description: string | null;
  usageCount: number;
  successRate: number;
  updatedAt: string;
  steps: readonly TenantWorkflowPatternStep[];
}>;
export type TenantPatternsData = Readonly<{
  membershipRole: TenantAdminRole;
  patterns: readonly TenantWorkflowPattern[];
  total: number;
  page: number;
  pageSize: number;
}>;
export type TenantPatternsSnapshot = TenantManagementAuthoritySnapshot<
  TenantManagementScope,
  TenantPatternsData
> &
  TenantPatternsData;
export type TenantPatternsClient = Readonly<{
  load: (
    scope: TenantManagementScope,
    options?: TenantManagementRequestOptions
  ) => Promise<TenantPatternsSnapshot>;
  deletePattern: (
    scope: TenantManagementScope,
    patternId: string,
    options?: TenantManagementRequestOptions
  ) => Promise<void>;
}>;
