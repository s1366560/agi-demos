import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from 'react';
import {
  CheckCircledIcon,
  ExclamationTriangleIcon,
  HomeIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import {
  TenantCreationError,
  type TenantCreationClient,
} from './tenantCreationClient';
import {
  TENANT_CREATION_PLANS,
  createTenantCreationDraft,
  tenantCreationIsDirty,
  validateTenantCreationDraft,
  type TenantCreationDraft,
  type TenantCreationPlan,
  type TenantCreationRecord,
} from './tenantCreationModel';
import './TenantCreationPage.css';

export type TenantCreationPageProps = Readonly<{
  client: TenantCreationClient;
  onCreated(
    created: TenantCreationRecord,
    signal: AbortSignal,
  ): Promise<Readonly<{ catalogRefreshed: boolean }>>;
  onNavigateBack(): void;
}>;

export function TenantCreationPage({
  client,
  onCreated,
  onNavigateBack,
}: TenantCreationPageProps) {
  const { t } = useI18n();
  const [draft, setDraft] = useState<TenantCreationDraft>(
    createTenantCreationDraft,
  );
  const [submitting, setSubmitting] = useState(false);
  const [confirmationOpen, setConfirmationOpen] = useState(false);
  const [reasonCode, setReasonCode] = useState<string | null>(null);
  const [created, setCreated] = useState<TenantCreationRecord | null>(null);
  const [catalogRefreshed, setCatalogRefreshed] = useState(true);
  const nameRef = useRef<HTMLInputElement>(null);
  const discardRef = useRef<HTMLButtonElement>(null);
  const requestRef = useRef<AbortController | null>(null);

  const restoreNameFocus = () => {
    queueMicrotask(() => nameRef.current?.focus());
  };

  const closeConfirmation = () => {
    setConfirmationOpen(false);
    restoreNameFocus();
  };

  useEffect(() => {
    if (!confirmationOpen) return;
    discardRef.current?.focus();
    const closeOnBlur = () => closeConfirmation();
    window.addEventListener('blur', closeOnBlur);
    return () => window.removeEventListener('blur', closeOnBlur);
  }, [confirmationOpen]);

  useEffect(
    () => () => {
      requestRef.current?.abort();
    },
    [],
  );

  const updateDraft = (
    field: keyof TenantCreationDraft,
    value: string,
  ) => {
    requestRef.current?.abort();
    setDraft((current) =>
      Object.freeze({
        ...current,
        [field]: value,
      }) as TenantCreationDraft,
    );
    setReasonCode(null);
  };

  const requestCancel = () => {
    if (submitting) return;
    if (!tenantCreationIsDirty(draft)) {
      onNavigateBack();
      return;
    }
    setConfirmationOpen(true);
  };

  const submit = async () => {
    if (submitting || created) return;
    const validation = validateTenantCreationDraft(draft);
    if (!validation.valid) {
      setReasonCode(validation.reasonCode);
      restoreNameFocus();
      return;
    }

    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setSubmitting(true);
    setReasonCode(null);
    try {
      const nextCreated = await client.create(validation.value, {
        signal: controller.signal,
      });
      const outcome = await onCreated(nextCreated, controller.signal);
      if (controller.signal.aborted) return;
      setCatalogRefreshed(outcome.catalogRefreshed);
      setCreated(nextCreated);
    } catch (error) {
      if (controller.signal.aborted) return;
      setReasonCode(
        error instanceof TenantCreationError
          ? error.reasonCode
          : 'tenant_creation_request_failed',
      );
      restoreNameFocus();
    } finally {
      if (requestRef.current === controller) requestRef.current = null;
      setSubmitting(false);
    }
  };

  if (created) {
    const planMismatch = created.plan !== draft.plan;
    return (
      <section
        className="tenant-creation-page tenant-creation-success"
        aria-labelledby="tenant-creation-title"
      >
        <CheckCircledIcon aria-hidden="true" />
        <p className="tenant-creation-eyebrow">
          {t('tenantCreation.success.eyebrow')}
        </p>
        <h1 id="tenant-creation-title">
          {t('tenantCreation.success.title')}
        </h1>
        <p>
          {t('tenantCreation.success.description', {
            name: created.name,
          })}
        </p>
        {planMismatch ? (
          <div className="tenant-creation-warning" role="status">
            <ExclamationTriangleIcon aria-hidden="true" />
            <p>
              {t('tenantCreation.success.planMismatch', {
                actual: t(`tenantCreation.plan.${created.plan}`),
                requested: t(`tenantCreation.plan.${draft.plan}`),
              })}
            </p>
          </div>
        ) : null}
        {!catalogRefreshed ? (
          <div className="tenant-creation-warning" role="status">
            <ExclamationTriangleIcon aria-hidden="true" />
            <p>{t('tenantCreation.success.catalogStale')}</p>
          </div>
        ) : null}
        <button type="button" onClick={onNavigateBack} autoFocus>
          {t('tenantCreation.success.return')}
        </button>
      </section>
    );
  }

  const errorKey = reasonCode
    ? `tenantCreation.error.${reasonCode}`
    : null;
  return (
    <section
      className="tenant-creation-page"
      aria-labelledby="tenant-creation-title"
    >
      <header>
        <span className="tenant-creation-icon">
          <HomeIcon aria-hidden="true" />
        </span>
        <p className="tenant-creation-eyebrow">
          {t('tenantCreation.eyebrow')}
        </p>
        <h1 id="tenant-creation-title">{t('tenantCreation.title')}</h1>
        <p>{t('tenantCreation.description')}</p>
      </header>

      {reasonCode ? (
        <div className="tenant-creation-error" role="alert" aria-live="polite">
          <strong>{t('tenantCreation.error.title')}</strong>
          <p>
            {t(
              errorKey ??
                'tenantCreation.error.tenant_creation_request_failed',
            )}
          </p>
          <code>{reasonCode}</code>
        </div>
      ) : null}

      <form
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label htmlFor="tenant-creation-name">
          {t('tenantCreation.name.label')}
        </label>
        <input
          ref={nameRef}
          id="tenant-creation-name"
          name="name"
          type="text"
          autoComplete="organization"
          spellCheck={false}
          maxLength={255}
          disabled={submitting}
          value={draft.name}
          placeholder={t('tenantCreation.name.placeholder')}
          onChange={(event) => updateDraft('name', event.currentTarget.value)}
          autoFocus
        />

        <label htmlFor="tenant-creation-description">
          {t('tenantCreation.description.label')}
        </label>
        <textarea
          id="tenant-creation-description"
          name="description"
          rows={4}
          maxLength={1000}
          disabled={submitting}
          value={draft.description}
          placeholder={t('tenantCreation.description.placeholder')}
          onChange={(event) =>
            updateDraft('description', event.currentTarget.value)
          }
        />

        <label htmlFor="tenant-creation-plan">
          {t('tenantCreation.plan.label')}
        </label>
        <select
          id="tenant-creation-plan"
          name="plan"
          disabled={submitting}
          value={draft.plan}
          onChange={(event) =>
            updateDraft(
              'plan',
              event.currentTarget.value as TenantCreationPlan,
            )
          }
        >
          {TENANT_CREATION_PLANS.map((plan) => (
            <option key={plan} value={plan}>
              {t(`tenantCreation.plan.${plan}`)}
            </option>
          ))}
        </select>

        <div className="tenant-creation-actions">
          <button type="button" onClick={requestCancel} disabled={submitting}>
            {t('common.cancel')}
          </button>
          <button
            type="submit"
            disabled={submitting || !draft.name.trim()}
          >
            {submitting
              ? t('tenantCreation.creating')
              : t('tenantCreation.create')}
          </button>
        </div>
      </form>

      {confirmationOpen ? (
        <div
          className="tenant-creation-dialog-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeConfirmation();
          }}
        >
          <section
            className="tenant-creation-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="tenant-creation-cancel-title"
            onKeyDown={(event: KeyboardEvent) => {
              if (event.key !== 'Escape') return;
              event.preventDefault();
              closeConfirmation();
            }}
          >
            <ExclamationTriangleIcon aria-hidden="true" />
            <h2 id="tenant-creation-cancel-title">
              {t('tenantCreation.cancel.title')}
            </h2>
            <p>{t('tenantCreation.cancel.description')}</p>
            <div className="tenant-creation-actions">
              <button type="button" onClick={closeConfirmation}>
                {t('common.cancel')}
              </button>
              <button
                ref={discardRef}
                type="button"
                onClick={onNavigateBack}
              >
                {t('tenantCreation.cancel.discard')}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}
