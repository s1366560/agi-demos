import type { TenantAdminRole } from './tenantAdminHttp';
import {
  type TenantManagementAuthoritySnapshot,
  type TenantManagementRequestOptions,
  type TenantManagementScope,
} from './tenantManagementHttp';

export const TENANT_WEBHOOKS_ROUTE_ID = 'tenant-tenant-webhooks' as const;
export const TENANT_WEBHOOKS_LOCAL_REASON = 'cloud_tenant_webhook_authority_required' as const;

export type TenantWebhook = Readonly<{
  id: string;
  tenantId: string;
  name: string;
  url: string;
  secret: string | null;
  events: readonly string[];
  isActive: boolean;
  createdAt: string | null;
  updatedAt: string | null;
}>;
export type TenantWebhookInput = Readonly<{
  name: string;
  url: string;
  events: readonly string[];
  isActive?: boolean;
}>;
export type TenantWebhooksData = Readonly<{
  membershipRole: TenantAdminRole;
  webhooks: readonly TenantWebhook[];
  eventTypes: readonly string[];
}>;
export type TenantWebhooksSnapshot = TenantManagementAuthoritySnapshot<
  TenantManagementScope,
  TenantWebhooksData
> &
  TenantWebhooksData;
export type TenantWebhooksClient = Readonly<{
  load: (
    scope: TenantManagementScope,
    options?: TenantManagementRequestOptions
  ) => Promise<TenantWebhooksSnapshot>;
  createWebhook: (
    scope: TenantManagementScope,
    input: TenantWebhookInput,
    options?: TenantManagementRequestOptions
  ) => Promise<TenantWebhook>;
  updateWebhook: (
    scope: TenantManagementScope,
    webhookId: string,
    input: TenantWebhookInput & Readonly<{ isActive: boolean }>,
    options?: TenantManagementRequestOptions
  ) => Promise<TenantWebhook>;
  deleteWebhook: (
    scope: TenantManagementScope,
    webhookId: string,
    options?: TenantManagementRequestOptions
  ) => Promise<void>;
}>;
