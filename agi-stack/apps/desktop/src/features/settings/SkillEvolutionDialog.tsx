import { useRef, useState } from 'react';
import {
  CheckIcon,
  Cross2Icon,
  ExclamationTriangleIcon,
  ReloadIcon,
  RocketIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { ManagedSkill, ManagedSkillEvolutionDetail } from '../../types';
import { useModalDialog } from './useModalDialog';

import './AgentDefinitionEditorDialog.css';
import './SkillEvolutionDialog.css';

type EvolutionDecision = { jobId: string; action: 'apply' | 'reject' } | null;

export function SkillEvolutionDialog({
  skill,
  detail,
  loading,
  running,
  processingJobId,
  canManage,
  error,
  onClose,
  onRun,
  onProcessJob,
}: {
  skill: ManagedSkill;
  detail: ManagedSkillEvolutionDetail | null;
  loading: boolean;
  running: boolean;
  processingJobId: string | null;
  canManage: boolean;
  error: string | null;
  onClose: () => void;
  onRun: () => void;
  onProcessJob: (jobId: string, action: 'apply' | 'reject') => void;
}) {
  const { locale, t } = useI18n();
  const [decision, setDecision] = useState<EvolutionDecision>(null);
  const runButtonRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useModalDialog({
    active: true,
    initialFocusRef: runButtonRef,
    nested: true,
    onClose,
  });
  const busy = running || processingJobId !== null;

  return (
    <div
      className="agent-definition-dialog-backdrop"
      role="presentation"
      onMouseDown={() => {
        if (!busy) onClose();
      }}
    >
      <section
        ref={dialogRef}
        className="agent-definition-dialog skill-evolution-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={t('settings.skillEvolution.title', { name: skill.name })}
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="agent-definition-dialog-heading">
          <div className="agent-definition-dialog-icon skill-evolution-icon">
            <RocketIcon />
          </div>
          <div>
            <span>{t('settings.skillsEyebrow')}</span>
            <h2>{t('settings.skillEvolution.title', { name: skill.name })}</h2>
            <p>{t('settings.skillEvolution.description')}</p>
          </div>
          <button
            type="button"
            className="agent-definition-dialog-close"
            aria-label={t('common.close')}
            disabled={busy}
            onClick={onClose}
          >
            <Cross2Icon />
          </button>
        </header>

        <div className="agent-definition-dialog-body skill-evolution-body">
          <div className="skill-evolution-toolbar">
            <div>
              <strong>{t('settings.skillEvolution.route')}</strong>
              <span>{t('settings.skillEvolution.routeDescription')}</span>
            </div>
            {canManage ? (
              <button
                ref={runButtonRef}
                type="button"
                className="skill-evolution-run"
                disabled={busy || loading}
                onClick={onRun}
              >
                {running ? <ReloadIcon className="managed-resource-spin" /> : <RocketIcon />}
                {t(running ? 'settings.skillEvolution.running' : 'settings.skillEvolution.run')}
              </button>
            ) : null}
          </div>

          {loading ? (
            <div className="skill-evolution-state">
              <ReloadIcon className="managed-resource-spin" />
              <span>{t('settings.skillEvolution.loading')}</span>
            </div>
          ) : null}

          {!loading && detail ? (
            <>
              <section className="skill-evolution-metrics">
                <EvolutionMetric
                  label={t('settings.skillEvolution.capturedSessions')}
                  value={String(detail.captured_session_count)}
                />
                <EvolutionMetric
                  label={t('settings.skillEvolution.captureHook')}
                  value={detail.trigger.capture_hook}
                />
                <EvolutionMetric
                  label={t('settings.skillEvolution.threshold')}
                  value={
                    `${detail.trigger.min_sessions_per_skill} / ${detail.trigger.min_avg_score}`
                  }
                />
              </section>

              <section className="skill-evolution-schedule">
                <span>{detail.trigger.capture_timing}</span>
                <span>{detail.trigger.scheduled_timing}</span>
                <em>
                  {t(
                    detail.trigger.enabled
                      ? 'settings.skillEvolution.enabled'
                      : 'settings.skillEvolution.disabled'
                  )}
                </em>
              </section>

              <section className="skill-evolution-route">
                {detail.route.length === 0 ? (
                  <div className="skill-evolution-state">
                    <RocketIcon />
                    <span>{t('settings.skillEvolution.empty')}</span>
                  </div>
                ) : (
                  detail.route.map((entry) => {
                    const pending =
                      entry.kind === 'evolution_job' && entry.status === 'pending_review';
                    const processing = processingJobId === entry.id;
                    return (
                      <article key={`${entry.kind}:${entry.id}`}>
                        <div className={`skill-evolution-node ${entry.kind}`}>
                          {entry.kind === 'version' ? <CheckIcon /> : <RocketIcon />}
                        </div>
                        <div className="skill-evolution-entry-copy">
                          <div>
                            <strong>{entry.label}</strong>
                            <span
                              className={`skill-evolution-status ${entry.status ?? 'version'}`}
                            >
                              {t(
                                `settings.skillEvolution.status.${entry.status ?? 'version'}`
                              )}
                            </span>
                          </div>
                          <p>
                            {entry.candidate_preview ||
                              entry.rationale ||
                              entry.change_summary ||
                              t('settings.skillEvolution.noDetail')}
                          </p>
                          <small>{formatEvolutionDate(entry.created_at, locale)}</small>
                        </div>
                        {pending && canManage ? (
                          <div className="skill-evolution-entry-actions">
                            {decision?.jobId === entry.id ? (
                              <div className="skill-evolution-confirm">
                                <span>
                                  {t(
                                    decision.action === 'apply'
                                      ? 'settings.skillEvolution.applyConfirm'
                                      : 'settings.skillEvolution.rejectConfirm'
                                  )}
                                </span>
                                <button
                                  type="button"
                                  disabled={busy}
                                  onClick={() => setDecision(null)}
                                >
                                  {t('common.cancel')}
                                </button>
                                <button
                                  type="button"
                                  className={decision.action}
                                  disabled={busy}
                                  onClick={() => {
                                    onProcessJob(entry.id, decision.action);
                                    setDecision(null);
                                  }}
                                >
                                  {processing ? (
                                    <ReloadIcon className="managed-resource-spin" />
                                  ) : null}
                                  {t(`settings.skillEvolution.${decision.action}`)}
                                </button>
                              </div>
                            ) : (
                              <>
                                <button
                                  type="button"
                                  className="apply"
                                  disabled={busy}
                                  onClick={() => setDecision({ jobId: entry.id, action: 'apply' })}
                                >
                                  {t('settings.skillEvolution.apply')}
                                </button>
                                <button
                                  type="button"
                                  className="reject"
                                  disabled={busy}
                                  onClick={() => setDecision({ jobId: entry.id, action: 'reject' })}
                                >
                                  {t('settings.skillEvolution.reject')}
                                </button>
                              </>
                            )}
                          </div>
                        ) : null}
                      </article>
                    );
                  })
                )}
              </section>
            </>
          ) : null}
        </div>

        {error ? (
          <div className="agent-definition-dialog-error" role="alert">
            <ExclamationTriangleIcon />
            <span>{error}</span>
          </div>
        ) : null}

        <footer className="agent-definition-dialog-footer">
          <div />
          <div>
            <button type="button" disabled={busy} onClick={onClose}>
              {t('common.close')}
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}

function EvolutionMetric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function formatEvolutionDate(value: string, locale: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}
