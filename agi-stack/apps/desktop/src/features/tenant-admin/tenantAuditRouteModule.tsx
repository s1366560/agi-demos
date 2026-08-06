import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import type { TenantAuditController } from './tenantAuditController';
import { TENANT_AUDIT_ROUTE_ID } from './tenantAuditClient';
import {
  buildTenantAuditPresentation,
  type TenantAuditViewModel,
} from './tenantAuditPresentationModel';
import type { TenantAdminScope } from './tenantAdminHttp';
import {
  createTenantAdminRouteModuleLoader,
  type TenantAdminRouteBinding,
  type TenantAdminRouteContext,
} from './tenantAdminRouteModuleFactory';

export type TenantAuditRouteBinding = TenantAdminRouteBinding<
  TenantAdminScope,
  TenantAuditViewModel,
  TenantAuditController
>;

export function createTenantAuditRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: TenantAdminRouteContext) => TenantAuditRouteBinding;
}>): DesktopRouteModuleLoader {
  return createTenantAdminRouteModuleLoader({
    routeId: TENANT_AUDIT_ROUTE_ID,
    createBinding,
    loadPage: async () => (await import('./TenantAuditPage')).TenantAuditPage,
    fallbackScope: (context) =>
      Object.freeze({
        authority: 'cloud',
        tenantId: context.tenantId ?? 'unavailable',
      }),
    buildTerminalModel: (scope, reasonCode) =>
      buildTenantAuditPresentation({
        state: 'unavailable',
        scope,
        snapshot: null,
        reasonCode,
        retryVisible: false,
        busyAction: null,
      }),
  });
}
