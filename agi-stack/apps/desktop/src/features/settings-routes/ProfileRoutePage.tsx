import { useEffect, useMemo, useState } from 'react';
import { LockClosedIcon, PersonIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { ProfileRouteController } from './profileRouteController';
import type { ProfileRoutePresentationModel } from './profileRoutePresentationModel';
import { useNativeRouteAction } from './useNativeRouteAction';

type PasswordDraft = Readonly<{
  current: string;
  next: string;
  confirm: string;
}>;

const EMPTY_PASSWORD: PasswordDraft = Object.freeze({ current: '', next: '', confirm: '' });

export function ProfileRoutePage({
  model,
  controller,
}: Readonly<{
  model: ProfileRoutePresentationModel;
  controller: ProfileRouteController;
}>) {
  const { locale, setLocale, t } = useI18n();
  const observation = model.observation;
  const action = useNativeRouteAction('user_profile_action_failed');
  const [name, setName] = useState(observation?.user.name ?? '');
  const [language, setLanguage] = useState<'en-US' | 'zh-CN'>(
    observation?.user.preferred_language === 'zh-CN' ? 'zh-CN' : 'en-US',
  );
  const [password, setPassword] = useState<PasswordDraft>(EMPTY_PASSWORD);
  const [passwordErrorKey, setPasswordErrorKey] = useState<string | null>(null);
  const allowed = useMemo(
    () => new Set(observation?.allowedActions ?? []),
    [observation?.allowedActions],
  );
  useEffect(() => {
    if (!observation) return;
    setName(observation.user.name);
    setLanguage(observation.user.preferred_language === 'zh-CN' ? 'zh-CN' : 'en-US');
  }, [observation]);

  if (!observation) return <ContractGap capability={model.capability} />;
  const busy = action.busyAction !== null;
  const editable = allowed.has('update') && model.state !== 'degraded';

  const saveProfile = async (): Promise<void> => {
    const result = await action.run('update', () =>
      controller.update(model.scope, { name, preferred_language: language }),
    );
    if (result.ok) setLocale(language === 'zh-CN' ? 'zh-CN' : 'en');
  };

  const savePassword = async (): Promise<void> => {
    const errorKey = validatePassword(password);
    setPasswordErrorKey(errorKey);
    if (errorKey) return;
    const result = await action.run('change-password', () =>
      controller.changePassword(model.scope, {
        oldPassword: password.current,
        newPassword: password.next,
      }),
    );
    if (result.ok) setPassword(EMPTY_PASSWORD);
  };

  return (
    <main className="settings-page" data-route-content="profile" data-state={model.state}>
      <header className="settings-page-heading">
        <div>
          <span>{t('settings.accountEyebrow')}</span>
          <h1>{t('settings.accountTitle')}</h1>
          <p>{t('settings.accountSubtitle')}</p>
        </div>
      </header>

      {model.reasonCode ? (
        <p role="status" data-reason-code={model.reasonCode}>
          {t('desktopProductionRouter.reason.authorityUnavailable')}
        </p>
      ) : null}
      {action.reasonCode ? (
        <p role="alert" data-reason-code={action.reasonCode}>
          {t('desktopProductionRouter.reason.authorityUnavailable')}
        </p>
      ) : null}

      <section className="settings-panel">
        <header>
          <PersonIcon />
          <div>
            <strong>{observation.user.name || observation.user.email}</strong>
            <small>{observation.user.email}</small>
          </div>
        </header>
        <dl>
          <div>
            <dt>{t('settings.accountCreated')}</dt>
            <dd>{new Date(observation.user.created_at).toLocaleDateString(locale)}</dd>
          </div>
          <div>
            <dt>{t('settings.workspaceRoles')}</dt>
            <dd>{observation.user.roles.join(', ')}</dd>
          </div>
        </dl>
      </section>

      <form
        className="settings-panel"
        data-action="update"
        onSubmit={(event) => {
          event.preventDefault();
          void saveProfile();
        }}
      >
        <label>
          <span>{t('settings.subagentEditor.displayName')}</span>
          <input
            value={name}
            disabled={busy || !editable}
            onChange={(event) => setName(event.currentTarget.value)}
          />
        </label>
        <label data-action="change-language">
          <span>{t('settings.language')}</span>
          <select
            value={language}
            disabled={busy || !editable || !allowed.has('change-language')}
            onChange={(event) =>
              setLanguage(event.currentTarget.value === 'zh-CN' ? 'zh-CN' : 'en-US')
            }
          >
            <option value="en-US">{t('settings.englishLocaleName')}</option>
            <option value="zh-CN">{t('settings.chineseLocaleName')}</option>
          </select>
          <small>{t('settings.languageDescription')}</small>
        </label>
        <button type="submit" disabled={busy || !editable}>
          {t('common.save')}
        </button>
      </form>

      <form
        className="settings-panel"
        data-action="change-password"
        onSubmit={(event) => {
          event.preventDefault();
          void savePassword();
        }}
      >
        <header>
          <LockClosedIcon />
          <div>
            <strong>{t('forcePassword.title')}</strong>
            <small>{t('forcePassword.passwordHint')}</small>
          </div>
        </header>
        <label>
          <span>{t('forcePassword.currentPassword')}</span>
          <input
            type="password"
            autoComplete="current-password"
            value={password.current}
            disabled={busy || !allowed.has('change-password')}
            onChange={(event) => setPassword({ ...password, current: event.currentTarget.value })}
          />
        </label>
        <label>
          <span>{t('forcePassword.newPassword')}</span>
          <input
            type="password"
            autoComplete="new-password"
            value={password.next}
            disabled={busy || !allowed.has('change-password')}
            onChange={(event) => setPassword({ ...password, next: event.currentTarget.value })}
          />
        </label>
        <label>
          <span>{t('forcePassword.confirmPassword')}</span>
          <input
            type="password"
            autoComplete="new-password"
            value={password.confirm}
            disabled={busy || !allowed.has('change-password')}
            onChange={(event) => setPassword({ ...password, confirm: event.currentTarget.value })}
          />
        </label>
        {passwordErrorKey ? <em role="alert">{t(passwordErrorKey)}</em> : null}
        <button type="submit" disabled={busy || !allowed.has('change-password')}>
          {t('forcePassword.submit')}
        </button>
      </form>
    </main>
  );
}

function validatePassword(draft: PasswordDraft): string | null {
  if (!draft.current) return 'forcePassword.currentRequired';
  if (!draft.next) return 'forcePassword.newRequired';
  if (draft.next.length < 8) return 'forcePassword.minimumLength';
  if (draft.next === draft.current) return 'forcePassword.mustDiffer';
  if (!draft.confirm) return 'forcePassword.confirmRequired';
  if (draft.next !== draft.confirm) return 'forcePassword.mismatch';
  return null;
}

function ContractGap({ capability }: Readonly<{ capability: string }>) {
  return (
    <section className="desktop-production-route-boundary" data-state="unavailable">
      <code>{capability}:presentation_observation_unavailable</code>
    </section>
  );
}
