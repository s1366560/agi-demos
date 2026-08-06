import type { DesktopRuntimeConfig } from '../../types';
import type { TenantAdminAuthoritySnapshot } from './tenantAdminController';
import {
  isRecord,
  observeTenantMembership,
  optionalText,
  requestTenantAdminJson,
  requestTenantAdminNoContent,
  requireCloudTenantScope,
  requireIdentifier,
  requireNonnegativeInteger,
  requireText,
  tenantAdminError,
  type TenantAdminRequestOptions,
  type TenantAdminRole,
  type TenantAdminScope,
} from './tenantAdminHttp';

export const TENANT_GOVERNANCE_ROUTE_ID = 'tenant-tenant-users' as const;
export const TENANT_GOVERNANCE_LOCAL_REASON = 'cloud_tenant_membership_not_applicable' as const;

export type TenantMemberRole = 'owner' | 'admin' | 'member' | 'editor' | 'viewer';
export type TenantMember = Readonly<{
  userId: string;
  email: string;
  name: string | null;
  role: TenantMemberRole;
  permissions: Readonly<Record<string, unknown>>;
  createdAt: string;
}>;
export type TenantInvitation = Readonly<{
  id: string;
  tenantId: string;
  email: string;
  role: TenantMemberRole;
  status: string;
  invitedBy: string;
  expiresAt: string;
  createdAt: string;
}>;
export type TenantInvitationInput = Readonly<{
  email: string;
  role: TenantMemberRole;
  message?: string;
}>;
export type TenantGovernanceData = Readonly<{
  membershipRole: TenantAdminRole;
  members: readonly TenantMember[];
  invitations: readonly TenantInvitation[];
  pendingInvitationTotal: number | null;
}>;
export type TenantGovernanceSnapshot = TenantAdminAuthoritySnapshot<
  TenantAdminScope,
  TenantGovernanceData
> &
  TenantGovernanceData;

export type TenantGovernanceClient = Readonly<{
  load: (
    scope: TenantAdminScope,
    options?: TenantAdminRequestOptions,
  ) => Promise<TenantGovernanceSnapshot>;
  invite: (
    scope: TenantAdminScope,
    input: TenantInvitationInput,
    options?: TenantAdminRequestOptions,
  ) => Promise<TenantInvitation>;
  changeRole: (
    scope: TenantAdminScope,
    userId: string,
    role: TenantMemberRole,
    options?: TenantAdminRequestOptions,
  ) => Promise<void>;
  removeMember: (
    scope: TenantAdminScope,
    userId: string,
    options?: TenantAdminRequestOptions,
  ) => Promise<void>;
}>;

const CONTRACT_VERSION = '4.0.0' as const;
const ROLES = new Set<TenantMemberRole>(['owner', 'admin', 'member', 'editor', 'viewer']);
const MEMBER_ACTIONS = Object.freeze(['view', 'list']);
const ADMIN_ACTIONS = Object.freeze([
  ...MEMBER_ACTIONS,
  'invite',
  'inspect-pending-invitation-count',
]);
const OWNER_ACTIONS = Object.freeze([...ADMIN_ACTIONS, 'change-role', 'remove-member']);

export function createTenantGovernanceClient(config: DesktopRuntimeConfig): TenantGovernanceClient {
  const runtimeConfig = Object.freeze({ ...config });
  return Object.freeze({
    async load(scope, options) {
      const currentScope = requireCloudTenantScope(
        runtimeConfig,
        scope,
        TENANT_GOVERNANCE_LOCAL_REASON,
      );
      const membershipRole = await observeTenantMembership(runtimeConfig, currentScope, options);
      const membersPayload = await requestTenantAdminJson(
        runtimeConfig,
        `${tenantPath(currentScope)}/members`,
        options,
      );
      const members = parseMembers(membersPayload);
      let invitations: readonly TenantInvitation[] = Object.freeze([]);
      let pendingInvitationTotal: number | null = null;
      if (membershipRole === 'admin' || membershipRole === 'owner') {
        const invitationsPayload = await requestTenantAdminJson(
          runtimeConfig,
          `${tenantPath(currentScope)}/invitations?limit=50&offset=0`,
          options,
        );
        const invitationPage = parseInvitationPage(invitationsPayload, currentScope.tenantId);
        invitations = invitationPage.items;
        pendingInvitationTotal = invitationPage.total;
      }
      const data = Object.freeze({
        membershipRole,
        members,
        invitations,
        pendingInvitationTotal,
      });
      return Object.freeze({
        scope: currentScope,
        authority: 'cloud',
        availability: 'available',
        reasonCode: null,
        contractVersion: CONTRACT_VERSION,
        allowedActions: actionsForRole(membershipRole),
        data,
        ...data,
      });
    },
    async invite(scope, input, options) {
      const currentScope = requireCloudTenantScope(
        runtimeConfig,
        scope,
        TENANT_GOVERNANCE_LOCAL_REASON,
      );
      const role = await requireRole(runtimeConfig, currentScope, ['admin', 'owner'], options);
      if (role !== 'admin' && role !== 'owner') {
        throw tenantAdminError('tenant_governance_invite_forbidden', 403);
      }
      const email = requireIdentifier(input.email, 'tenant_governance_invitation_email_required');
      const memberRole = requireMemberRole(input.role);
      const message = input.message?.trim() ?? '';
      const payload = await requestTenantAdminJson(
        runtimeConfig,
        `${tenantPath(currentScope)}/invitations`,
        {
          ...options,
          method: 'POST',
          body: { email, role: memberRole, ...(message ? { message } : {}) },
        },
      );
      return parseInvitation(payload, currentScope.tenantId);
    },
    async changeRole(scope, userId, role, options) {
      const currentScope = requireCloudTenantScope(
        runtimeConfig,
        scope,
        TENANT_GOVERNANCE_LOCAL_REASON,
      );
      await requireRole(runtimeConfig, currentScope, ['owner'], options);
      await requestTenantAdminJson(
        runtimeConfig,
        `${tenantPath(currentScope)}/members/${encodeURIComponent(
          requireIdentifier(userId, 'tenant_governance_member_id_required'),
        )}`,
        {
          ...options,
          method: 'PATCH',
          body: { role: requireMemberRole(role) },
        },
      );
    },
    async removeMember(scope, userId, options) {
      const currentScope = requireCloudTenantScope(
        runtimeConfig,
        scope,
        TENANT_GOVERNANCE_LOCAL_REASON,
      );
      await requireRole(runtimeConfig, currentScope, ['owner'], options);
      await requestTenantAdminNoContent(
        runtimeConfig,
        `${tenantPath(currentScope)}/members/${encodeURIComponent(
          requireIdentifier(userId, 'tenant_governance_member_id_required'),
        )}`,
        { ...options, method: 'DELETE' },
      );
    },
  });
}

async function requireRole(
  config: DesktopRuntimeConfig,
  scope: TenantAdminScope,
  allowed: readonly TenantAdminRole[],
  options?: TenantAdminRequestOptions,
): Promise<TenantAdminRole> {
  const role = await observeTenantMembership(config, scope, options);
  if (!allowed.includes(role)) throw tenantAdminError('tenant_governance_action_forbidden', 403);
  return role;
}

function actionsForRole(role: TenantAdminRole): readonly string[] {
  if (role === 'owner') return OWNER_ACTIONS;
  if (role === 'admin') return ADMIN_ACTIONS;
  return MEMBER_ACTIONS;
}

function tenantPath(scope: TenantAdminScope): string {
  return `/api/v1/tenants/${encodeURIComponent(scope.tenantId)}`;
}

function parseMembers(payload: unknown): readonly TenantMember[] {
  if (!isRecord(payload) || !Array.isArray(payload.members)) {
    throw tenantAdminError('tenant_governance_members_contract_invalid');
  }
  const members = Object.freeze(payload.members.map(parseMember));
  if (
    payload.total !== undefined &&
    requireNonnegativeInteger(payload.total, 'tenant_governance_members_contract_invalid') !==
      members.length
  ) {
    throw tenantAdminError('tenant_governance_members_contract_invalid');
  }
  return members;
}

function parseMember(value: unknown): TenantMember {
  if (!isRecord(value) || !isRecord(value.permissions)) {
    throw tenantAdminError('tenant_governance_member_contract_invalid');
  }
  return Object.freeze({
    userId: requireIdentifier(value.user_id, 'tenant_governance_member_contract_invalid'),
    email: requireText(value.email, 'tenant_governance_member_contract_invalid'),
    name: optionalText(value.name, 'tenant_governance_member_contract_invalid'),
    role: requireMemberRole(value.role),
    permissions: Object.freeze({ ...value.permissions }),
    createdAt: optionalText(value.created_at, 'tenant_governance_member_contract_invalid') ?? '',
  });
}

function parseInvitationPage(
  payload: unknown,
  tenantId: string,
): Readonly<{ items: readonly TenantInvitation[]; total: number }> {
  if (!isRecord(payload) || !Array.isArray(payload.items)) {
    throw tenantAdminError('tenant_governance_invitations_contract_invalid');
  }
  return Object.freeze({
    items: Object.freeze(payload.items.map((item) => parseInvitation(item, tenantId))),
    total: requireNonnegativeInteger(
      payload.total,
      'tenant_governance_invitations_contract_invalid',
    ),
  });
}

function parseInvitation(value: unknown, tenantId: string): TenantInvitation {
  if (!isRecord(value)) throw tenantAdminError('tenant_governance_invitation_contract_invalid');
  const observedTenant = requireIdentifier(
    value.tenant_id,
    'tenant_governance_invitation_contract_invalid',
  );
  if (observedTenant !== tenantId) {
    throw tenantAdminError('tenant_governance_invitation_scope_mismatch', 409);
  }
  return Object.freeze({
    id: requireIdentifier(value.id, 'tenant_governance_invitation_contract_invalid'),
    tenantId: observedTenant,
    email: requireText(value.email, 'tenant_governance_invitation_contract_invalid'),
    role: requireMemberRole(value.role),
    status: requireText(value.status, 'tenant_governance_invitation_contract_invalid'),
    invitedBy: requireIdentifier(value.invited_by, 'tenant_governance_invitation_contract_invalid'),
    expiresAt: requireText(value.expires_at, 'tenant_governance_invitation_contract_invalid'),
    createdAt: requireText(value.created_at, 'tenant_governance_invitation_contract_invalid'),
  });
}

function requireMemberRole(value: unknown): TenantMemberRole {
  if (typeof value !== 'string' || !ROLES.has(value as TenantMemberRole)) {
    throw tenantAdminError('tenant_governance_member_role_invalid', 422);
  }
  return value as TenantMemberRole;
}
