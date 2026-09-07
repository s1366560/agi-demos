import {
  optionalText,
  requireIdentifier,
  requireNonnegativeInteger,
  requireText,
  tenantAdminError,
  type TenantAdminRole,
} from './tenantAdminHttp';
import {
  isRecord,
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
