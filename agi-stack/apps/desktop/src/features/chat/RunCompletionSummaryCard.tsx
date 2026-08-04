import {
  ArchiveIcon,
  CheckCircledIcon,
  ChevronRightIcon,
  CodeIcon,
  CrossCircledIcon,
  ExclamationTriangleIcon,
  FileTextIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import { formatElapsedClock } from '../session/currentActivityModel';
import type {
  RunCompletionSummary,
  RunCompletionSummaryLink,
} from '../session/runCompletionSummaryModel';
import type { SessionCanvasTabId } from '../session/sessionCanvasModel';
import { formatTokenCount } from '../session/sessionUsageModel';
import './RunCompletionSummaryCard.css';

type RunCompletionSummaryCardProps = {
  summary: RunCompletionSummary;
  onOpenTab: (tab: SessionCanvasTabId) => void;
};

const OUTCOME_ICONS = {
  completed: CheckCircledIcon,
  failed: CrossCircledIcon,
  cancelled: ExclamationTriangleIcon,
} as const;

/**
 * Durable run-completion summary rendered at the tail of the timeline. Every
 * section that makes a claim links to the canvas holding the inspectable
 * evidence; sections without data are omitted by the model.
 */
export function RunCompletionSummaryCard({ summary, onOpenTab }: RunCompletionSummaryCardProps) {
  const { t } = useI18n();
  const OutcomeIcon = OUTCOME_ICONS[summary.outcome];

  const evidenceLink = (link: RunCompletionSummaryLink, className: string) => (
    <button
      type="button"
      className={className}
      aria-label={t('session.openCanvasTab', { label: t(link.labelKey) })}
      onClick={() => onOpenTab(link.tab)}
    >
      {t(link.labelKey)} <ChevronRightIcon aria-hidden="true" />
    </button>
  );

  return (
    <section
      className={`run-completion-card outcome-${summary.outcome}`}
      aria-label={t('session.runSummary.title')}
    >
      <header>
        <span className="run-completion-icon" aria-hidden="true">
          <OutcomeIcon />
        </span>
        <div className="run-completion-heading">
          <small>{t('session.runSummary.eyebrow')}</small>
          <strong>{t('session.runSummary.title')}</strong>
        </div>
        <em className={`run-completion-outcome tone-${summary.outcome}`}>
          {t(summary.outcomeLabelKey)}
        </em>
      </header>

      <div className="run-completion-body">
        {summary.durationMs !== null || summary.usage ? (
          <div className="run-completion-meta">
            {summary.durationMs !== null ? (
              <span>
                {t('session.runSummary.duration', {
                  duration: formatElapsedClock(summary.durationMs),
                })}
              </span>
            ) : null}
            {summary.usage ? (
              <span>
                {t('session.runSummary.contextUsage', {
                  tokens: formatTokenCount(summary.usage.currentTokens),
                  percent: summary.usage.occupancyPct.toFixed(1),
                })}
              </span>
            ) : null}
          </div>
        ) : null}

        {summary.changes ? (
          <section className="run-completion-section" aria-label={t('session.canvasChanges')}>
            <div className="run-completion-section-head">
              <CodeIcon aria-hidden="true" />
              <strong>{t('session.canvasChanges')}</strong>
            </div>
            <div className="run-completion-changes-stat">
              <span>
                {t('session.runSummary.filesChanged', { count: summary.changes.filesChanged })}
              </span>
              <span className="run-completion-diff additions">+{summary.changes.additions}</span>
              <span className="run-completion-diff deletions">−{summary.changes.deletions}</span>
              {summary.changes.truncated ? (
                <span className="run-completion-truncated">{t('chat.truncated')}</span>
              ) : null}
            </div>
            {summary.changes.link
              ? evidenceLink(summary.changes.link, 'run-completion-link')
              : null}
          </section>
        ) : null}

        {summary.artifacts ? (
          <section className="run-completion-section" aria-label={t('session.canvasArtifacts')}>
            <div className="run-completion-section-head">
              <ArchiveIcon aria-hidden="true" />
              <strong>{t('session.canvasArtifacts')}</strong>
              <small>
                {t('session.runSummary.artifactCount', { count: summary.artifacts.totalCount })}
              </small>
            </div>
            <ul className="run-completion-artifact-list">
              {summary.artifacts.entries.map((entry) => (
                <li key={entry.versionId}>
                  <FileTextIcon aria-hidden="true" />
                  <span title={entry.title}>{entry.title}</span>
                  <em>{entry.mimeType}</em>
                </li>
              ))}
            </ul>
            {summary.artifacts.totalCount > summary.artifacts.entries.length ? (
              <small className="run-completion-more">
                {t('session.runSummary.moreArtifacts', {
                  count: summary.artifacts.totalCount - summary.artifacts.entries.length,
                })}
              </small>
            ) : null}
            {summary.artifacts.link
              ? evidenceLink(summary.artifacts.link, 'run-completion-link')
              : null}
          </section>
        ) : null}

        {summary.verification ? (
          <section
            className="run-completion-section"
            aria-label={t(summary.verification.link.labelKey)}
          >
            <div className="run-completion-section-head">
              <CheckCircledIcon aria-hidden="true" />
              <strong>{t(summary.verification.link.labelKey)}</strong>
            </div>
            <div className="run-completion-verification-stat">
              <span className={summary.verification.failedCount ? 'tone-danger' : 'tone-success'}>
                {t('session.runSummary.checksPassed', {
                  passed: summary.verification.passedCount,
                  total: summary.verification.total,
                })}
              </span>
              {summary.verification.failedCount ? (
                <span className="tone-danger">
                  {t('session.runSummary.checksFailed', {
                    count: summary.verification.failedCount,
                  })}
                </span>
              ) : null}
              {summary.verification.pendingCount ? (
                <span className="tone-warning">
                  {t('session.runSummary.checksPending', {
                    count: summary.verification.pendingCount,
                  })}
                </span>
              ) : null}
            </div>
            {evidenceLink(summary.verification.link, 'run-completion-link run-completion-evidence')}
          </section>
        ) : null}

        {summary.failureReason ? (
          <section
            className="run-completion-section run-completion-failure"
            aria-label={t('session.runSummary.failureTitle')}
          >
            <div className="run-completion-section-head">
              <ExclamationTriangleIcon aria-hidden="true" />
              <strong>{t('session.runSummary.failureTitle')}</strong>
            </div>
            <p>{summary.failureReason}</p>
          </section>
        ) : null}
      </div>
    </section>
  );
}
