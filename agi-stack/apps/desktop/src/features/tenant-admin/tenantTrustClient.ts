import type { TenantAdminAuthoritySnapshot } from './tenantAdminController';
import type { TenantAdminRequestOptions, TenantAdminRole, TenantAdminScope } from './tenantAdminHttp';

export const TENANT_TRUST_ROUTE_ID = 'tenant-tenant-trust-policies' as const;
export const TENANT_TRUST_LOCAL_REASON = 'cloud_tenant_trust_governance_not_applicable' as const;

export type TenantTrustScope = TenantAdminScope & Readonly<{ workspaceId: string }>;
export type TenantTrustGrantType = 'once' | 'always';
export type TenantTrustPolicy = Readonly<{
  id: string;
  tenantId: string;
  workspaceId: string;
  agentInstanceId: string;
  actionType: string;
  grantedBy: string;
  grantType: TenantTrustGrantType;
  scope: string;
  revision: number;
  revokedBy: string | null;
  revokedAt: string | null;
  createdAt: string;
  deletedAt: string | null;
}>;
export type TenantTrustPolicyInput = Readonly<{
  agentInstanceId: string;
  actionType: string;
  grantType: TenantTrustGrantType;
}>;
export type TenantTrustData = Readonly<{
  membershipRole: TenantAdminRole;
  policies: readonly TenantTrustPolicy[];
}>;
export type TenantTrustSnapshot = TenantAdminAuthoritySnapshot<TenantTrustScope, TenantTrustData> &
  TenantTrustData;
export type TenantTrustClient = Readonly<{
  load: (
    scope: TenantTrustScope,
    options?: TenantAdminRequestOptions,
  ) => Promise<TenantTrustSnapshot>;
  create: (
    scope: TenantTrustScope,
    input: TenantTrustPolicyInput,
    options?: TenantAdminRequestOptions,
  ) => Promise<TenantTrustPolicy>;
  revoke: (
    scope: TenantTrustScope,
    policyId: string,
    options?: TenantAdminRequestOptions,
  ) => Promise<TenantTrustPolicy>;
}>;
