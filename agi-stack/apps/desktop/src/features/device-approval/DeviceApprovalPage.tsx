import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from 'react';
import { CheckCircledIcon, DesktopIcon, LockClosedIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import {
  DeviceApprovalError,
  type DeviceApprovalClient,
} from './deviceApprovalClient';
import {
  isCompleteDeviceApprovalCode,
  normalizeDeviceApprovalCode,
} from './deviceApprovalModel';
import './DeviceApprovalPage.css';

export type DeviceApprovalPageProps = Readonly<{
  accountLabel: string;
  client: DeviceApprovalClient;
  initialCode: string;
  onNavigateBack(): void;
}>;

export function DeviceApprovalPage({
  accountLabel,
  client,
  initialCode,
  onNavigateBack,
}: DeviceApprovalPageProps) {
  const { t } = useI18n();
  const [code, setCode] = useState(() =>
    normalizeDeviceApprovalCode(initialCode),
  );
  const [confirmationOpen, setConfirmationOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [approved, setApproved] = useState(false);
  const [reasonCode, setReasonCode] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const requestRef = useRef<AbortController | null>(null);

  const restoreInputFocus = () => {
    queueMicrotask(() => inputRef.current?.focus());
  };
  const closeConfirmation = () => {
    if (submitting) return;
    setConfirmationOpen(false);
    restoreInputFocus();
  };

  useEffect(() => {
    if (!confirmationOpen) return;
    confirmRef.current?.focus();
    const closeOnBlur = () => closeConfirmation();
    window.addEventListener('blur', closeOnBlur);
    return () => window.removeEventListener('blur', closeOnBlur);
  }, [confirmationOpen, submitting]);

  useEffect(
    () => () => {
      requestRef.current?.abort();
    },
    [],
  );

  const requestConfirmation = () => {
    setReasonCode(null);
    if (!isCompleteDeviceApprovalCode(code)) {
      setReasonCode('device_approval_code_invalid');
      restoreInputFocus();
      return;
    }
    setConfirmationOpen(true);
  };

  const approve = async () => {
    if (submitting || !isCompleteDeviceApprovalCode(code)) return;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setSubmitting(true);
    setReasonCode(null);
    try {
      await client.approve(code, { signal: controller.signal });
      setApproved(true);
      setConfirmationOpen(false);
    } catch (error) {
      if (controller.signal.aborted) return;
      setReasonCode(
        error instanceof DeviceApprovalError
          ? error.reasonCode
          : 'device_approval_request_failed',
      );
      setConfirmationOpen(false);
      restoreInputFocus();
    } finally {
      if (requestRef.current === controller) requestRef.current = null;
      setSubmitting(false);
    }
  };

  if (approved) {
    return (
      <section
        className="device-approval-page device-approval-success"
        aria-labelledby="device-approval-title"
      >
        <CheckCircledIcon aria-hidden="true" />
        <p className="device-approval-eyebrow">{t('deviceApproval.eyebrow')}</p>
        <h1 id="device-approval-title">{t('deviceApproval.approved.title')}</h1>
        <p>{t('deviceApproval.approved.description')}</p>
        <button type="button" onClick={onNavigateBack} autoFocus>
          {t('deviceApproval.returnWorkbench')}
        </button>
      </section>
    );
  }

  const errorKey = reasonCode
    ? `deviceApproval.error.${reasonCode}`
    : null;
  return (
    <section
      className="device-approval-page"
      aria-labelledby="device-approval-title"
    >
      <header>
        <span className="device-approval-icon">
          <DesktopIcon aria-hidden="true" />
        </span>
        <p className="device-approval-eyebrow">{t('deviceApproval.eyebrow')}</p>
        <h1 id="device-approval-title">{t('deviceApproval.title')}</h1>
        <p>{t('deviceApproval.description')}</p>
      </header>

      <div className="device-approval-account">
        <LockClosedIcon aria-hidden="true" />
        <span>
          <strong>{t('deviceApproval.account.title')}</strong>
          <small>
            {t('deviceApproval.account.description', {
              account: accountLabel || t('deviceApproval.account.current'),
            })}
          </small>
        </span>
      </div>

      {reasonCode ? (
        <div className="device-approval-error" role="alert" aria-live="polite">
          <strong>{t('deviceApproval.error.title')}</strong>
          <p>{t(errorKey ?? 'deviceApproval.error.device_approval_request_failed')}</p>
          <code>{reasonCode}</code>
        </div>
      ) : null}

      <form
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          requestConfirmation();
        }}
      >
        <label htmlFor="device-approval-code">
          {t('deviceApproval.code.label')}
        </label>
        <input
          ref={inputRef}
          id="device-approval-code"
          value={code}
          maxLength={8}
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          autoFocus
          placeholder={t('deviceApproval.code.placeholder')}
          onChange={(event) => {
            requestRef.current?.abort();
            setCode(normalizeDeviceApprovalCode(event.currentTarget.value));
            setReasonCode(null);
          }}
        />
        <p>{t('deviceApproval.code.help')}</p>
        <div className="device-approval-actions">
          <button type="button" onClick={onNavigateBack}>
            {t('common.cancel')}
          </button>
          <button
            type="submit"
            disabled={!isCompleteDeviceApprovalCode(code) || submitting}
          >
            {t('deviceApproval.approve')}
          </button>
        </div>
      </form>

      {confirmationOpen ? (
        <div
          className="device-approval-dialog-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeConfirmation();
          }}
        >
          <section
            className="device-approval-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="device-approval-confirm-title"
            onKeyDown={(event: KeyboardEvent) => {
              if (event.key !== 'Escape' || submitting) return;
              event.preventDefault();
              closeConfirmation();
            }}
          >
            <LockClosedIcon aria-hidden="true" />
            <h2 id="device-approval-confirm-title">
              {t('deviceApproval.confirm.title')}
            </h2>
            <p>
              {t('deviceApproval.confirm.description', {
                code,
                account: accountLabel || t('deviceApproval.account.current'),
              })}
            </p>
            <code>{code}</code>
            <div className="device-approval-actions">
              <button
                type="button"
                onClick={closeConfirmation}
                disabled={submitting}
              >
                {t('common.cancel')}
              </button>
              <button
                ref={confirmRef}
                type="button"
                onClick={() => void approve()}
                disabled={submitting}
              >
                {submitting
                  ? t('deviceApproval.approving')
                  : t('deviceApproval.confirm.action')}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}
