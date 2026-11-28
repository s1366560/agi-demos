/**
 * Steps, calls, tokens and cost of a finished answer, shown above it in the
 * transcript of the original workbench and of the signed chat page.
 */

import type React from 'react';

import { useTranslation } from 'react-i18next';

import { useLocaleNumberFormat } from '@/i18n/formatters';
import { normalizeExecutionSummary } from '@/utils/executionSummary';

const COUNT_FORMATTER_FALLBACK = new Intl.NumberFormat('en-US');
const SUMMARY_PILL_CLASSES =
  'inline-flex items-center gap-1 rounded-full border border-slate-200/60 bg-slate-50/80 px-2.5 py-1 text-xs text-neutral-600 dark:border-slate-800/60 dark:bg-slate-800/50';

const formatCount = (
  value: number,
  formatter: Intl.NumberFormat = COUNT_FORMATTER_FALLBACK
): string => formatter.format(value);

const SummaryPill: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <span className={SUMMARY_PILL_CLASSES}>
    <span className="text-neutral-500">{label}</span>
    <span className="font-medium text-neutral-800">{value}</span>
  </span>
);

export const ExecutionSummaryPanel: React.FC<{
  summary: ReturnType<typeof normalizeExecutionSummary>;
}> = ({ summary }) => {
  const { t } = useTranslation();
  const countFormatter = useLocaleNumberFormat();
  if (!summary) {
    return null;
  }

  const taskSummary = summary.tasks;
  const hasVisibleSummary =
    summary.stepCount > 0 ||
    summary.artifactCount > 0 ||
    summary.callCount > 0 ||
    summary.totalTokens.total > 0 ||
    Boolean(taskSummary && taskSummary.total > 0);
  if (!hasVisibleSummary) {
    return null;
  }

  return (
    <div className="mb-3 flex flex-wrap gap-2">
      {summary.stepCount > 0 ? (
        <SummaryPill
          label={t('agent.messageBubble.pill.steps', 'Steps')}
          value={formatCount(summary.stepCount, countFormatter)}
        />
      ) : null}
      {taskSummary ? (
        <SummaryPill
          label={t('agent.messageBubble.pill.tasks', 'Tasks')}
          value={`${formatCount(taskSummary.completed, countFormatter)}/${formatCount(taskSummary.total, countFormatter)}`}
        />
      ) : null}
      {taskSummary && taskSummary.remaining > 0 ? (
        <SummaryPill
          label={t('agent.messageBubble.pill.remaining', 'Remaining')}
          value={formatCount(taskSummary.remaining, countFormatter)}
        />
      ) : null}
      {summary.artifactCount > 0 ? (
        <SummaryPill
          label={t('agent.messageBubble.pill.artifacts', 'Artifacts')}
          value={formatCount(summary.artifactCount, countFormatter)}
        />
      ) : null}
      {summary.callCount > 0 ? (
        <SummaryPill
          label={t('agent.messageBubble.pill.llmCalls', 'LLM calls')}
          value={formatCount(summary.callCount, countFormatter)}
        />
      ) : null}
      {summary.totalTokens.total > 0 ? (
        <SummaryPill
          label={t('agent.messageBubble.pill.tokens', 'Tokens')}
          value={formatCount(summary.totalTokens.total, countFormatter)}
        />
      ) : null}
      {summary.totalCost > 0 ? (
        <SummaryPill
          label={t('agent.messageBubble.pill.cost', 'Cost')}
          value={summary.totalCostFormatted}
        />
      ) : null}
    </div>
  );
};
