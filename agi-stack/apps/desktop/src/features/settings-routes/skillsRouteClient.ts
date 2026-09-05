import type { DesktopTenantSkillDefinitionsOperationsV2 } from '../../plugins/desktopTenantSkillDefinitionsAuthorityModuleV2';
import type { DesktopRuntimeConfig } from '../../types';
import {
  managementRouteObservation,
  requireManagementRouteRuntimeScope,
  type ManagementRouteClient,
} from './managementRouteTypes';

export type SkillsRouteAuthority = Pick<
  DesktopTenantSkillDefinitionsOperationsV2,
  'loadTenantSkillDefinitions'
>;

export function createSkillsRouteClient(
  config: DesktopRuntimeConfig,
  authority: SkillsRouteAuthority,
): ManagementRouteClient {
  const runtimeConfig = Object.freeze({ ...config });
  const client: ManagementRouteClient = {
    async observe(scope, options) {
      const currentScope = requireManagementRouteRuntimeScope(
        runtimeConfig,
        scope,
      );
      const skills = await authority.loadTenantSkillDefinitions({
        config: runtimeConfig,
        scope: currentScope,
        signal: options?.signal,
      });
      return managementRouteObservation(currentScope, skills.length);
    },
  };
  return Object.freeze(client);
}
