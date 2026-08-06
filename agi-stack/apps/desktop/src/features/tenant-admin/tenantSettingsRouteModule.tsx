import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import type { TenantManagementScope } from './tenantManagementHttp';
import {
  createTenantManagementRouteModuleLoader,
  type TenantManagementRouteBinding,
  type TenantManagementRouteContext,
} from './tenantManagementRouteModuleFactory';
import type { TenantSettingsController } from './tenantSettingsController';
import { TENANT_SETTINGS_ROUTE_ID } from './tenantSettingsClient';
import {
  buildTenantSettingsPresentation,
  type TenantSettingsViewModel,
} from './tenantSettingsPresentationModel';

export type TenantSettingsRouteBinding = TenantManagementRouteBinding<
  TenantManagementScope,
  TenantSettingsViewModel,
  TenantSettingsController
>;

export function createTenantSettingsRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: TenantManagementRouteContext) => TenantSettingsRouteBinding;
}>): DesktopRouteModuleLoader {
  return createTenantManagementRouteModuleLoader({
    routeId: TENANT_SETTINGS_ROUTE_ID,
    localPolicy: 'cloud_only',
    createBinding,
    loadPage: async () => (await import('./TenantSettingsPage')).TenantSettingsPage,
    fallbackScope: (context) =>
      Object.freeze({ authority: 'cloud', tenantId: context.tenantId ?? 'unavailable' }),
    buildTerminalModel: (scope, reasonCode) =>
      buildTenantSettingsPresentation({
        state: 'unavailable',
        scope,
        snapshot: null,
        reasonCode,
        retryVisible: false,
        busyAction: null,
      }),
  });
}
