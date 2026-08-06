import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import type { TenantDecisionRecordsController } from './tenantDecisionRecordsController';
import { TENANT_DECISION_RECORDS_ROUTE_ID } from './tenantDecisionRecordsClient';
import {
  buildTenantDecisionRecordsPresentation,
  type TenantDecisionRecordsViewModel,
} from './tenantDecisionRecordsPresentationModel';
import type { TenantManagementWorkspaceScope } from './tenantManagementHttp';
import {
  createTenantManagementRouteModuleLoader,
  type TenantManagementRouteBinding,
  type TenantManagementRouteContext,
} from './tenantManagementRouteModuleFactory';

export type TenantDecisionRecordsRouteBinding = TenantManagementRouteBinding<
  TenantManagementWorkspaceScope,
  TenantDecisionRecordsViewModel,
  TenantDecisionRecordsController
>;

export function createTenantDecisionRecordsRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: TenantManagementRouteContext) => TenantDecisionRecordsRouteBinding;
}>): DesktopRouteModuleLoader {
  return createTenantManagementRouteModuleLoader({
    routeId: TENANT_DECISION_RECORDS_ROUTE_ID,
    localPolicy: 'cloud_only',
    createBinding,
    loadPage: async () =>
      (await import('./TenantDecisionRecordsPage')).TenantDecisionRecordsPage,
    fallbackScope: (context) =>
      Object.freeze({
        authority: 'cloud',
        tenantId: context.tenantId ?? 'unavailable',
        workspaceId: context.workspaceId ?? 'unavailable',
      }),
    scopeMatches: (context, scope) => context.tenantId === scope.tenantId,
    buildTerminalModel: (scope, reasonCode) =>
      buildTenantDecisionRecordsPresentation({
        state: 'unavailable',
        scope,
        snapshot: null,
        reasonCode,
        retryVisible: false,
        busyAction: null,
      }),
  });
}
