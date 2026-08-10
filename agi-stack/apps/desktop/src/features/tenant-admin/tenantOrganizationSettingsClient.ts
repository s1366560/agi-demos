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
  requireBoolean,
  requireRecord,
  requireRole,
  requireTenantManagementScope,
  withStableTenantManagementAuthority,
  type TenantManagementAuthoritySnapshot,
  type TenantManagementRequestOptions,
  type TenantManagementScope,
} from './tenantManagementHttp';
import {
  parseTenantSettingsTenant,
  type TenantSettingsTenant,
} from './tenantSettingsClient';

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

const MEMBER_ACTIONS = Object.freeze(['view', 'inspect-stats', 'inspect-smtp']);
const ADMIN_ACTIONS = Object.freeze([
  ...MEMBER_ACTIONS,
  'manage-registries',
  'update-smtp',
  'delete-smtp',
  'test-smtp',
  'manage-gene-policies',
]);

export function createTenantOrganizationSettingsClient(
  config: DesktopRuntimeConfig,
): TenantOrganizationSettingsClient {
  const runtimeConfig = Object.freeze({ ...config });
  const scopeFor = (scope: TenantManagementScope) =>
    requireTenantManagementScope(
      runtimeConfig,
      scope,
      'cloud_only',
      TENANT_ORGANIZATION_SETTINGS_LOCAL_REASON,
    );
  return Object.freeze({
    async load(scope, options) {
      const currentScope = scopeFor(scope);
      const path = tenantPath(currentScope);
      const observation = await withStableTenantManagementAuthority(
        runtimeConfig,
        currentScope,
        options,
        () =>
          Promise.all([
            requestTenantManagementJson(runtimeConfig, path, options),
            requestTenantManagementJson(runtimeConfig, `${path}/stats`, options),
            requestTenantManagementJson(runtimeConfig, `${path}/registries`, options),
            requestTenantManagementJson(runtimeConfig, `${path}/smtp-config`, options, true),
            requestTenantManagementJson(runtimeConfig, `${path}/gene-policies`, options),
          ]),
      );
      const [tenantPayload, statsPayload, registriesPayload, smtpPayload, policiesPayload] =
        observation.value;
      const membershipRole = observation.membershipRole;
      if (!Array.isArray(registriesPayload) || !Array.isArray(policiesPayload)) {
        throw tenantAdminError('tenant_org_settings_collection_contract_invalid');
      }
      const data = Object.freeze({
        membershipRole,
        tenant: parseTenantSettingsTenant(tenantPayload, currentScope),
        stats: requireRecord(statsPayload, 'tenant_org_settings_stats_contract_invalid'),
        registries: Object.freeze(
          registriesPayload.map((item) => parseRegistry(item, currentScope)),
        ),
        smtp: smtpPayload === null ? null : parseSmtp(smtpPayload, currentScope),
        genePolicies: Object.freeze(
          policiesPayload.map((item) => parseGenePolicy(item, currentScope)),
        ),
      });
      return Object.freeze({
        scope: currentScope,
        scopeRevision: observation.scopeRevision,
        authority: authorityFor(runtimeConfig),
        availability: 'available',
        reasonCode: null,
        contractVersion: '4.0.0',
        allowedActions:
          membershipRole === 'owner' || membershipRole === 'admin'
            ? ADMIN_ACTIONS
            : MEMBER_ACTIONS,
        data,
        ...data,
      });
    },
    async saveRegistry(scope, input, options) {
      const currentScope = scopeFor(scope);
      await requireAdmin(runtimeConfig, currentScope, options);
      const path = input.id
        ? `${tenantPath(currentScope)}/registries/${encodeURIComponent(
            requireIdentifier(input.id, 'tenant_org_registry_id_required'),
          )}`
        : `${tenantPath(currentScope)}/registries`;
      const payload = await requestTenantManagementJson(runtimeConfig, path, {
        ...options,
        method: input.id ? 'PUT' : 'POST',
        body: registryBody(input),
      });
      return parseRegistry(payload, currentScope);
    },
    async deleteRegistry(scope, registryId, options) {
      const currentScope = scopeFor(scope);
      await requireAdmin(runtimeConfig, currentScope, options);
      await requestTenantManagementNoContent(
        runtimeConfig,
        `${tenantPath(currentScope)}/registries/${encodeURIComponent(
          requireIdentifier(registryId, 'tenant_org_registry_id_required'),
        )}`,
        { ...options, method: 'DELETE' },
      );
    },
    async testRegistry(scope, registryId, options) {
      const currentScope = scopeFor(scope);
      await requireAdmin(runtimeConfig, currentScope, options);
      const payload = await requestTenantManagementJson(
        runtimeConfig,
        `${tenantPath(currentScope)}/registries/${encodeURIComponent(
          requireIdentifier(registryId, 'tenant_org_registry_id_required'),
        )}/test`,
        { ...options, method: 'POST', body: null },
      );
      return requireRecord(payload, 'tenant_org_registry_test_contract_invalid');
    },
    async saveSmtp(scope, input, options) {
      const currentScope = scopeFor(scope);
      await requireAdmin(runtimeConfig, currentScope, options);
      const payload = await requestTenantManagementJson(
        runtimeConfig,
        `${tenantPath(currentScope)}/smtp-config`,
        { ...options, method: 'PUT', body: smtpBody(input) },
      );
      return parseSmtp(payload, currentScope);
    },
    async deleteSmtp(scope, options) {
      const currentScope = scopeFor(scope);
      await requireAdmin(runtimeConfig, currentScope, options);
      await requestTenantManagementNoContent(runtimeConfig, `${tenantPath(currentScope)}/smtp-config`, {
        ...options,
        method: 'DELETE',
      });
    },
    async testSmtp(scope, recipientEmail, options) {
      const currentScope = scopeFor(scope);
      await requireAdmin(runtimeConfig, currentScope, options);
      const payload = await requestTenantManagementJson(
        runtimeConfig,
        `${tenantPath(currentScope)}/smtp-config/test`,
        {
          ...options,
          method: 'POST',
          body: {
            recipient_email: requireIdentifier(
              recipientEmail,
              'tenant_org_smtp_recipient_required',
            ),
          },
        },
      );
      return requireRecord(payload, 'tenant_org_smtp_test_contract_invalid');
    },
    async saveGenePolicy(scope, input, options) {
      const currentScope = scopeFor(scope);
      await requireAdmin(runtimeConfig, currentScope, options);
      const policyKey = requireIdentifier(input.policyKey, 'tenant_org_gene_policy_key_required');
      const payload = await requestTenantManagementJson(
        runtimeConfig,
        `${tenantPath(currentScope)}/gene-policies/${encodeURIComponent(policyKey)}`,
        {
          ...options,
          method: 'PUT',
          body: {
            policy_key: policyKey,
            policy_value: Object.freeze({ ...input.policyValue }),
            description: input.description ?? null,
          },
        },
      );
      return parseGenePolicy(payload, currentScope);
    },
    async deleteGenePolicy(scope, policyKey, options) {
      const currentScope = scopeFor(scope);
      await requireAdmin(runtimeConfig, currentScope, options);
      await requestTenantManagementNoContent(
        runtimeConfig,
        `${tenantPath(currentScope)}/gene-policies/${encodeURIComponent(
          requireIdentifier(policyKey, 'tenant_org_gene_policy_key_required'),
        )}`,
        { ...options, method: 'DELETE' },
      );
    },
  });
}

async function requireAdmin(
  config: DesktopRuntimeConfig,
  scope: TenantManagementScope,
  options?: TenantManagementRequestOptions,
): Promise<void> {
  const role = await observeTenantManagementRole(config, scope, options);
  requireRole(role, ['owner', 'admin'], 'tenant_org_settings_admin_required');
}

function tenantPath(scope: TenantManagementScope): string {
  return `/api/v1/tenants/${encodeURIComponent(scope.tenantId)}`;
}

function registryBody(input: TenantRegistryInput): Readonly<Record<string, unknown>> {
  return Object.freeze({
    name: requireIdentifier(input.name, 'tenant_org_registry_name_required'),
    registry_type: requireIdentifier(input.registryType, 'tenant_org_registry_type_required'),
    url: requireIdentifier(input.url, 'tenant_org_registry_url_required'),
    username: input.username ?? null,
    password: input.password ?? null,
    is_default: input.isDefault ?? false,
  });
}

function smtpBody(input: TenantSmtpInput): Readonly<Record<string, unknown>> {
  return Object.freeze({
    smtp_host: requireIdentifier(input.smtpHost, 'tenant_org_smtp_host_required'),
    smtp_port: input.smtpPort,
    smtp_username: requireIdentifier(input.smtpUsername, 'tenant_org_smtp_username_required'),
    smtp_password: requireIdentifier(input.smtpPassword, 'tenant_org_smtp_password_required'),
    from_email: requireIdentifier(input.fromEmail, 'tenant_org_smtp_from_email_required'),
    from_name: input.fromName ?? null,
    use_tls: input.useTls ?? true,
  });
}

function parseRegistry(value: unknown, scope: TenantManagementScope): TenantRegistry {
  if (!isRecord(value)) throw tenantAdminError('tenant_org_registry_contract_invalid');
  const tenantId = requireIdentifier(value.tenant_id, 'tenant_org_registry_contract_invalid');
  if (tenantId !== scope.tenantId) throw tenantAdminError('tenant_org_registry_scope_mismatch', 409);
  return Object.freeze({
    id: requireIdentifier(value.id, 'tenant_org_registry_contract_invalid'),
    tenantId,
    name: requireText(value.name, 'tenant_org_registry_contract_invalid'),
    type: requireText(value.type, 'tenant_org_registry_contract_invalid'),
    url: requireText(value.url, 'tenant_org_registry_contract_invalid'),
    username: optionalText(value.username, 'tenant_org_registry_contract_invalid'),
    isDefault: requireBoolean(value.is_default, 'tenant_org_registry_contract_invalid'),
    status: requireText(value.status, 'tenant_org_registry_contract_invalid'),
    lastChecked: optionalText(value.last_checked, 'tenant_org_registry_contract_invalid'),
    createdAt: requireText(value.created_at, 'tenant_org_registry_contract_invalid'),
    updatedAt: optionalText(value.updated_at, 'tenant_org_registry_contract_invalid'),
  });
}

function parseSmtp(value: unknown, scope: TenantManagementScope): TenantSmtpConfig {
  if (!isRecord(value)) throw tenantAdminError('tenant_org_smtp_contract_invalid');
  const tenantId = requireIdentifier(value.tenant_id, 'tenant_org_smtp_contract_invalid');
  if (tenantId !== scope.tenantId) throw tenantAdminError('tenant_org_smtp_scope_mismatch', 409);
  return Object.freeze({
    id: requireIdentifier(value.id, 'tenant_org_smtp_contract_invalid'),
    tenantId,
    smtpHost: requireText(value.smtp_host, 'tenant_org_smtp_contract_invalid'),
    smtpPort: requireNonnegativeInteger(value.smtp_port, 'tenant_org_smtp_contract_invalid'),
    smtpUsername: requireText(value.smtp_username, 'tenant_org_smtp_contract_invalid'),
    smtpPasswordMasked: requireText(
      value.smtp_password_masked,
      'tenant_org_smtp_contract_invalid',
    ),
    fromEmail: requireText(value.from_email, 'tenant_org_smtp_contract_invalid'),
    fromName: optionalText(value.from_name, 'tenant_org_smtp_contract_invalid'),
    useTls: requireBoolean(value.use_tls, 'tenant_org_smtp_contract_invalid'),
  });
}

function parseGenePolicy(value: unknown, scope: TenantManagementScope): TenantGenePolicy {
  if (!isRecord(value)) throw tenantAdminError('tenant_org_gene_policy_contract_invalid');
  const tenantId = requireIdentifier(value.tenant_id, 'tenant_org_gene_policy_contract_invalid');
  if (tenantId !== scope.tenantId) {
    throw tenantAdminError('tenant_org_gene_policy_scope_mismatch', 409);
  }
  return Object.freeze({
    id: requireIdentifier(value.id, 'tenant_org_gene_policy_contract_invalid'),
    tenantId,
    policyKey: requireIdentifier(value.policy_key, 'tenant_org_gene_policy_contract_invalid'),
    policyValue: requireRecord(value.policy_value, 'tenant_org_gene_policy_contract_invalid'),
    description: optionalText(value.description, 'tenant_org_gene_policy_contract_invalid'),
    createdAt: requireText(value.created_at, 'tenant_org_gene_policy_contract_invalid'),
    updatedAt: optionalText(value.updated_at, 'tenant_org_gene_policy_contract_invalid'),
  });
}
