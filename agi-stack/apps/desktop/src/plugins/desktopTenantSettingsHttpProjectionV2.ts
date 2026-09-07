import type { DesktopRuntimeConfig } from '../types';
import { requireIdentifier, tenantAdminError } from '../features/tenant-admin/tenantAdminHttp';
import {
  authorityFor,
  observeTenantManagementRole,
  requestTenantManagementJson,
  requestTenantManagementNoContent,
  requireRecord,
  requireRole,
  requireTenantManagementScope,
  withStableTenantManagementAuthority,
  type TenantManagementRequestOptions,
  type TenantManagementScope,
} from '../features/tenant-admin/tenantManagementHttp';
import {
  parseTenantSettingsTenant,
  TENANT_SETTINGS_LOCAL_REASON,
  type TenantSettingsClient,
  type TenantSettingsUpdate,
} from '../features/tenant-admin/tenantSettingsClient';

const MEMBER_ACTIONS = Object.freeze(['view', 'inspect-usage']);
const OWNER_ACTIONS = Object.freeze([...MEMBER_ACTIONS, 'update', 'delete']);

export function createDesktopTenantSettingsHttpProjectionV2(
  config: DesktopRuntimeConfig
): TenantSettingsClient {
  const runtimeConfig = Object.freeze({ ...config });
  const scopeFor = (scope: TenantManagementScope) =>
    requireTenantManagementScope(runtimeConfig, scope, 'cloud_only', TENANT_SETTINGS_LOCAL_REASON);
  return Object.freeze({
    async load(scope, options) {
      const currentScope = scopeFor(scope);
      const observation = await withStableTenantManagementAuthority(
        runtimeConfig,
        currentScope,
        options,
        () =>
          Promise.all([
            requestTenantManagementJson(runtimeConfig, tenantPath(currentScope), options),
            requestTenantManagementJson(
              runtimeConfig,
              `${tenantPath(currentScope)}/stats`,
              options
            ),
          ])
      );
      const [tenantPayload, statsPayload] = observation.value;
      const membershipRole = observation.membershipRole;
      const data = Object.freeze({
        membershipRole,
        tenant: parseTenantSettingsTenant(tenantPayload, currentScope),
        stats: requireRecord(statsPayload, 'tenant_settings_stats_contract_invalid'),
      });
      return Object.freeze({
        scope: currentScope,
        scopeRevision: observation.scopeRevision,
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
      const payload = await requestTenantManagementJson(runtimeConfig, tenantPath(currentScope), {
        ...options,
        method: 'PUT',
        body: updateBody(input),
      });
      return parseTenantSettingsTenant(payload, currentScope);
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
  options?: TenantManagementRequestOptions
): Promise<void> {
  requireRole(
    await observeTenantManagementRole(config, scope, options),
    ['owner'],
    'tenant_settings_owner_required'
  );
}
function tenantPath(scope: TenantManagementScope): string {
  return `/api/v1/tenants/${encodeURIComponent(scope.tenantId)}`;
}
function updateBody(input: TenantSettingsUpdate): Readonly<Record<string, unknown>> {
  const body: Record<string, unknown> = {};
  if (input.name !== undefined)
    body.name = requireIdentifier(input.name, 'tenant_settings_name_required');
  if (input.description !== undefined) body.description = input.description;
  if (input.plan !== undefined)
    body.plan = requireIdentifier(input.plan, 'tenant_settings_plan_required');
  if (input.maxProjects !== undefined) body.max_projects = input.maxProjects;
  if (input.maxUsers !== undefined) body.max_users = input.maxUsers;
  if (input.maxStorage !== undefined) body.max_storage = input.maxStorage;
  if (Object.keys(body).length === 0) throw tenantAdminError('tenant_settings_update_empty', 422);
  return Object.freeze(body);
}
