import type { ManagedSkillEvolutionDetail, ManagedSkillEvolutionRun } from '../types';
import {
  freezeSkillJsonV2,
  prepareSkillInputV2,
  skillErrorV2,
  skillIdentifierV2,
  skillRecordV2,
  type SkillInputV2,
  type SkillScopeV2,
} from './desktopTenantSkillOperationSupportV2';
export type SkillEvolutionInputV2 = SkillInputV2 & Readonly<{ skillId: string }>;
export interface DesktopTenantSkillEvolutionAuthorityV2 {
  get(
    scope: SkillScopeV2,
    skillId: string,
    signal?: AbortSignal,
  ): Promise<ManagedSkillEvolutionDetail>;
  run(
    scope: SkillScopeV2,
    skillId: string,
    signal?: AbortSignal,
  ): Promise<ManagedSkillEvolutionRun>;
}
export function prepareSkillEvolutionInputV2(input: SkillEvolutionInputV2): SkillEvolutionInputV2 {
  return Object.freeze({
    ...prepareSkillInputV2(input),
    skillId: skillIdentifierV2(input.skillId),
  });
}
export function requireSkillEvolutionDetailV2(
  value: unknown,
  skillId: string,
): ManagedSkillEvolutionDetail {
  if (
    !skillRecordV2(value) ||
    value.skill_id !== skillId ||
    typeof value.skill_name !== 'string' ||
    !Number.isSafeInteger(value.captured_session_count) ||
    Number(value.captured_session_count) < 0 ||
    !Array.isArray(value.jobs) ||
    value.jobs.some((item) => !skillRecordV2(item)) ||
    !Array.isArray(value.route) ||
    value.route.some((item) => !skillRecordV2(item)) ||
    !skillRecordV2(value.trigger)
  )
    throw skillErrorV2('tenant_skill_evolution_response_invalid', 502);
  return freezeSkillJsonV2(value) as unknown as ManagedSkillEvolutionDetail;
}
export function requireSkillEvolutionRunV2(
  value: unknown,
  skillId: string,
): ManagedSkillEvolutionRun {
  if (
    !skillRecordV2(value) ||
    value.skill_id !== skillId ||
    typeof value.skill_name !== 'string' ||
    !skillRecordV2(value.result)
  )
    throw skillErrorV2('tenant_skill_evolution_response_invalid', 502);
  return freezeSkillJsonV2(value) as unknown as ManagedSkillEvolutionRun;
}
