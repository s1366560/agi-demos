import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import type { TenantTrustController } from './tenantTrustController';
import { TENANT_TRUST_ROUTE_ID, type TenantTrustScope } from './tenantTrustClient';
import {
  buildTenantTrustPresentation,
  type TenantTrustViewModel,
} from './tenantTrustPresentationModel';
import {
  createTenantAdminRouteModuleLoader,
  type TenantAdminRouteBinding,
  type TenantAdminRouteContext,
} from './tenantAdminRouteModuleFactory';

export type TenantTrustRouteBinding = TenantAdminRouteBinding<
  TenantTrustScope,
  TenantTrustViewModel,
  TenantTrustController
>;

export function createTenantTrustRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: TenantAdminRouteContext) => TenantTrustRouteBinding;
}>): DesktopRouteModuleLoader {
  return createTenantAdminRouteModuleLoader({
    routeId: TENANT_TRUST_ROUTE_ID,
    createBinding,
    loadPage: async () => (await import('./TenantTrustPage')).TenantTrustPage,
    fallbackScope: (context) =>
      Object.freeze({
        authority: 'cloud',
        tenantId: context.tenantId ?? 'unavailable',
        workspaceId: 'unavailable',
      }),
    buildTerminalModel: (scope, reasonCode) =>
      buildTenantTrustPresentation({
        state: 'unavailable',
        scope,
        snapshot: null,
        reasonCode,
        retryVisible: false,
        busyAction: null,
      }),
    scopeMatches: (context, scope) => context.tenantId === scope.tenantId,
  });
}
