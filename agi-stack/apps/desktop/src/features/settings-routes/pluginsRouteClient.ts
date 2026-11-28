import type { DesktopPluginMarketplaceCatalogOperationsV2 } from '../../plugins/desktopPluginMarketplaceAuthorityModulesV2';
import type { DesktopRuntimeConfig } from '../../types';
import {
  managementRouteObservation,
  requireManagementRouteRuntimeScope,
  type ManagementRouteClient,
} from './managementRouteTypes';

export type PluginsRouteAuthority = Pick<
  DesktopPluginMarketplaceCatalogOperationsV2,
  'projectMarketplacePlugins'
>;

export function createPluginsRouteClient(
  config: DesktopRuntimeConfig,
  pluginMarketplaceOperationsV2: PluginsRouteAuthority,
): ManagementRouteClient {
  const runtimeConfig = Object.freeze({ ...config });
  const client: ManagementRouteClient = {
    async observe(scope, options) {
      const currentScope = requireManagementRouteRuntimeScope(
        runtimeConfig,
        scope,
      );
      return pluginMarketplaceOperationsV2.projectMarketplacePlugins(
        runtimeConfig,
        options?.signal,
        (plugins) => managementRouteObservation(currentScope, plugins.length),
      );
    },
  };
  return Object.freeze(client);
}
