import type {
  DesktopTenantAgentDefinitionsOperationsV2,
} from '../plugins/desktopTenantAgentDefinitionsAuthorityModuleV2';
import {
  createDesktopTenantAgentDefinitionsHttpProjectionV2,
} from '../plugins/desktopTenantAgentDefinitionsHttpProjectionV2';
import {
  prepareDesktopTenantAgentDefinitionsCreateV2,
  prepareDesktopTenantAgentDefinitionsDeleteV2,
  prepareDesktopTenantAgentDefinitionsEnabledV2,
  prepareDesktopTenantAgentDefinitionsExternalV2,
  prepareDesktopTenantAgentDefinitionsLoadV2,
  prepareDesktopTenantAgentDefinitionsUpdateV2,
  requireDesktopTenantAgentDefinitionDeleteV2,
  requireDesktopTenantAgentDefinitionExternalAcpAgentsV2,
  requireDesktopTenantAgentDefinitionsV2,
  requireDesktopTenantAgentDefinitionV2,
} from '../plugins/desktopTenantAgentDefinitionsOperationContractV2';

// Standalone QA pages have no generation host; keep their transport and
// contract semantics identical to production while native lease evidence stays
// reserved for the real App host.
export function createDesktopTenantAgentDefinitionsQaOperationsV2():
  DesktopTenantAgentDefinitionsOperationsV2 {
  const operations: DesktopTenantAgentDefinitionsOperationsV2 = {
    async loadTenantAgentDefinitions(input) {
      const prepared = prepareDesktopTenantAgentDefinitionsLoadV2(input);
      const authority = createDesktopTenantAgentDefinitionsHttpProjectionV2(prepared.config);
      return requireDesktopTenantAgentDefinitionsV2(
        await authority.load(prepared.scope, prepared.signal),
        prepared.scope,
      );
    },
    async listTenantAgentDefinitionExternalAcpAgents(input) {
      const prepared = prepareDesktopTenantAgentDefinitionsExternalV2(input);
      const authority = createDesktopTenantAgentDefinitionsHttpProjectionV2(prepared.config);
      return requireDesktopTenantAgentDefinitionExternalAcpAgentsV2(
        await authority.listExternal(prepared.scope, prepared.signal),
      );
    },
    async createTenantAgentDefinition(input) {
      const prepared = prepareDesktopTenantAgentDefinitionsCreateV2(input);
      const authority = createDesktopTenantAgentDefinitionsHttpProjectionV2(prepared.config);
      return requireDesktopTenantAgentDefinitionV2(
        await authority.create(prepared.scope, prepared.input, prepared.signal),
        prepared.scope,
      );
    },
    async updateTenantAgentDefinition(input) {
      const prepared = prepareDesktopTenantAgentDefinitionsUpdateV2(input);
      const authority = createDesktopTenantAgentDefinitionsHttpProjectionV2(prepared.config);
      return requireDesktopTenantAgentDefinitionV2(
        await authority.update(
          prepared.scope,
          prepared.definitionId,
          prepared.input,
          prepared.expectedRevision,
          prepared.signal,
        ),
        prepared.scope,
      );
    },
    async setTenantAgentDefinitionEnabled(input) {
      const prepared = prepareDesktopTenantAgentDefinitionsEnabledV2(input);
      const authority = createDesktopTenantAgentDefinitionsHttpProjectionV2(prepared.config);
      return requireDesktopTenantAgentDefinitionV2(
        await authority.setEnabled(
          prepared.scope,
          prepared.definitionId,
          prepared.enabled,
          prepared.expectedRevision,
          prepared.signal,
        ),
        prepared.scope,
      );
    },
    async deleteTenantAgentDefinition(input) {
      const prepared = prepareDesktopTenantAgentDefinitionsDeleteV2(input);
      const authority = createDesktopTenantAgentDefinitionsHttpProjectionV2(prepared.config);
      return requireDesktopTenantAgentDefinitionDeleteV2(
        await authority.delete(
          prepared.scope,
          prepared.definitionId,
          prepared.expectedRevision,
          prepared.signal,
        ),
        prepared.definitionId,
      );
    },
  };
  return Object.freeze(operations);
}
