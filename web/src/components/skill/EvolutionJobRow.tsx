/**
 * Shared evolution route / job row.
 *
 * Renders both `version` and `evolution_job` entries with apply/reject
 * actions (Popconfirm-guarded). Used by the skill detail page (evolution
 * route) and the skill evolution page (recent jobs).
 */

import { useTranslation } from 'react-i18next';

import { Tag } from 'antd';
import { CheckCircle2, GitBranch, History, XCircle } from 'lucide-react';

import { formatDateTime } from '@/utils/date';

import { LazyPopconfirm } from '@/components/ui/lazyAntd';


import type { SkillEvolutionRouteEntry } from '@/types/agent';

const pageText = 'text-[oklch(0.24_0.01_255)] dark:text-[oklch(0.94_0.006_255)]';
const mutedText = 'text-[oklch(0.48_0.01_255)] dark:text-[oklch(0.68_0.008_255)]';
const actionButton =
  'inline-flex h-9 items-center justify-center gap-2 rounded-[4px] border border-[oklch(0.86_0.006_255)] px-3 text-sm font-medium text-[oklch(0.34_0.01_255)] transition-colors hover:bg-[oklch(0.95_0.005_255)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] disabled:cursor-not-allowed disabled:opacity-60 dark:border-[oklch(0.34_0.006_255)] dark:text-[oklch(0.82_0.006_255)] dark:hover:bg-[oklch(0.24_0.006_255)]';

interface EvolutionJobRowProps {
  entry: SkillEvolutionRouteEntry;
  isProcessing: boolean;
  onApply: (jobId: string) => void;
  onReject: (jobId: string) => void;
  /** Optional scope label (e.g. tenant/project) shown as an extra tag. */
  scopeLabel?: string | undefined;
  /** Optional number of source sessions, appended to the meta line. */
  sessionCount?: number | undefined;
}

export function EvolutionJobRow({
  entry,
  isProcessing,
  onApply,
  onReject,
  scopeLabel,
  sessionCount,
}: EvolutionJobRowProps) {
  const isVersion = entry.kind === 'version';
  const { t } = useTranslation();
  const actionable = entry.kind === 'evolution_job' && entry.status === 'pending_review';
  return (
    <div className="py-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div
            className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-[4px] ${
              isVersion
                ? 'bg-[oklch(0.9_0.08_145)] text-[oklch(0.35_0.1_145)] dark:bg-[oklch(0.24_0.05_145)] dark:text-[oklch(0.78_0.09_145)]'
                : 'bg-[oklch(0.91_0.05_255)] text-[oklch(0.38_0.1_255)] dark:bg-[oklch(0.24_0.04_255)] dark:text-[oklch(0.76_0.08_255)]'
            }`}
          >
            {isVersion ? <History size={15} /> : <GitBranch size={15} />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`text-sm font-semibold ${pageText}`}>{entry.label}</span>
              <Tag>
                {isVersion
                  ? 'version'
                  : t(
                      `tenant.skillEvolution.jobActions.${entry.action ?? ''}`,
                      entry.action ?? ''
                    )}
              </Tag>
              {entry.status ? (
                <Tag color={entry.status === 'applied' ? 'success' : 'default'}>
                  {t(`tenant.skillEvolution.jobStatuses.${entry.status}`, entry.status)}
                </Tag>
              ) : null}
              {scopeLabel ? <Tag>{scopeLabel}</Tag> : null}
            </div>
            {entry.change_summary || entry.rationale ? (
              <div className={`mt-1 line-clamp-3 text-sm ${mutedText}`}>
                {entry.change_summary ?? entry.rationale}
              </div>
            ) : null}
            <div className={`mt-1 text-xs ${mutedText}`}>
              {entry.created_by ? `${entry.created_by} · ` : ''}
              {formatDateTime(entry.created_at)}
              {sessionCount !== undefined
                ? ` · ${t('tenant.skillEvolution.units.sessions', { count: sessionCount })}`
                : ''}
            </div>
            {entry.candidate_preview ? (
              <pre className="mt-2 max-h-36 overflow-auto rounded-[4px] border border-[oklch(0.88_0.006_255)] bg-[oklch(0.96_0.004_255)] p-3 text-xs leading-5 text-[oklch(0.28_0.01_255)] dark:border-[oklch(0.3_0.006_255)] dark:bg-[oklch(0.14_0.006_255)] dark:text-[oklch(0.84_0.006_255)]">
                {entry.candidate_preview}
              </pre>
            ) : null}
          </div>
        </div>
        {actionable ? (
          <div className="flex shrink-0 gap-2">
            <LazyPopconfirm
              title={t('tenant.skillEvolution.jobs.applyConfirm')}
              okText={t('common.confirm')}
              cancelText={t('common.cancel')}
              onConfirm={() => {
                onApply(entry.id);
              }}
            >
              <button type="button" disabled={isProcessing} className={actionButton}>
                <CheckCircle2 size={14} />
                {t('tenant.skillEvolution.jobs.apply')}
              </button>
            </LazyPopconfirm>
            <LazyPopconfirm
              title={t('tenant.skillEvolution.jobs.rejectConfirm')}
              okText={t('common.confirm')}
              cancelText={t('common.cancel')}
              onConfirm={() => {
                onReject(entry.id);
              }}
            >
              <button type="button" disabled={isProcessing} className={actionButton}>
                <XCircle size={14} />
                {t('tenant.skillEvolution.jobs.reject')}
              </button>
            </LazyPopconfirm>
          </div>
        ) : null}
      </div>
    </div>
  );
}
