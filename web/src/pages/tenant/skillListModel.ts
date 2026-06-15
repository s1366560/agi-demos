import type { SkillResponse } from '@/types/agent';

export type TenantSkillConfigAction = 'disable' | 'override';

export function getSystemSkillConfigAction(
  skill: SkillResponse,
  configBySystemSkillName: Map<string, TenantSkillConfigAction>
): TenantSkillConfigAction | null {
  if (!skill.is_system_skill) {
    return null;
  }
  return configBySystemSkillName.get(skill.name) ?? null;
}
