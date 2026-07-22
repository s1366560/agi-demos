/**
 * Shared skill version list with rollback actions.
 *
 * Used by the skill detail page (versions aside) and the skill list page
 * (versions modal) so both surfaces render identical rows and behavior.
 */

import { useTranslation } from 'react-i18next';

import { Tag } from 'antd';
import { RotateCcw } from 'lucide-react';

import { formatDateTime } from '@/utils/date';

import { LazyEmpty, LazyPopconfirm } from '@/components/ui/lazyAntd';

import type { SkillVersionResponse } from '@/types/agent';

const pageText = 'text-[oklch(0.24_0.01_255)] dark:text-[oklch(0.94_0.006_255)]';
const mutedText = 'text-[oklch(0.48_0.01_255)] dark:text-[oklch(0.68_0.008_255)]';

interface SkillVersionListProps {
  versions: SkillVersionResponse[];
  currentVersion: number | undefined;
  rollbackVersion: number | null;
  emptyDescription: string;
  onRollback: (versionNumber: number) => void;
}

export function SkillVersionList({
  versions,
  currentVersion,
  rollbackVersion,
  emptyDescription,
  onRollback,
}: SkillVersionListProps) {
  const { t } = useTranslation();

  if (versions.length === 0) {
    return (
      <div className="py-8">
        <LazyEmpty description={emptyDescription} />
      </div>
    );
  }

  return (
    <div className="divide-y divide-[oklch(0.9_0.006_255)] dark:divide-[oklch(0.28_0.006_255)]">
      {versions.map((version) => {
        const isCurrent = currentVersion === version.version_number;
        return (
          <div key={version.id} className="py-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`text-sm font-semibold ${pageText}`}>
                    {version.version_label ?? `#${String(version.version_number)}`}
                  </span>
                  <span className={`text-xs ${mutedText}`}>#{version.version_number}</span>
                  {isCurrent ? (
                    <Tag color="success">{t('tenant.skills.versions.current')}</Tag>
                  ) : null}
                </div>
                {version.change_summary ? (
                  <div className={`mt-1 text-sm ${mutedText}`}>{version.change_summary}</div>
                ) : null}
                <div className={`mt-1 text-xs ${mutedText}`}>
                  {t('tenant.skills.versions.createdBy', {
                    author: version.created_by,
                    date: formatDateTime(version.created_at),
                  })}
                </div>
              </div>
              {!isCurrent ? (
                <LazyPopconfirm
                  title={t('tenant.skills.versions.rollbackConfirm')}
                  okText={t('common.confirm')}
                  cancelText={t('common.cancel')}
                  onConfirm={() => {
                    onRollback(version.version_number);
                  }}
                >
                  <button
                    type="button"
                    className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-[4px] text-[oklch(0.48_0.01_255)] transition-colors hover:bg-[oklch(0.95_0.005_255)] hover:text-[oklch(0.26_0.012_255)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] disabled:cursor-not-allowed disabled:opacity-60 dark:text-[oklch(0.7_0.008_255)] dark:hover:bg-[oklch(0.24_0.006_255)]"
                    title={t('tenant.skills.versions.rollback')}
                    aria-label={t('tenant.skills.versions.rollback')}
                    disabled={rollbackVersion !== null}
                  >
                    <RotateCcw size={15} />
                  </button>
                </LazyPopconfirm>
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}
