import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import type { TenantPatternsController } from './tenantPatternsController';
import { TENANT_PATTERNS_ROUTE_ID } from './tenantPatternsClient';
import type { TenantManagementScope } from './tenantManagementHttp';
import {
  createTenantManagementRouteModuleLoader,
  type TenantManagementRouteBinding,
  type TenantManagementRouteContext,
} from './tenantManagementRouteModuleFactory';
import {
  buildTenantPatternsPresentation,
  type TenantPatternsViewModel,
} from './tenantPatternsPresentationModel';

export type TenantPatternsRouteBinding = TenantManagementRouteBinding<
  TenantManagementScope,
  TenantPatternsViewModel,
  TenantPatternsController
>;

export function createTenantPatternsRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: TenantManagementRouteContext) => TenantPatternsRouteBinding;
}>): DesktopRouteModuleLoader {
  return createTenantManagementRouteModuleLoader({
    routeId: TENANT_PATTERNS_ROUTE_ID,
    localPolicy: 'native_equivalent',
    createBinding,
    loadPage: async () => (await import('./TenantPatternsPage')).TenantPatternsPage,
    fallbackScope: (context) =>
      Object.freeze({ authority: 'cloud', tenantId: context.tenantId ?? 'unavailable' }),
    buildTerminalModel: (scope, reasonCode) =>
      buildTenantPatternsPresentation({
        state: 'unavailable',
        scope,
        snapshot: null,
        reasonCode,
        retryVisible: false,
        busyAction: null,
      }),
  });
}
