/**
 * Shared Skill helpers: source/managed predicates, package export (download),
 * and the version rollback flow used by both the skill list and detail pages.
 */

import { useCallback, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { skillAPI } from '@/services/skillService';

import { useLazyMessage } from '@/components/ui/lazyAntd';

import type { SkillResponse } from '@/types/agent';

export type SkillSource = NonNullable<SkillResponse['source']>;

export function getSkillSource(skill: SkillResponse): SkillSource {
  return skill.source ?? 'database';
}

export function isManagedSkill(skill: SkillResponse): boolean {
  const source = getSkillSource(skill);
  return !skill.is_system_skill && (source === 'database' || source === 'hybrid');
}

/** Filesystem-backed skills are addressed by name; database skills by id. */
export function getSkillExportId(skill: SkillResponse): string {
  return getSkillSource(skill) === 'filesystem' ? skill.name : skill.id;
}

/**
 * Export the skill package and trigger a browser download.
 * Throws when the export request fails so callers can surface an error.
 */
export async function downloadSkillPackage(skill: SkillResponse, tenantId: string): Promise<void> {
  const exported = await skillAPI.exportPackage(getSkillExportId(skill), { tenant_id: tenantId });
  const blob = new Blob([JSON.stringify(exported, null, 2)], {
    type: 'application/json',
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${skill.name}.agentskill.json`;
  link.click();
  URL.revokeObjectURL(url);
}

interface UseSkillRollbackOptions {
  tenantId: string | null;
  /** Called with the updated skill after a successful rollback (e.g. to reload data). */
  onRolledBack?: ((updated: SkillResponse) => void | Promise<void>) | undefined;
}

/**
 * Shared rollback flow for skill versions: tracks the in-flight version number
 * and shows success/error feedback. Callers keep their own reload logic in
 * `onRolledBack`.
 */
export function useSkillRollback({ tenantId, onRolledBack }: UseSkillRollbackOptions): {
  rollbackVersion: number | null;
  rollback: (skill: SkillResponse, versionNumber: number) => Promise<void>;
} {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const [rollbackVersion, setRollbackVersion] = useState<number | null>(null);

  const rollback = useCallback(
    async (skill: SkillResponse, versionNumber: number) => {
      if (!tenantId) {
        return;
      }
      setRollbackVersion(versionNumber);
      try {
        const updated = await skillAPI.rollback(skill.id, versionNumber, {
          tenant_id: tenantId,
        });
        message?.success(t('tenant.skills.versions.rollbackSuccess'));
        await onRolledBack?.(updated);
      } catch {
        message?.error(t('tenant.skills.versions.rollbackFailed'));
      } finally {
        setRollbackVersion(null);
      }
    },
    [message, onRolledBack, t, tenantId]
  );

  return { rollbackVersion, rollback };
}
