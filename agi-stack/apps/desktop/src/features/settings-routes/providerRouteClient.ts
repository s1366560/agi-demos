import type { DesktopTenantProvidersOperationsV2 } from '../../plugins/desktopTenantProvidersAuthorityModuleV2';
import type { DesktopRuntimeConfig } from '../../types';
import {
  managementRouteObservation,
  requireManagementRouteRuntimeScope,
  type ManagementRouteClient,
} from './managementRouteTypes';

export type ProviderRouteAuthority = Pick<
  DesktopTenantProvidersOperationsV2,
  'listLlmProviders' | 'listLlmProviderTypes'
>;

export function createProviderRouteClient(
  config: DesktopRuntimeConfig,
  authority: ProviderRouteAuthority,
): ManagementRouteClient {
  const runtimeConfig = Object.freeze({ ...config });
  const client: ManagementRouteClient = {
    async observe(scope, options) {
      const currentScope = requireManagementRouteRuntimeScope(
        runtimeConfig,
        scope,
      );
      const input = {
        config: runtimeConfig,
        args: [] as [],
        scope: { authority: currentScope.authority, tenantId: currentScope.tenantId },
        signal: options?.signal,
      };
      const [providers] = await Promise.all([
        authority.listLlmProviders(input),
        authority.listLlmProviderTypes(input),
      ]);
      return managementRouteObservation(currentScope, providers.length);
    },
  };
  return Object.freeze(client);
}
