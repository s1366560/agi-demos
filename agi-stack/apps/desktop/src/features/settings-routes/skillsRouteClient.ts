import { ManagedResourcesClient } from '../../api/managedResourcesClient';
import type { DesktopRuntimeConfig } from '../../types';
import {
  managementRouteObservation,
  requireManagementRouteRuntimeScope,
  type ManagementRouteClient,
} from './managementRouteTypes';

export type SkillsRouteAuthority = Pick<
  ManagedResourcesClient,
  'listManagedSkills'
>;

export function createSkillsRouteClient(
  config: DesktopRuntimeConfig,
  authority: SkillsRouteAuthority = new ManagedResourcesClient(config),
): ManagementRouteClient {
  const runtimeConfig = Object.freeze({ ...config });
  const client: ManagementRouteClient = {
    async observe(scope, options) {
      const currentScope = requireManagementRouteRuntimeScope(
        runtimeConfig,
        scope,
      );
      const skills = await authority.listManagedSkills(options?.signal);
      return managementRouteObservation(currentScope, skills.length);
    },
  };
  return Object.freeze(client);
}
