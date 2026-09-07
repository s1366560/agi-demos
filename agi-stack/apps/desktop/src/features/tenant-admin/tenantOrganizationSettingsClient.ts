import type { TenantAdminRole } from './tenantAdminHttp';
import type {
  TenantManagementAuthoritySnapshot,
  TenantManagementRequestOptions,
  TenantManagementScope,
} from './tenantManagementHttp';
import type { TenantSettingsTenant } from './tenantSettingsClient';

export const TENANT_ORGANIZATION_SETTINGS_ROUTE_ID = 'tenant-tenant-org-settings' as const;
export const TENANT_ORGANIZATION_SETTINGS_LOCAL_REASON =
  'cloud_organization_governance_not_applicable' as const;

export type TenantRegistry = Readonly<{
  id: string;
  tenantId: string;
  name: string;
  type: string;
  url: string;
  username: string | null;
  isDefault: boolean;
  status: string;
  lastChecked: string | null;
  createdAt: string;
  updatedAt: string | null;
}>;
export type TenantRegistryInput = Readonly<{
  id?: string;
  name: string;
  registryType: string;
  url: string;
  username?: string | null;
  password?: string | null;
  isDefault?: boolean;
}>;
export type TenantSmtpConfig = Readonly<{
  id: string;
  tenantId: string;
  smtpHost: string;
  smtpPort: number;
  smtpUsername: string;
  smtpPasswordMasked: string;
  fromEmail: string;
  fromName: string | null;
  useTls: boolean;
}>;
export type TenantSmtpInput = Readonly<{
  smtpHost: string;
  smtpPort: number;
  smtpUsername: string;
  smtpPassword: string;
  fromEmail: string;
  fromName?: string | null;
  useTls?: boolean;
}>;
export type TenantGenePolicy = Readonly<{
  id: string;
  tenantId: string;
  policyKey: string;
  policyValue: Readonly<Record<string, unknown>>;
  description: string | null;
  createdAt: string;
  updatedAt: string | null;
}>;
export type TenantGenePolicyInput = Readonly<{
  policyKey: string;
  policyValue: Readonly<Record<string, unknown>>;
  description?: string | null;
}>;
export type TenantOrganizationSettingsData = Readonly<{
  membershipRole: TenantAdminRole;
  tenant: TenantSettingsTenant;
  stats: Readonly<Record<string, unknown>>;
  registries: readonly TenantRegistry[];
  smtp: TenantSmtpConfig | null;
  genePolicies: readonly TenantGenePolicy[];
}>;
export type TenantOrganizationSettingsSnapshot = TenantManagementAuthoritySnapshot<
  TenantManagementScope,
  TenantOrganizationSettingsData
> &
  TenantOrganizationSettingsData;
export type TenantOrganizationSettingsClient = Readonly<{
  load: (
    scope: TenantManagementScope,
    options?: TenantManagementRequestOptions,
  ) => Promise<TenantOrganizationSettingsSnapshot>;
  saveRegistry: (
    scope: TenantManagementScope,
    input: TenantRegistryInput,
    options?: TenantManagementRequestOptions,
  ) => Promise<TenantRegistry>;
  deleteRegistry: (
    scope: TenantManagementScope,
    registryId: string,
    options?: TenantManagementRequestOptions,
  ) => Promise<void>;
  testRegistry: (
    scope: TenantManagementScope,
    registryId: string,
    options?: TenantManagementRequestOptions,
  ) => Promise<Readonly<Record<string, unknown>>>;
  saveSmtp: (
    scope: TenantManagementScope,
    input: TenantSmtpInput,
    options?: TenantManagementRequestOptions,
  ) => Promise<TenantSmtpConfig>;
  deleteSmtp: (
    scope: TenantManagementScope,
    options?: TenantManagementRequestOptions,
  ) => Promise<void>;
  testSmtp: (
    scope: TenantManagementScope,
    recipientEmail: string,
    options?: TenantManagementRequestOptions,
  ) => Promise<Readonly<Record<string, unknown>>>;
  saveGenePolicy: (
    scope: TenantManagementScope,
    input: TenantGenePolicyInput,
    options?: TenantManagementRequestOptions,
  ) => Promise<TenantGenePolicy>;
  deleteGenePolicy: (
    scope: TenantManagementScope,
    policyKey: string,
    options?: TenantManagementRequestOptions,
  ) => Promise<void>;
}>;
