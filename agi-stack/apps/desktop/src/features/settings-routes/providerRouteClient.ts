import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import {
  managementRouteObservation,
  requireManagementRouteRuntimeScope,
  type ManagementRouteClient,
} from './managementRouteTypes';

export type ProviderRouteAuthority = Pick<
  DesktopApiClient,
  'listLlmProviders' | 'listLlmProviderTypes'
>;

export function createProviderRouteClient(
  config: DesktopRuntimeConfig,
  authority: ProviderRouteAuthority = new DesktopApiClient(config),
): ManagementRouteClient {
  const runtimeConfig = Object.freeze({ ...config });
  const client: ManagementRouteClient = {
    async observe(scope, options) {
      const currentScope = requireManagementRouteRuntimeScope(
        runtimeConfig,
        scope,
      );
      const [providers] = await Promise.all([
        authority.listLlmProviders(options?.signal),
        authority.listLlmProviderTypes(options?.signal),
      ]);
      return managementRouteObservation(currentScope, providers.length);
    },
  };
  return Object.freeze(client);
}
