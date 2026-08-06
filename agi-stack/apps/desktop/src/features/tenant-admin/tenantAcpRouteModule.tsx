import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import type { TenantAcpController } from './tenantAcpController';
import { TENANT_ACP_ROUTE_ID } from './tenantAcpClient';
import {
  buildTenantAcpPresentation,
  type TenantAcpViewModel,
} from './tenantAcpPresentationModel';
import type { TenantManagementScope } from './tenantManagementHttp';
import {
  createTenantManagementRouteModuleLoader,
  type TenantManagementRouteBinding,
  type TenantManagementRouteContext,
} from './tenantManagementRouteModuleFactory';

export type TenantAcpRouteBinding = TenantManagementRouteBinding<
  TenantManagementScope,
  TenantAcpViewModel,
  TenantAcpController
>;

export function createTenantAcpRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: TenantManagementRouteContext) => TenantAcpRouteBinding;
}>): DesktopRouteModuleLoader {
  return createTenantManagementRouteModuleLoader({
    routeId: TENANT_ACP_ROUTE_ID,
    localPolicy: 'cloud_only',
    createBinding,
    loadPage: async () => (await import('./TenantAcpPage')).TenantAcpPage,
    fallbackScope: (context) =>
      Object.freeze({ authority: 'cloud', tenantId: context.tenantId ?? 'unavailable' }),
    buildTerminalModel: (scope, reasonCode) =>
      buildTenantAcpPresentation({
        state: 'unavailable',
        scope,
        snapshot: null,
        reasonCode,
        retryVisible: false,
        busyAction: null,
      }),
  });
}
