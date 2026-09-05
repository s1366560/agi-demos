import type { DesktopTenantSubAgentDefinitionsOperationsV2 } from '../plugins/desktopTenantSubAgentDefinitionsAuthorityModuleV2';
import { createDesktopTenantSubAgentDefinitionsHttpProjectionV2 } from '../plugins/desktopTenantSubAgentDefinitionsHttpProjectionV2';
import {
  prepareDesktopTenantSubAgentDefinitionsCreateV2,
  prepareDesktopTenantSubAgentDefinitionsDeleteV2,
  prepareDesktopTenantSubAgentDefinitionsEnabledV2,
  prepareDesktopTenantSubAgentDefinitionsImportV2,
  prepareDesktopTenantSubAgentDefinitionsLoadV2,
  prepareDesktopTenantSubAgentDefinitionsUpdateV2,
  requireDesktopTenantSubAgentDefinitionDeleteV2,
  requireDesktopTenantSubAgentDefinitionsV2,
  requireDesktopTenantSubAgentDefinitionV2,
} from '../plugins/desktopTenantSubAgentDefinitionsOperationContractV2';

// Standalone QA pages have no generation host; keep their transport and
// contract semantics identical to production while native lease evidence stays
// reserved for the real App host.
export function createDesktopTenantSubAgentDefinitionsQaOperationsV2(): DesktopTenantSubAgentDefinitionsOperationsV2 {
  const operations: DesktopTenantSubAgentDefinitionsOperationsV2 = {
    async loadTenantSubAgentDefinitions(input) {
      const prepared = prepareDesktopTenantSubAgentDefinitionsLoadV2(input);
      const authority = createDesktopTenantSubAgentDefinitionsHttpProjectionV2(prepared.config);
      return requireDesktopTenantSubAgentDefinitionsV2(
        await authority.load(prepared.scope, prepared.signal),
        prepared.scope,
      );
    },
    async importTenantFilesystemSubAgentDefinition(input) {
      const prepared = prepareDesktopTenantSubAgentDefinitionsImportV2(input);
      const authority = createDesktopTenantSubAgentDefinitionsHttpProjectionV2(prepared.config);
      return requireDesktopTenantSubAgentDefinitionV2(
        await authority.importFilesystem(prepared.scope, prepared.name, prepared.signal),
        prepared.scope,
      );
    },
    async createTenantSubAgentDefinition(input) {
      const prepared = prepareDesktopTenantSubAgentDefinitionsCreateV2(input);
      const authority = createDesktopTenantSubAgentDefinitionsHttpProjectionV2(prepared.config);
      return requireDesktopTenantSubAgentDefinitionV2(
        await authority.create(prepared.scope, prepared.input, prepared.signal),
        prepared.scope,
      );
    },
    async updateTenantSubAgentDefinition(input) {
      const prepared = prepareDesktopTenantSubAgentDefinitionsUpdateV2(input);
      const authority = createDesktopTenantSubAgentDefinitionsHttpProjectionV2(prepared.config);
      return requireDesktopTenantSubAgentDefinitionV2(
        await authority.update(
          prepared.scope,
          prepared.definitionId,
          prepared.input,
          prepared.expectedRevision,
          prepared.signal,
        ),
        prepared.scope,
        prepared.definitionId,
      );
    },
    async setTenantSubAgentDefinitionEnabled(input) {
      const prepared = prepareDesktopTenantSubAgentDefinitionsEnabledV2(input);
      const authority = createDesktopTenantSubAgentDefinitionsHttpProjectionV2(prepared.config);
      return requireDesktopTenantSubAgentDefinitionV2(
        await authority.setEnabled(
          prepared.scope,
          prepared.definitionId,
          prepared.enabled,
          prepared.expectedRevision,
          prepared.signal,
        ),
        prepared.scope,
        prepared.definitionId,
      );
    },
    async deleteTenantSubAgentDefinition(input) {
      const prepared = prepareDesktopTenantSubAgentDefinitionsDeleteV2(input);
      const authority = createDesktopTenantSubAgentDefinitionsHttpProjectionV2(prepared.config);
      return requireDesktopTenantSubAgentDefinitionDeleteV2(
        await authority.delete(
          prepared.scope,
          prepared.definitionId,
          prepared.expectedRevision,
          prepared.signal,
        ),
      );
    },
  };
  return Object.freeze(operations);
}
