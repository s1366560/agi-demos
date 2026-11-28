import type {
  DesktopRuntimeConfig,
  ManagedSkillEvolutionDetail,
  ManagedSkillEvolutionRun,
} from '../types';
import type { DesktopTenantSkillEvolutionAuthorityV2 } from './desktopTenantSkillEvolutionOperationContractV2';
import {
  freezeSkillConfigV2,
  prepareSkillInputV2,
  requestSkillJsonV2,
  skillErrorV2,
  skillIdentifierV2,
  type SkillScopeV2,
} from './desktopTenantSkillOperationSupportV2';
export function createDesktopTenantSkillEvolutionHttpProjectionV2(
  config: DesktopRuntimeConfig,
): DesktopTenantSkillEvolutionAuthorityV2 {
  const runtime = freezeSkillConfigV2(config);
  const path = (scope: SkillScopeV2, skillId: string, suffix: string) => {
    prepareSkillInputV2({ config: runtime, scope });
    if (runtime.mode === 'local')
      throw skillErrorV2('local_skill_evolution_authority_unavailable', 501);
    return `/api/v1/skills/${encodeURIComponent(skillIdentifierV2(skillId))}/evolution${suffix}?${new URLSearchParams({ tenant_id: scope.tenantId })}`;
  };
  const authority: DesktopTenantSkillEvolutionAuthorityV2 = {
    async get(scope, skillId, signal) {
      return (await requestSkillJsonV2(runtime, path(scope, skillId, ''), {
        signal,
      })) as ManagedSkillEvolutionDetail;
    },
    async run(scope, skillId, signal) {
      return (await requestSkillJsonV2(runtime, path(scope, skillId, '/run'), {
        method: 'POST',
        signal,
      })) as ManagedSkillEvolutionRun;
    },
  };
  return Object.freeze(authority);
}
