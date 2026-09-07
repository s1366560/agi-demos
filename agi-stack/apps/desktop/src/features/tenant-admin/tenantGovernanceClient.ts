import type { TenantAdminAuthoritySnapshot } from './tenantAdminController';
import type { TenantAdminRequestOptions, TenantAdminRole, TenantAdminScope } from './tenantAdminHttp';

export const TENANT_GOVERNANCE_ROUTE_ID = 'tenant-tenant-users' as const;
export const TENANT_GOVERNANCE_LOCAL_REASON = 'cloud_tenant_membership_not_applicable' as const;
export type TenantMemberRole = 'owner' | 'admin' | 'member' | 'editor' | 'viewer';
export type TenantMember = Readonly<{ userId: string; email: string; name: string | null; role: TenantMemberRole; permissions: Readonly<Record<string, unknown>>; createdAt: string }>;
export type TenantInvitation = Readonly<{ id: string; tenantId: string; email: string; role: TenantMemberRole; status: string; invitedBy: string; expiresAt: string; createdAt: string }>;
export type TenantInvitationInput = Readonly<{ email: string; role: TenantMemberRole; message?: string }>;
export type TenantGovernanceData = Readonly<{ membershipRole: TenantAdminRole; members: readonly TenantMember[]; invitations: readonly TenantInvitation[]; pendingInvitationTotal: number | null }>;
export type TenantGovernanceSnapshot = TenantAdminAuthoritySnapshot<TenantAdminScope, TenantGovernanceData> & TenantGovernanceData;
export type TenantGovernanceClient = Readonly<{
  load(scope: TenantAdminScope, options?: TenantAdminRequestOptions): Promise<TenantGovernanceSnapshot>;
  invite(scope: TenantAdminScope, input: TenantInvitationInput, options?: TenantAdminRequestOptions): Promise<TenantInvitation>;
  changeRole(scope: TenantAdminScope, userId: string, role: TenantMemberRole, options?: TenantAdminRequestOptions): Promise<void>;
  removeMember(scope: TenantAdminScope, userId: string, options?: TenantAdminRequestOptions): Promise<void>;
}>;
