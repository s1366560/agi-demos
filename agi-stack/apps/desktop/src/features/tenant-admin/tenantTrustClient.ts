import type { DesktopRuntimeConfig } from '../../types';
import type { TenantAdminAuthoritySnapshot } from './tenantAdminController';
import {
  isRecord,
  observeTenantMembership,
  optionalText,
  requestTenantAdminJson,
  requireCloudTenantScope,
  requireIdentifier,
  requireNonnegativeInteger,
  requireText,
  tenantAdminError,
  type TenantAdminRequestOptions,
  type TenantAdminRole,
  type TenantAdminScope,
} from './tenantAdminHttp';

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

const CONTRACT_VERSION = '4.0.0' as const;
const MEMBER_ACTIONS = Object.freeze(['view', 'list']);
const ADMIN_ACTIONS = Object.freeze([...MEMBER_ACTIONS, 'create', 'revoke']);
const GRANT_TYPES = new Set<TenantTrustGrantType>(['once', 'always']);

export function createTenantTrustClient(config: DesktopRuntimeConfig): TenantTrustClient {
  const runtimeConfig = Object.freeze({ ...config });
  return Object.freeze({
    async load(scope, options) {
      const currentScope = requireTrustScope(runtimeConfig, scope);
      const membershipRole = await observeTenantMembership(runtimeConfig, currentScope, options);
      const params = new URLSearchParams({
        workspace_id: currentScope.workspaceId,
      });
      const payload = await requestTenantAdminJson(
        runtimeConfig,
        `${trustPath(currentScope)}/policies?${params.toString()}`,
        options,
      );
      const policies = parsePolicies(payload, currentScope);
      const data = Object.freeze({ membershipRole, policies });
      return Object.freeze({
        scope: currentScope,
        authority: 'cloud',
        availability: 'available',
        reasonCode: null,
        contractVersion: CONTRACT_VERSION,
        allowedActions:
          membershipRole === 'owner' || membershipRole === 'admin' ? ADMIN_ACTIONS : MEMBER_ACTIONS,
        data,
        ...data,
      });
    },
    async create(scope, input, options) {
      const currentScope = requireTrustScope(runtimeConfig, scope);
      await requireAdmin(runtimeConfig, currentScope, options);
      const payload = await requestTenantAdminJson(
        runtimeConfig,
        `${trustPath(currentScope)}/policies`,
        {
          ...options,
          method: 'POST',
          body: {
            workspace_id: currentScope.workspaceId,
            agent_instance_id: requireIdentifier(
              input.agentInstanceId,
              'tenant_trust_agent_instance_id_required',
            ),
            action_type: requireIdentifier(input.actionType, 'tenant_trust_action_type_required'),
            grant_type: requireGrantType(input.grantType),
          },
        },
      );
      return parsePolicy(payload, currentScope);
    },
    async revoke(scope, policyId, options) {
      const currentScope = requireTrustScope(runtimeConfig, scope);
      await requireAdmin(runtimeConfig, currentScope, options);
      const params = new URLSearchParams({
        workspace_id: currentScope.workspaceId,
      });
      const payload = await requestTenantAdminJson(
        runtimeConfig,
        `${trustPath(currentScope)}/policies/${encodeURIComponent(
          requireIdentifier(policyId, 'tenant_trust_policy_id_required'),
        )}?${params.toString()}`,
        { ...options, method: 'DELETE' },
      );
      return parsePolicy(payload, currentScope);
    },
  });
}

function requireTrustScope(
  config: DesktopRuntimeConfig,
  scope: TenantTrustScope,
): TenantTrustScope {
  const currentScope = requireCloudTenantScope(config, scope, TENANT_TRUST_LOCAL_REASON);
  const workspaceId = requireIdentifier(
    currentScope.workspaceId,
    'tenant_trust_workspace_scope_invalid',
  );
  if (workspaceId === 'default' || workspaceId === 'local') {
    throw tenantAdminError('tenant_trust_workspace_scope_invalid', 422);
  }
  if (config.workspaceId.trim() !== workspaceId) {
    throw tenantAdminError('tenant_trust_workspace_scope_mismatch', 409);
  }
  return currentScope;
}

async function requireAdmin(
  config: DesktopRuntimeConfig,
  scope: TenantTrustScope,
  options?: TenantAdminRequestOptions,
): Promise<void> {
  const role = await observeTenantMembership(config, scope, options);
  if (role !== 'admin' && role !== 'owner') {
    throw tenantAdminError('tenant_trust_mutation_forbidden', 403);
  }
}

function trustPath(scope: TenantTrustScope): string {
  return `/api/v1/tenants/${encodeURIComponent(scope.tenantId)}/trust`;
}

function parsePolicies(payload: unknown, scope: TenantTrustScope): readonly TenantTrustPolicy[] {
  if (!isRecord(payload) || !Array.isArray(payload.items)) {
    throw tenantAdminError('tenant_trust_list_contract_invalid');
  }
  return Object.freeze(payload.items.map((item) => parsePolicy(item, scope)));
}

function parsePolicy(value: unknown, scope: TenantTrustScope): TenantTrustPolicy {
  if (!isRecord(value)) throw tenantAdminError('tenant_trust_policy_contract_invalid');
  const tenantId = requireIdentifier(value.tenant_id, 'tenant_trust_policy_contract_invalid');
  const workspaceId = requireIdentifier(value.workspace_id, 'tenant_trust_policy_contract_invalid');
  if (tenantId !== scope.tenantId || workspaceId !== scope.workspaceId) {
    throw tenantAdminError('tenant_trust_policy_scope_mismatch', 409);
  }
  return Object.freeze({
    id: requireIdentifier(value.id, 'tenant_trust_policy_contract_invalid'),
    tenantId,
    workspaceId,
    agentInstanceId: requireIdentifier(
      value.agent_instance_id,
      'tenant_trust_policy_contract_invalid',
    ),
    actionType: requireText(value.action_type, 'tenant_trust_policy_contract_invalid'),
    grantedBy: requireIdentifier(value.granted_by, 'tenant_trust_policy_contract_invalid'),
    grantType: requireGrantType(value.grant_type),
    scope: requireText(value.scope ?? 'agent', 'tenant_trust_policy_contract_invalid'),
    revision: requireNonnegativeInteger(
      value.revision ?? 0,
      'tenant_trust_policy_contract_invalid',
    ),
    revokedBy: optionalText(value.revoked_by, 'tenant_trust_policy_contract_invalid'),
    revokedAt: optionalText(value.revoked_at, 'tenant_trust_policy_contract_invalid'),
    createdAt: requireText(value.created_at, 'tenant_trust_policy_contract_invalid'),
    deletedAt: optionalText(value.deleted_at, 'tenant_trust_policy_contract_invalid'),
  });
}

function requireGrantType(value: unknown): TenantTrustGrantType {
  if (typeof value !== 'string' || !GRANT_TYPES.has(value as TenantTrustGrantType)) {
    throw tenantAdminError('tenant_trust_grant_type_invalid', 422);
  }
  return value as TenantTrustGrantType;
}
