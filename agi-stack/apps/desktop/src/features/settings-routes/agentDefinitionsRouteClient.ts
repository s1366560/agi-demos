import { ManagedResourcesClient } from '../../api/managedResourcesClient';
import type { DesktopRuntimeConfig } from '../../types';
import {
  managementRouteObservation,
  requireManagementRouteRuntimeScope,
  type ManagementRouteClient,
} from './managementRouteTypes';

export type AgentDefinitionsRouteAuthority = Pick<
  ManagedResourcesClient,
  'listManagedAgents'
>;

export function createAgentDefinitionsRouteClient(
  config: DesktopRuntimeConfig,
  authority: AgentDefinitionsRouteAuthority = new ManagedResourcesClient(
    config,
  ),
): ManagementRouteClient {
  const runtimeConfig = Object.freeze({ ...config });
  const client: ManagementRouteClient = {
    async observe(scope, options) {
      const currentScope = requireManagementRouteRuntimeScope(
        runtimeConfig,
        scope,
      );
      const definitions = await authority.listManagedAgents(options?.signal);
      return managementRouteObservation(currentScope, definitions.length);
    },
  };
  return Object.freeze(client);
}
