import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import {
  managementRouteObservation,
  requireManagementRouteRuntimeScope,
  type ManagementRouteClient,
} from './managementRouteTypes';

export type PluginsRouteAuthority = Pick<
  DesktopApiClient,
  'listMarketplacePlugins'
>;

export function createPluginsRouteClient(
  config: DesktopRuntimeConfig,
  authority: PluginsRouteAuthority = new DesktopApiClient(config),
): ManagementRouteClient {
  const runtimeConfig = Object.freeze({ ...config });
  const client: ManagementRouteClient = {
    async observe(scope, options) {
      const currentScope = requireManagementRouteRuntimeScope(
        runtimeConfig,
        scope,
      );
      const plugins = await authority.listMarketplacePlugins(options?.signal);
      return managementRouteObservation(currentScope, plugins.length);
    },
  };
  return Object.freeze(client);
}
