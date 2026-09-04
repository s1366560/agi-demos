import type { DesktopRuntimeConfig } from '../types';
import {
  optionalText,
  requireIdentifier,
  requireText,
  tenantAdminError,
} from '../features/tenant-admin/tenantAdminHttp';
import {
  authorityFor,
  isRecord,
  observeTenantManagementRole,
  requestTenantManagementJson,
  requestTenantManagementNoContent,
  requireBoolean,
  requireRole,
  requireStringArray,
  requireTenantManagementScope,
  withStableTenantManagementAuthority,
  type TenantManagementRequestOptions,
  type TenantManagementScope,
} from '../features/tenant-admin/tenantManagementHttp';
import {
  TENANT_WEBHOOKS_LOCAL_REASON,
  type TenantWebhook,
  type TenantWebhookInput,
  type TenantWebhooksClient,
} from '../features/tenant-admin/tenantWebhooksClient';

const ADMIN_ACTIONS = Object.freeze([
  'view',
  'list',
  'list-event-types',
  'create',
  'update',
  'delete',
  'copy-secret',
]);

export function createDesktopTenantWebhooksHttpProjectionV2(
  config: DesktopRuntimeConfig
): TenantWebhooksClient {
  const runtimeConfig = Object.freeze({ ...config });
  const scopeFor = (scope: TenantManagementScope) =>
    requireTenantManagementScope(runtimeConfig, scope, 'cloud_only', TENANT_WEBHOOKS_LOCAL_REASON);
  return Object.freeze({
    async load(scope, options) {
      const currentScope = scopeFor(scope);
      const observation = await withStableTenantManagementAuthority(
        runtimeConfig,
        currentScope,
        options,
        (authority) => {
          requireRole(authority.membershipRole, ['owner', 'admin'], 'tenant_webhooks_forbidden');
          return Promise.all([
            requestTenantManagementJson(runtimeConfig, webhooksPath(currentScope), options),
            requestTenantManagementJson(
              runtimeConfig,
              `/api/v1/events/types?${new URLSearchParams({ tenant_id: currentScope.tenantId })}`,
              options
            ),
          ]);
        }
      );
      const membershipRole = observation.membershipRole;
      const [webhookPayload, eventTypesPayload] = observation.value;
      if (!Array.isArray(webhookPayload)) {
        throw tenantAdminError('tenant_webhooks_list_contract_invalid');
      }
      const data = Object.freeze({
        membershipRole,
        webhooks: Object.freeze(webhookPayload.map((item) => parseWebhook(item, currentScope))),
        eventTypes: requireStringArray(
          eventTypesPayload,
          'tenant_webhooks_event_types_contract_invalid'
        ),
      });
      return Object.freeze({
        scope: currentScope,
        scopeRevision: observation.scopeRevision,
        authority: authorityFor(runtimeConfig),
        availability: 'available',
        reasonCode: null,
        contractVersion: '4.0.0',
        allowedActions: ADMIN_ACTIONS,
        data,
        ...data,
      });
    },
    async createWebhook(scope, input, options) {
      const currentScope = scopeFor(scope);
      await requireAdmin(runtimeConfig, currentScope, options);
      const payload = await requestTenantManagementJson(runtimeConfig, webhooksPath(currentScope), {
        ...options,
        method: 'POST',
        body: webhookBody(input),
      });
      return parseWebhook(payload, currentScope);
    },
    async updateWebhook(scope, webhookId, input, options) {
      const currentScope = scopeFor(scope);
      await requireAdmin(runtimeConfig, currentScope, options);
      const payload = await requestTenantManagementJson(
        runtimeConfig,
        `/api/v1/tenant-webhooks/${encodeURIComponent(
          requireIdentifier(webhookId, 'tenant_webhooks_webhook_id_required')
        )}`,
        { ...options, method: 'PUT', body: webhookBody(input) }
      );
      return parseWebhook(payload, currentScope);
    },
    async deleteWebhook(scope, webhookId, options) {
      const currentScope = scopeFor(scope);
      await requireAdmin(runtimeConfig, currentScope, options);
      await requestTenantManagementNoContent(
        runtimeConfig,
        `/api/v1/tenant-webhooks/${encodeURIComponent(
          requireIdentifier(webhookId, 'tenant_webhooks_webhook_id_required')
        )}`,
        { ...options, method: 'DELETE' }
      );
    },
  });
}

async function requireAdmin(
  config: DesktopRuntimeConfig,
  scope: TenantManagementScope,
  options?: TenantManagementRequestOptions
): Promise<void> {
  const role = await observeTenantManagementRole(config, scope, options);
  requireRole(role, ['owner', 'admin'], 'tenant_webhooks_forbidden');
}

function webhooksPath(scope: TenantManagementScope): string {
  return `/api/v1/tenant-webhooks/${encodeURIComponent(scope.tenantId)}`;
}

function webhookBody(input: TenantWebhookInput): Readonly<Record<string, unknown>> {
  return Object.freeze({
    name: requireIdentifier(input.name, 'tenant_webhooks_name_required'),
    url: requireIdentifier(input.url, 'tenant_webhooks_url_required'),
    events: Object.freeze([...input.events]),
    is_active: input.isActive ?? true,
  });
}

function parseWebhook(value: unknown, scope: TenantManagementScope): TenantWebhook {
  if (!isRecord(value)) throw tenantAdminError('tenant_webhooks_contract_invalid');
  const tenantId = requireIdentifier(value.tenant_id, 'tenant_webhooks_contract_invalid');
  if (tenantId !== scope.tenantId) throw tenantAdminError('tenant_webhooks_scope_mismatch', 409);
  return Object.freeze({
    id: requireIdentifier(value.id, 'tenant_webhooks_contract_invalid'),
    tenantId,
    name: requireText(value.name, 'tenant_webhooks_contract_invalid'),
    url: requireText(value.url, 'tenant_webhooks_contract_invalid'),
    secret: optionalText(value.secret, 'tenant_webhooks_contract_invalid'),
    events: requireStringArray(value.events, 'tenant_webhooks_contract_invalid'),
    isActive: requireBoolean(value.is_active, 'tenant_webhooks_contract_invalid'),
    createdAt: optionalText(value.created_at, 'tenant_webhooks_contract_invalid'),
    updatedAt: optionalText(value.updated_at, 'tenant_webhooks_contract_invalid'),
  });
}
