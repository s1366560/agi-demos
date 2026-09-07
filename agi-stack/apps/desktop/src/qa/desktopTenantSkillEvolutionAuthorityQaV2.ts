import type { DesktopTenantSkillEvolutionOperationsV2 } from '../plugins/desktopTenantSkillEvolutionAuthorityModuleV2';
import { createDesktopTenantSkillEvolutionHttpProjectionV2 } from '../plugins/desktopTenantSkillEvolutionHttpProjectionV2';
import {
  prepareSkillEvolutionInputV2,
  requireSkillEvolutionDetailV2,
  requireSkillEvolutionRunV2,
  type DesktopTenantSkillEvolutionAuthorityV2,
  type SkillEvolutionInputV2,
} from '../plugins/desktopTenantSkillEvolutionOperationContractV2';
import type { SkillInputV2 } from '../plugins/desktopTenantSkillOperationSupportV2';

// Standalone QA shares production contracts and HTTP transport; it does not claim native lease evidence.
export function createDesktopTenantSkillEvolutionQaOperationsV2(): DesktopTenantSkillEvolutionOperationsV2 {
  const run = <T>(
    input: SkillInputV2,
    operation: (authority: DesktopTenantSkillEvolutionAuthorityV2) => Promise<T>,
  ) => operation(createDesktopTenantSkillEvolutionHttpProjectionV2(input.config));
  return Object.freeze({
    getTenantSkillEvolution(input: SkillEvolutionInputV2) {
      const p = prepareSkillEvolutionInputV2(input);
      return run(p, async (a) =>
        requireSkillEvolutionDetailV2(await a.get(p.scope, p.skillId, p.signal), p.skillId),
      );
    },
    runTenantSkillEvolution(input: SkillEvolutionInputV2) {
      const p = prepareSkillEvolutionInputV2(input);
      return run(p, async (a) =>
        requireSkillEvolutionRunV2(await a.run(p.scope, p.skillId, p.signal), p.skillId),
      );
    },
  });
}
