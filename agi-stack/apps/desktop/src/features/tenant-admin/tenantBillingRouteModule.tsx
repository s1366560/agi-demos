import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import type { TenantBillingController } from './tenantBillingController';
import { TENANT_BILLING_ROUTE_ID } from './tenantBillingClient';
import {
  buildTenantBillingPresentation,
  type TenantBillingViewModel,
} from './tenantBillingPresentationModel';
import type { TenantAdminScope } from './tenantAdminHttp';
import {
  createTenantAdminRouteModuleLoader,
  type TenantAdminRouteBinding,
  type TenantAdminRouteContext,
} from './tenantAdminRouteModuleFactory';

export type TenantBillingRouteBinding = TenantAdminRouteBinding<
  TenantAdminScope,
  TenantBillingViewModel,
  TenantBillingController
>;

export function createTenantBillingRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: TenantAdminRouteContext) => TenantBillingRouteBinding;
}>): DesktopRouteModuleLoader {
  return createTenantAdminRouteModuleLoader({
    routeId: TENANT_BILLING_ROUTE_ID,
    createBinding,
    loadPage: async () => (await import('./TenantBillingPage')).TenantBillingPage,
    fallbackScope: (context) =>
      Object.freeze({
        authority: 'cloud',
        tenantId: context.tenantId ?? 'unavailable',
      }),
    buildTerminalModel: (scope, reasonCode) =>
      buildTenantBillingPresentation({
        state: 'unavailable',
        scope,
        snapshot: null,
        reasonCode,
        retryVisible: false,
        busyAction: null,
      }),
  });
}
