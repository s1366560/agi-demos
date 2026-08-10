import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import type { TenantManagementScope } from '../tenant-admin/tenantManagementHttp';
import {
  createTenantManagementRouteModuleLoader,
  type TenantManagementRouteBinding,
  type TenantManagementRouteContext,
} from '../tenant-admin/tenantManagementRouteModuleFactory';
import {
  buildBackendStoresPresentation,
  type BackendStoresController,
  type BackendStoresViewModel,
} from './backendStoresController';
import { BACKEND_STORES_ROUTE_ID } from './backendStoresClient';

export type BackendStoresRouteBinding = TenantManagementRouteBinding<
  TenantManagementScope,
  BackendStoresViewModel,
  BackendStoresController
>;

export function createBackendStoresRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: TenantManagementRouteContext) => BackendStoresRouteBinding;
}>): DesktopRouteModuleLoader {
  return createTenantManagementRouteModuleLoader({
    routeId: BACKEND_STORES_ROUTE_ID,
    localPolicy: 'cloud_only',
    createBinding,
    loadPage: async () => (await import('./BackendStoresPage')).BackendStoresPage,
    fallbackScope: (context) =>
      Object.freeze({
        authority: 'cloud',
        tenantId: context.tenantId ?? 'unavailable',
      }),
    buildTerminalModel: (scope, reasonCode) =>
      buildBackendStoresPresentation({
        state: 'unavailable',
        scope,
        snapshot: null,
        reasonCode,
        retryVisible: false,
        busyAction: null,
      }),
  });
}
