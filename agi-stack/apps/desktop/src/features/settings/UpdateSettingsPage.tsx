import { useCallback, useEffect, useState } from 'react';
import { CheckCircledIcon, ReloadIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import { SettingsPage } from './SettingsCorePages';
import {
  updateLifecyclePresentation,
  type UpdateLifecycleState,
} from './updateSettingsModel';
import './UpdateSettingsPage.css';

const unavailableState: UpdateLifecycleState = Object.freeze({
  schemaVersion: 2,
  phase: 'disabled',
  currentVersion: '',
  candidateVersion: null,
  recoveryVersion: null,
  progress: null,
  reasonCode: 'production_update_feed_disabled',
  retryable: false,
  allowedActions: Object.freeze([]),
});

export function UpdateSettingsPage() {
  const { t } = useI18n();
  const updates = window.__MEMSTACK_DESKTOP__?.updates;
  const [state, setState] = useState<UpdateLifecycleState>(unavailableState);
  const [busyAction, setBusyAction] = useState<'check' | 'restart_to_apply' | null>(null);

  useEffect(() => {
    if (!updates) {
      setState(unavailableState);
      return;
    }

    let active = true;
    const unsubscribe = updates.subscribe((nextState) => {
      if (active) setState(nextState);
    });
    void updates.getState()
      .then((nextState) => {
        if (active) setState(nextState);
      })
      .catch(() => {
        if (active) {
          setState({
            ...unavailableState,
            phase: 'failed',
            reasonCode: 'update_operation_failed',
          });
        }
      });

    return () => {
      active = false;
      unsubscribe();
    };
  }, [updates]);

  const runAction = useCallback(
    async (action: 'check' | 'restart_to_apply') => {
      if (!updates || !state.allowedActions.includes(action)) return;
      setBusyAction(action);
      try {
        const nextState =
          action === 'check' ? await updates.check() : await updates.restartToApply();
        setState(nextState);
      } catch {
        setState((current) => ({
          ...current,
          phase: 'failed',
          reasonCode: 'update_operation_failed',
          retryable: current.allowedActions.includes('check'),
        }));
      } finally {
        setBusyAction(null);
      }
    },
    [state.allowedActions, updates],
  );

  const presentation = updateLifecyclePresentation(state);
  const canCheck = state.allowedActions.includes('check');
  const canRestart = state.allowedActions.includes('restart_to_apply');

  return (
    <SettingsPage
      eyebrow={t('settings.updatesEyebrow')}
      title={t('settings.updatesTitle')}
      description={t('settings.updatesSubtitle')}
      className="settings-updates-page"
    >
      <section
        className={`settings-update-card tone-${presentation.tone}`}
        aria-busy={busyAction !== null}
      >
        <header>
          <span className="settings-update-state-icon" aria-hidden="true">
            {presentation.tone === 'success' ? <CheckCircledIcon /> : <ReloadIcon />}
          </span>
          <span>
            <strong aria-live="polite">{t(presentation.phaseKey)}</strong>
            <small>{t('settings.updatesCurrentVersion', { version: state.currentVersion || '—' })}</small>
          </span>
        </header>

        {presentation.reasonKey ? (
          <p className="settings-update-message" role={state.phase === 'failed' ? 'alert' : undefined}>
            {t(presentation.reasonKey)}
          </p>
        ) : null}

        {presentation.progress !== null ? (
          <div className="settings-update-progress">
            <label htmlFor="settings-update-download-progress">
              {t('settings.updatesProgress', { progress: presentation.progress })}
            </label>
            <progress
              id="settings-update-download-progress"
              max={100}
              value={presentation.progress}
            >
              {presentation.progress}%
            </progress>
          </div>
        ) : null}

        <dl className="settings-update-versions">
          <div>
            <dt>{t('settings.updatesCandidateVersion')}</dt>
            <dd>{state.candidateVersion ?? t('settings.notAvailable')}</dd>
          </div>
          <div>
            <dt>{t('settings.updatesRecoveryVersion')}</dt>
            <dd>{state.recoveryVersion ?? t('settings.notAvailable')}</dd>
          </div>
        </dl>

        {canCheck || canRestart ? (
          <footer>
            {canCheck ? (
              <button
                type="button"
                disabled={busyAction !== null}
                onClick={() => void runAction('check')}
              >
                {busyAction === 'check' ? t('settings.updatesChecking') : t('settings.updatesCheck')}
              </button>
            ) : null}
            {canRestart ? (
              <button
                type="button"
                className="primary"
                disabled={busyAction !== null}
                onClick={() => void runAction('restart_to_apply')}
              >
                {busyAction === 'restart_to_apply'
                  ? t('settings.updatesApplying')
                  : t('settings.updatesRestartToApply')}
              </button>
            ) : null}
          </footer>
        ) : null}
      </section>
    </SettingsPage>
  );
}
