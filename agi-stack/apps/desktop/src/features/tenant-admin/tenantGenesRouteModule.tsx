import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import type { TenantGenesController } from './tenantGenesController';
import { TENANT_GENES_ROUTE_ID } from './tenantGenesClient';
import type { TenantManagementScope } from './tenantManagementHttp';
import {
  createTenantManagementRouteModuleLoader,
  type TenantManagementRouteBinding,
  type TenantManagementRouteContext,
} from './tenantManagementRouteModuleFactory';
import {
  buildTenantGenesPresentation,
  type TenantGenesViewModel,
} from './tenantGenesPresentationModel';

export type TenantGenesRouteBinding = TenantManagementRouteBinding<
  TenantManagementScope,
  TenantGenesViewModel,
  TenantGenesController
>;

export function createTenantGenesRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: TenantManagementRouteContext) => TenantGenesRouteBinding;
}>): DesktopRouteModuleLoader {
  return createTenantManagementRouteModuleLoader({
    routeId: TENANT_GENES_ROUTE_ID,
    localPolicy: 'native_equivalent',
    createBinding,
    loadPage: async () => (await import('./TenantGenesPage')).TenantGenesPage,
    fallbackScope: (context) =>
      Object.freeze({ authority: 'cloud', tenantId: context.tenantId ?? 'unavailable' }),
    buildTerminalModel: (scope, reasonCode) =>
      buildTenantGenesPresentation({
        state: 'unavailable',
        scope,
        snapshot: null,
        reasonCode,
        retryVisible: false,
        busyAction: null,
      }),
  });
}
