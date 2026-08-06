import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import type { TenantManagementScope } from './tenantManagementHttp';
import {
  createTenantManagementRouteModuleLoader,
  type TenantManagementRouteBinding,
  type TenantManagementRouteContext,
} from './tenantManagementRouteModuleFactory';
import type { TenantOrganizationSettingsController } from './tenantOrganizationSettingsController';
import { TENANT_ORGANIZATION_SETTINGS_ROUTE_ID } from './tenantOrganizationSettingsClient';
import {
  buildTenantOrganizationSettingsPresentation,
  type TenantOrganizationSettingsViewModel,
} from './tenantOrganizationSettingsPresentationModel';

export type TenantOrganizationSettingsRouteBinding = TenantManagementRouteBinding<
  TenantManagementScope,
  TenantOrganizationSettingsViewModel,
  TenantOrganizationSettingsController
>;

export function createTenantOrganizationSettingsRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (
    context: TenantManagementRouteContext,
  ) => TenantOrganizationSettingsRouteBinding;
}>): DesktopRouteModuleLoader {
  return createTenantManagementRouteModuleLoader({
    routeId: TENANT_ORGANIZATION_SETTINGS_ROUTE_ID,
    localPolicy: 'cloud_only',
    createBinding,
    loadPage: async () =>
      (await import('./TenantOrganizationSettingsPage')).TenantOrganizationSettingsPage,
    fallbackScope: (context) =>
      Object.freeze({ authority: 'cloud', tenantId: context.tenantId ?? 'unavailable' }),
    buildTerminalModel: (scope, reasonCode) =>
      buildTenantOrganizationSettingsPresentation({
        state: 'unavailable',
        scope,
        snapshot: null,
        reasonCode,
        retryVisible: false,
        busyAction: null,
      }),
  });
}
