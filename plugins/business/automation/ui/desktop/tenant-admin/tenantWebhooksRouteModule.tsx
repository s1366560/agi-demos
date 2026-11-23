import type { DesktopRouteModuleLoader } from '@desktop/features/navigation/desktopRouteModule';
import type { TenantManagementScope } from '@desktop/features/tenant-admin/tenantManagementHttp';
import {
  createTenantManagementRouteModuleLoader,
  type TenantManagementRouteBinding,
  type TenantManagementRouteContext,
} from '@desktop/features/tenant-admin/tenantManagementRouteModuleFactory';
import type { TenantWebhooksController } from './tenantWebhooksController';
import { TENANT_WEBHOOKS_ROUTE_ID } from './tenantWebhooksClient';
import {
  buildTenantWebhooksPresentation,
  type TenantWebhooksViewModel,
} from './tenantWebhooksPresentationModel';

export type TenantWebhooksRouteBinding = TenantManagementRouteBinding<
  TenantManagementScope,
  TenantWebhooksViewModel,
  TenantWebhooksController
>;

export function createTenantWebhooksRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: TenantManagementRouteContext) => TenantWebhooksRouteBinding;
}>): DesktopRouteModuleLoader {
  return createTenantManagementRouteModuleLoader({
    routeId: TENANT_WEBHOOKS_ROUTE_ID,
    localPolicy: 'cloud_only',
    createBinding,
    loadPage: async () => (await import('./TenantWebhooksPage')).TenantWebhooksPage,
    fallbackScope: (context) =>
      Object.freeze({ authority: 'cloud', tenantId: context.tenantId ?? 'unavailable' }),
    buildTerminalModel: (scope, reasonCode) =>
      buildTenantWebhooksPresentation({
        state: 'unavailable',
        scope,
        snapshot: null,
        reasonCode,
        retryVisible: false,
        busyAction: null,
      }),
  });
}
