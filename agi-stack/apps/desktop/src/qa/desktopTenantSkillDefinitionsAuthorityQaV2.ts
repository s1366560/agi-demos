import type { DesktopTenantSkillDefinitionsOperationsV2 } from '../plugins/desktopTenantSkillDefinitionsAuthorityModuleV2';
import { createDesktopTenantSkillDefinitionsHttpProjectionV2 } from '../plugins/desktopTenantSkillDefinitionsHttpProjectionV2';
import {
  prepareDesktopTenantSkillDefinitionsLoadV2,
  prepareDesktopTenantSkillDefinitionsItemV2,
  prepareDesktopTenantSkillDefinitionsCreateV2,
  prepareDesktopTenantSkillDefinitionsUpdateV2,
  prepareDesktopTenantSkillDefinitionsContentV2,
  prepareDesktopTenantSkillDefinitionsStatusV2,
  requireDesktopTenantSkillDefinitionsV2,
  requireDesktopTenantSkillDefinitionV2,
  requireDesktopTenantSkillContentV2,
  requireDesktopTenantSkillDeletionV2,
} from '../plugins/desktopTenantSkillDefinitionsOperationContractV2';

// Standalone QA has no generation host. Exercise production transport and
// contracts without presenting this path as Loader or native lease evidence.
export function createDesktopTenantSkillDefinitionsQaOperationsV2(): DesktopTenantSkillDefinitionsOperationsV2 {
  const operations: DesktopTenantSkillDefinitionsOperationsV2 = {
    async loadTenantSkillDefinitions(input) {
      const p = prepareDesktopTenantSkillDefinitionsLoadV2(input);
      const a = createDesktopTenantSkillDefinitionsHttpProjectionV2(p.config);
      return requireDesktopTenantSkillDefinitionsV2(await a.load(p.scope, p.signal), p.scope);
    },
    async createTenantSkillDefinition(input) {
      const p = prepareDesktopTenantSkillDefinitionsCreateV2(input);
      const a = createDesktopTenantSkillDefinitionsHttpProjectionV2(p.config);
      return requireDesktopTenantSkillDefinitionV2(
        await a.create(p.scope, p.input, p.signal),
        p.scope,
        undefined,
        p.input.scope,
      );
    },
    async getTenantSkillContent(input) {
      const p = prepareDesktopTenantSkillDefinitionsItemV2(input);
      const a = createDesktopTenantSkillDefinitionsHttpProjectionV2(p.config);
      return requireDesktopTenantSkillContentV2(
        await a.getContent(p.scope, p.skillId, p.signal),
        p.skillId,
      );
    },
    async updateTenantSkillDefinition(input) {
      const p = prepareDesktopTenantSkillDefinitionsUpdateV2(input);
      const a = createDesktopTenantSkillDefinitionsHttpProjectionV2(p.config);
      return requireDesktopTenantSkillDefinitionV2(
        await a.update(p.scope, p.skillId, p.input, p.expectedRevision, p.signal),
        p.scope,
        p.skillId,
      );
    },
    async updateTenantSkillContent(input) {
      const p = prepareDesktopTenantSkillDefinitionsContentV2(input);
      const a = createDesktopTenantSkillDefinitionsHttpProjectionV2(p.config);
      return requireDesktopTenantSkillDefinitionV2(
        await a.updateContent(p.scope, p.skillId, p.fullContent, p.expectedRevision, p.signal),
        p.scope,
        p.skillId,
      );
    },
    async setTenantSkillStatus(input) {
      const p = prepareDesktopTenantSkillDefinitionsStatusV2(input);
      const a = createDesktopTenantSkillDefinitionsHttpProjectionV2(p.config);
      return requireDesktopTenantSkillDefinitionV2(
        await a.setStatus(p.scope, p.skillId, p.status, p.expectedRevision, p.signal),
        p.scope,
        p.skillId,
      );
    },
    async deleteTenantSkillDefinition(input) {
      const p = prepareDesktopTenantSkillDefinitionsItemV2(input);
      const a = createDesktopTenantSkillDefinitionsHttpProjectionV2(p.config);
      requireDesktopTenantSkillDeletionV2(
        await a.delete(p.scope, p.skillId, p.expectedRevision, p.signal),
      );
    },
  };
  return Object.freeze(operations);
}
