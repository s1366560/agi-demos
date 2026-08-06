import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import type { TenantGovernanceController } from './tenantGovernanceController';
import { TENANT_GOVERNANCE_ROUTE_ID } from './tenantGovernanceClient';
import {
  buildTenantGovernancePresentation,
  type TenantGovernanceViewModel,
} from './tenantGovernancePresentationModel';
import type { TenantAdminScope } from './tenantAdminHttp';
import {
  createTenantAdminRouteModuleLoader,
  type TenantAdminRouteBinding,
  type TenantAdminRouteContext,
} from './tenantAdminRouteModuleFactory';

export type TenantGovernanceRouteBinding = TenantAdminRouteBinding<
  TenantAdminScope,
  TenantGovernanceViewModel,
  TenantGovernanceController
>;

export function createTenantGovernanceRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: TenantAdminRouteContext) => TenantGovernanceRouteBinding;
}>): DesktopRouteModuleLoader {
  return createTenantAdminRouteModuleLoader({
    routeId: TENANT_GOVERNANCE_ROUTE_ID,
    createBinding,
    loadPage: async () => (await import('./TenantGovernancePage')).TenantGovernancePage,
    fallbackScope: (context) =>
      Object.freeze({
        authority: 'cloud',
        tenantId: context.tenantId ?? 'unavailable',
      }),
    buildTerminalModel: (scope, reasonCode) =>
      buildTenantGovernancePresentation({
        state: 'unavailable',
        scope,
        snapshot: null,
        reasonCode,
        retryVisible: false,
        busyAction: null,
      }),
  });
}
