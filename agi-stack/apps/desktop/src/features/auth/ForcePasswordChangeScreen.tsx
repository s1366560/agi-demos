import { useRef, useState } from 'react';
import {
  ArrowRightIcon,
  ExitIcon,
  EyeClosedIcon,
  EyeOpenIcon,
  LockClosedIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import {
  type ForcedPasswordChangeField,
  type ForcedPasswordChangeValues,
  validateForcedPasswordChange,
} from './forcePasswordChangeModel';
import './ForcePasswordChangeScreen.css';

type ForcePasswordChangeScreenProps = {
  busy: boolean;
  error: string | null;
  onSubmit: (currentPassword: string, newPassword: string) => void;
  onSignOut: () => void;
};

const emptyValues: ForcedPasswordChangeValues = {
  currentPassword: '',
  newPassword: '',
  confirmPassword: '',
};

export function ForcePasswordChangeScreen({
  busy,
  error,
  onSubmit,
  onSignOut,
}: ForcePasswordChangeScreenProps) {
  const { t } = useI18n();
  const [values, setValues] = useState(emptyValues);
  const [validation, setValidation] =
    useState<ReturnType<typeof validateForcedPasswordChange>>(null);
  const [showPasswords, setShowPasswords] = useState(false);
  const currentPasswordRef = useRef<HTMLInputElement>(null);
  const newPasswordRef = useRef<HTMLInputElement>(null);
  const confirmPasswordRef = useRef<HTMLInputElement>(null);
  const visibleError = validation ? t(validation.messageKey) : error;

  const updateValue = (field: ForcedPasswordChangeField, value: string) => {
    setValues((current) => ({ ...current, [field]: value }));
    if (validation?.field === field) setValidation(null);
  };

  const submit = () => {
    const nextValidation = validateForcedPasswordChange(values);
    setValidation(nextValidation);
    if (nextValidation) {
      const target = {
        currentPassword: currentPasswordRef,
        newPassword: newPasswordRef,
        confirmPassword: confirmPasswordRef,
      }[nextValidation.field];
      target.current?.focus();
      return;
    }
    onSubmit(values.currentPassword, values.newPassword);
  };

  return (
    <main className="force-password-screen">
      <section className="force-password-card" aria-labelledby="force-password-title">
        <header>
          <span className="force-password-lock" aria-hidden="true">
            <LockClosedIcon />
          </span>
          <span className="force-password-eyebrow">{t('forcePassword.eyebrow')}</span>
          <h1 id="force-password-title">{t('forcePassword.title')}</h1>
          <p>{t('forcePassword.subtitle')}</p>
        </header>

        <form
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <label>
            <span>{t('forcePassword.currentPassword')}</span>
            <input
              ref={currentPasswordRef}
              type={showPasswords ? 'text' : 'password'}
              value={values.currentPassword}
              onChange={(event) => updateValue('currentPassword', event.target.value)}
              autoComplete="current-password"
              disabled={busy}
              aria-invalid={validation?.field === 'currentPassword'}
              autoFocus
            />
          </label>

          <label>
            <span>{t('forcePassword.newPassword')}</span>
            <input
              ref={newPasswordRef}
              type={showPasswords ? 'text' : 'password'}
              value={values.newPassword}
              onChange={(event) => updateValue('newPassword', event.target.value)}
              autoComplete="new-password"
              disabled={busy}
              aria-invalid={validation?.field === 'newPassword'}
            />
            <small>{t('forcePassword.passwordHint')}</small>
          </label>

          <label>
            <span>{t('forcePassword.confirmPassword')}</span>
            <input
              ref={confirmPasswordRef}
              type={showPasswords ? 'text' : 'password'}
              value={values.confirmPassword}
              onChange={(event) => updateValue('confirmPassword', event.target.value)}
              autoComplete="new-password"
              disabled={busy}
              aria-invalid={validation?.field === 'confirmPassword'}
            />
          </label>

          <button
            className="force-password-visibility"
            type="button"
            onClick={() => setShowPasswords((current) => !current)}
            disabled={busy}
            aria-pressed={showPasswords}
          >
            {showPasswords ? <EyeClosedIcon /> : <EyeOpenIcon />}
            {t(showPasswords ? 'forcePassword.hidePasswords' : 'forcePassword.showPasswords')}
          </button>

          {visibleError ? (
            <div className="force-password-error" role="alert">
              {visibleError}
            </div>
          ) : null}

          <button className="force-password-submit" type="submit" disabled={busy}>
            {t(busy ? 'forcePassword.submitting' : 'forcePassword.submit')}
            <ArrowRightIcon />
          </button>
        </form>

        <button
          className="force-password-sign-out"
          type="button"
          onClick={onSignOut}
          disabled={busy}
        >
          <ExitIcon />
          {t('forcePassword.signOut')}
        </button>

        <footer>
          <LockClosedIcon aria-hidden="true" />
          {t('forcePassword.securityNote')}
        </footer>
      </section>
    </main>
  );
}
