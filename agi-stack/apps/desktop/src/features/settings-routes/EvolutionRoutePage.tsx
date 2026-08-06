import { useEffect, useMemo, useState } from 'react';
import { ReloadIcon, RocketIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { EvolutionRouteConfig } from './evolutionRouteClient';
import type { EvolutionRouteController } from './evolutionRouteController';
import type { EvolutionRoutePresentationModel } from './evolutionRoutePresentationModel';
import { useNativeRouteAction } from './useNativeRouteAction';

const NUMERIC_CONFIG_FIELDS = Object.freeze([
  'min_sessions_per_skill',
  'scoring_min_sessions_per_skill',
  'min_avg_score',
  'max_sessions_per_batch',
  'evolution_interval_minutes',
] as const);

export function EvolutionRoutePage({
  model,
  controller,
}: Readonly<{
  model: EvolutionRoutePresentationModel;
  controller: EvolutionRouteController;
}>) {
  const { t } = useI18n();
  const observation = model.observation;
  const [draft, setDraft] = useState<EvolutionRouteConfig | null>(observation?.config ?? null);
  const action = useNativeRouteAction('skill_evolution_action_failed');
  const allowed = useMemo(
    () => new Set(observation?.allowedActions ?? []),
    [observation?.allowedActions],
  );
  useEffect(() => setDraft(observation?.config ?? null), [observation]);

  if (!observation || !draft) {
    return <NativeContentContractGap capability={model.capability} />;
  }
  const jobs = observation.overview.recent_jobs.flatMap(readEvolutionJob);
  const skills = observation.overview.skills;
  const busy = action.busyAction !== null;

  return (
    <main className="settings-page" data-route-content="evolution" data-state={model.state}>
      <header className="settings-page-heading">
        <div>
          <span>{t('settings.skillsEyebrow')}</span>
          <h1>{t('settings.skillEvolution.action')}</h1>
          <p>{t('settings.skillEvolution.description')}</p>
        </div>
        <button
          type="button"
          data-action="run"
          disabled={busy || !allowed.has('run')}
          onClick={() => void action.run('run', () => controller.run(model.scope))}
        >
          {action.busyAction === 'run' ? <ReloadIcon /> : <RocketIcon />}
          {t(
            action.busyAction === 'run'
              ? 'settings.skillEvolution.running'
              : 'settings.skillEvolution.run',
          )}
        </button>
      </header>

      {action.reasonCode ? <code role="alert">{action.reasonCode}</code> : null}

      <section className="settings-panel" aria-label={t('settings.skillEvolution.route')}>
        <div className="settings-rows">
          {Object.entries(observation.overview.stats).map(([key, value]) => (
            <div key={key} className="settings-row">
              <code>{key}</code>
              <strong>{displayValue(value)}</strong>
            </div>
          ))}
        </div>
      </section>

      <form
        className="settings-panel"
        data-action="configure"
        onSubmit={(event) => {
          event.preventDefault();
          void action.run('configure', () => controller.updateConfig(model.scope, draft));
        }}
      >
        <header>
          <strong>{t('settings.skillEvolution.threshold')}</strong>
        </header>
        <label>
          <input
            type="checkbox"
            checked={draft.enabled}
            disabled={busy || !allowed.has('configure')}
            onChange={(event) =>
              setDraft((current) =>
                current ? { ...current, enabled: event.currentTarget.checked } : current,
              )
            }
          />
          {t(
            draft.enabled ? 'settings.skillEvolution.enabled' : 'settings.skillEvolution.disabled',
          )}
        </label>
        <div className="settings-grid">
          {NUMERIC_CONFIG_FIELDS.map((field) => (
            <label key={field}>
              <code>{field}</code>
              <input
                type="number"
                value={draft[field]}
                step={field === 'min_avg_score' ? '0.01' : '1'}
                min="0"
                disabled={busy || !allowed.has('configure')}
                onChange={(event) => {
                  const value = Number(event.currentTarget.value);
                  setDraft((current) =>
                    current && Number.isFinite(value) ? { ...current, [field]: value } : current,
                  );
                }}
              />
            </label>
          ))}
          <label>
            <code>publish_mode</code>
            <select
              value={draft.publish_mode}
              disabled={busy || !allowed.has('configure')}
              onChange={(event) =>
                setDraft((current) =>
                  current ? { ...current, publish_mode: event.currentTarget.value } : current,
                )
              }
            >
              <option value="review">review</option>
              <option value="direct">direct</option>
            </select>
          </label>
          <label>
            <input
              type="checkbox"
              checked={draft.auto_apply}
              disabled={busy || !allowed.has('configure')}
              onChange={(event) =>
                setDraft((current) =>
                  current ? { ...current, auto_apply: event.currentTarget.checked } : current,
                )
              }
            />
            <code>auto_apply</code>
          </label>
        </div>
        <button type="submit" disabled={busy || !allowed.has('configure')}>
          {t('common.save')}
        </button>
      </form>

      <section className="settings-panel">
        <header>
          <strong>{t('settings.skillEvolution.route')}</strong>
          <span>{t('settings.skillEvolution.routeDescription')}</span>
        </header>
        {jobs.length === 0 ? (
          <p>{t('settings.skillEvolution.empty')}</p>
        ) : (
          <div className="settings-list">
            {jobs.map((job) => (
              <article key={job.id}>
                <div>
                  <strong>{job.skillName}</strong>
                  <code>{job.status}</code>
                  <p>{job.detail || t('settings.skillEvolution.noDetail')}</p>
                </div>
                {job.status === 'pending_review' ? (
                  <div>
                    <button
                      type="button"
                      data-action="apply-job"
                      disabled={busy || !allowed.has('apply-job')}
                      onClick={() =>
                        void action.run(`apply:${job.id}`, () =>
                          controller.reviewJob(model.scope, job.id, 'apply'),
                        )
                      }
                    >
                      {t('settings.skillEvolution.apply')}
                    </button>
                    <button
                      type="button"
                      data-action="reject-job"
                      disabled={busy || !allowed.has('reject-job')}
                      onClick={() =>
                        void action.run(`reject:${job.id}`, () =>
                          controller.reviewJob(model.scope, job.id, 'reject'),
                        )
                      }
                    >
                      {t('settings.skillEvolution.reject')}
                    </button>
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="settings-panel">
        <strong>{t('settings.skills')}</strong>
        <div className="settings-list">
          {skills.map((skill, index) => (
            <article key={recordText(skill, 'skill_id') ?? String(index)}>
              <strong>{recordText(skill, 'skill_name') ?? t('chat.skillUnnamed')}</strong>
              <code>{displayValue(skill.session_count)}</code>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}

function NativeContentContractGap({ capability }: Readonly<{ capability: string }>) {
  return (
    <section className="desktop-production-route-boundary" data-state="unavailable">
      <code>{capability}:presentation_observation_unavailable</code>
    </section>
  );
}

function readEvolutionJob(value: Readonly<Record<string, unknown>>) {
  const id = recordText(value, 'id');
  if (!id) return [];
  return [
    Object.freeze({
      id,
      status: recordText(value, 'status') ?? 'unknown',
      skillName: recordText(value, 'skill_name') ?? id,
      detail: recordText(value, 'candidate_preview') ?? recordText(value, 'rationale'),
    }),
  ];
}

function recordText(value: Readonly<Record<string, unknown>>, key: string): string | null {
  const candidate = value[key];
  return typeof candidate === 'string' && candidate.trim() ? candidate.trim() : null;
}

function displayValue(value: unknown): string {
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return '—';
}
