import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import type { TenantEventsController } from './tenantEventsController';
import { TENANT_EVENTS_ROUTE_ID } from './tenantEventsClient';
import {
  buildTenantEventsPresentation,
  type TenantEventsViewModel,
} from './tenantEventsPresentationModel';
import type { TenantManagementScope } from './tenantManagementHttp';
import {
  createTenantManagementRouteModuleLoader,
  type TenantManagementRouteBinding,
  type TenantManagementRouteContext,
} from './tenantManagementRouteModuleFactory';

export type TenantEventsRouteBinding = TenantManagementRouteBinding<
  TenantManagementScope,
  TenantEventsViewModel,
  TenantEventsController
>;

export function createTenantEventsRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: TenantManagementRouteContext) => TenantEventsRouteBinding;
}>): DesktopRouteModuleLoader {
  return createTenantManagementRouteModuleLoader({
    routeId: TENANT_EVENTS_ROUTE_ID,
    localPolicy: 'native_equivalent',
    createBinding,
    loadPage: async () => (await import('./TenantEventsPage')).TenantEventsPage,
    fallbackScope: (context) =>
      Object.freeze({ authority: 'cloud', tenantId: context.tenantId ?? 'unavailable' }),
    buildTerminalModel: (scope, reasonCode) =>
      buildTenantEventsPresentation({
        state: 'unavailable',
        scope,
        snapshot: null,
        reasonCode,
        retryVisible: false,
        busyAction: null,
      }),
  });
}
