import type { DesktopRuntimeConfig } from '../../types';
import {
  optionalText,
  requireIdentifier,
  requireNonnegativeInteger,
  requireText,
  tenantAdminError,
  type TenantAdminRole,
} from './tenantAdminHttp';
import {
  authorityFor,
  isRecord,
  observeTenantManagementRole,
  requestTenantManagementJson,
  requestTenantManagementNoContent,
  requireRecord,
  requireRole,
  requireTenantManagementScope,
  type TenantManagementAuthoritySnapshot,
  type TenantManagementRequestOptions,
  type TenantManagementScope,
} from './tenantManagementHttp';

export const TENANT_SETTINGS_ROUTE_ID = 'tenant-tenant-settings' as const;
export const TENANT_SETTINGS_LOCAL_REASON = 'cloud_tenant_settings_not_applicable' as const;

export type TenantSettingsTenant = Readonly<{
  id: string;
  name: string;
  slug: string;
  description: string | null;
  ownerId: string;
  plan: string;
  maxProjects: number;
  maxUsers: number;
  maxStorage: number;
  createdAt: string;
  updatedAt: string | null;
}>;
export type TenantSettingsUpdate = Readonly<{
  name?: string;
  description?: string | null;
  plan?: string;
  maxProjects?: number;
  maxUsers?: number;
  maxStorage?: number;
}>;
export type TenantSettingsData = Readonly<{
  membershipRole: TenantAdminRole;
  tenant: TenantSettingsTenant;
  stats: Readonly<Record<string, unknown>>;
}>;
export type TenantSettingsSnapshot = TenantManagementAuthoritySnapshot<
  TenantManagementScope,
  TenantSettingsData
> &
  TenantSettingsData;
export type TenantSettingsClient = Readonly<{
  load: (
    scope: TenantManagementScope,
    options?: TenantManagementRequestOptions,
  ) => Promise<TenantSettingsSnapshot>;
  updateTenant: (
    scope: TenantManagementScope,
    input: TenantSettingsUpdate,
    options?: TenantManagementRequestOptions,
  ) => Promise<TenantSettingsTenant>;
  deleteTenant: (
    scope: TenantManagementScope,
    options?: TenantManagementRequestOptions,
  ) => Promise<void>;
}>;

const MEMBER_ACTIONS = Object.freeze(['view', 'inspect-usage']);
const OWNER_ACTIONS = Object.freeze([...MEMBER_ACTIONS, 'update', 'delete']);

export function createTenantSettingsClient(config: DesktopRuntimeConfig): TenantSettingsClient {
  const runtimeConfig = Object.freeze({ ...config });
  const scopeFor = (scope: TenantManagementScope) =>
    requireTenantManagementScope(
      runtimeConfig,
      scope,
      'cloud_only',
      TENANT_SETTINGS_LOCAL_REASON,
    );
  return Object.freeze({
    async load(scope, options) {
      const currentScope = scopeFor(scope);
      const membershipRole = await observeTenantManagementRole(runtimeConfig, currentScope, options);
      const [tenantPayload, statsPayload] = await Promise.all([
        requestTenantManagementJson(runtimeConfig, tenantPath(currentScope), options),
        requestTenantManagementJson(runtimeConfig, `${tenantPath(currentScope)}/stats`, options),
      ]);
      const data = Object.freeze({
        membershipRole,
        tenant: parseTenant(tenantPayload, currentScope),
        stats: requireRecord(statsPayload, 'tenant_settings_stats_contract_invalid'),
      });
      return Object.freeze({
        scope: currentScope,
        authority: authorityFor(runtimeConfig),
        availability: 'available',
        reasonCode: null,
        contractVersion: '4.0.0',
        allowedActions: membershipRole === 'owner' ? OWNER_ACTIONS : MEMBER_ACTIONS,
        data,
        ...data,
      });
    },
    async updateTenant(scope, input, options) {
      const currentScope = scopeFor(scope);
      await requireOwner(runtimeConfig, currentScope, options);
      const payload = await requestTenantManagementJson(
        runtimeConfig,
        tenantPath(currentScope),
        { ...options, method: 'PUT', body: updateBody(input) },
      );
      return parseTenant(payload, currentScope);
    },
    async deleteTenant(scope, options) {
      const currentScope = scopeFor(scope);
      await requireOwner(runtimeConfig, currentScope, options);
      await requestTenantManagementNoContent(runtimeConfig, tenantPath(currentScope), {
        ...options,
        method: 'DELETE',
      });
    },
  });
}

async function requireOwner(
  config: DesktopRuntimeConfig,
  scope: TenantManagementScope,
  options?: TenantManagementRequestOptions,
): Promise<void> {
  const role = await observeTenantManagementRole(config, scope, options);
  requireRole(role, ['owner'], 'tenant_settings_owner_required');
}

function tenantPath(scope: TenantManagementScope): string {
  return `/api/v1/tenants/${encodeURIComponent(scope.tenantId)}`;
}

function updateBody(input: TenantSettingsUpdate): Readonly<Record<string, unknown>> {
  const body: Record<string, unknown> = {};
  if (input.name !== undefined) {
    body.name = requireIdentifier(input.name, 'tenant_settings_name_required');
  }
  if (input.description !== undefined) body.description = input.description;
  if (input.plan !== undefined) body.plan = requireIdentifier(input.plan, 'tenant_settings_plan_required');
  if (input.maxProjects !== undefined) body.max_projects = input.maxProjects;
  if (input.maxUsers !== undefined) body.max_users = input.maxUsers;
  if (input.maxStorage !== undefined) body.max_storage = input.maxStorage;
  if (Object.keys(body).length === 0) throw tenantAdminError('tenant_settings_update_empty', 422);
  return Object.freeze(body);
}

export function parseTenantSettingsTenant(
  value: unknown,
  scope: TenantManagementScope,
): TenantSettingsTenant {
  return parseTenant(value, scope);
}

function parseTenant(value: unknown, scope: TenantManagementScope): TenantSettingsTenant {
  if (!isRecord(value)) throw tenantAdminError('tenant_settings_tenant_contract_invalid');
  const id = requireIdentifier(value.id, 'tenant_settings_tenant_contract_invalid');
  if (id !== scope.tenantId) throw tenantAdminError('tenant_settings_scope_mismatch', 409);
  return Object.freeze({
    id,
    name: requireText(value.name, 'tenant_settings_tenant_contract_invalid'),
    slug: requireText(value.slug, 'tenant_settings_tenant_contract_invalid'),
    description: optionalText(value.description, 'tenant_settings_tenant_contract_invalid'),
    ownerId: requireIdentifier(value.owner_id, 'tenant_settings_tenant_contract_invalid'),
    plan: requireText(value.plan, 'tenant_settings_tenant_contract_invalid'),
    maxProjects: requireNonnegativeInteger(
      value.max_projects,
      'tenant_settings_tenant_contract_invalid',
    ),
    maxUsers: requireNonnegativeInteger(value.max_users, 'tenant_settings_tenant_contract_invalid'),
    maxStorage: requireNonnegativeInteger(
      value.max_storage,
      'tenant_settings_tenant_contract_invalid',
    ),
    createdAt: requireText(value.created_at, 'tenant_settings_tenant_contract_invalid'),
    updatedAt: optionalText(value.updated_at, 'tenant_settings_tenant_contract_invalid'),
  });
}
