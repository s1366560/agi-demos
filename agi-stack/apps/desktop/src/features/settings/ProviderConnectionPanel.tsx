import { useMemo, useState } from 'react';
import {
  CheckCircledIcon,
  ChevronDownIcon,
  ExclamationTriangleIcon,
  EyeClosedIcon,
  EyeOpenIcon,
  GearIcon,
  InfoCircledIcon,
  Link2Icon,
  LockClosedIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  LlmProviderMutationInput,
  LlmProviderValidationOutcome,
  ManagedLlmProvider,
  RuntimeMode,
} from '../../types';
import {
  providerDraftFromProvider,
  providerDraftIsValid,
  providerMutationFromDraft,
  type ProviderEditorDraft,
} from './providerManagementModel';

type ProviderConnectionPanelProps = {
  provider: ManagedLlmProvider;
  mode: RuntimeMode;
  canManage: boolean;
  onSave: (
    provider: ManagedLlmProvider,
    mutation: LlmProviderMutationInput,
  ) => Promise<ManagedLlmProvider>;
  onValidate: (providerId: string) => Promise<LlmProviderValidationOutcome>;
  onValidateDraft: (
    mutation: LlmProviderMutationInput,
  ) => Promise<LlmProviderValidationOutcome>;
};

function validationSucceeded(outcome: LlmProviderValidationOutcome | null): boolean {
  return outcome?.status === 'healthy' || outcome?.status === 'configuration_valid';
}

export function ProviderConnectionPanel({
  provider,
  mode,
  canManage,
  onSave,
  onValidate,
  onValidateDraft,
}: ProviderConnectionPanelProps) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [showSecret, setShowSecret] = useState(false);
  const [draft, setDraft] = useState<ProviderEditorDraft>(() =>
    providerDraftFromProvider(provider),
  );
  const [validation, setValidation] = useState<LlmProviderValidationOutcome | null>(null);
  const [busy, setBusy] = useState<'test' | 'save' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMemo(() => providerMutationFromDraft(draft), [draft]);
  const updateDraft = <Key extends keyof ProviderEditorDraft>(
    key: Key,
    value: ProviderEditorDraft[Key],
  ) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setValidation(null);
  };

  const testConnection = async () => {
    setBusy('test');
    setError(null);
    try {
      setValidation(editing ? await onValidateDraft(mutation) : await onValidate(provider.id));
    } catch (caught) {
      setValidation(null);
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  };

  const saveConnection = async () => {
    setBusy('save');
    setError(null);
    try {
      const updated = await onSave(provider, mutation);
      setEditing(false);
      setDraft(providerDraftFromProvider(updated));
      setShowSecret(false);
    } catch (caught) {
      setDraft((current) => ({ ...current, apiKey: '' }));
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  };

  const cancelEdit = () => {
    setDraft(providerDraftFromProvider(provider));
    setEditing(false);
    setValidation(null);
    setError(null);
  };

  const startEdit = () => {
    setDraft(providerDraftFromProvider(provider));
    setEditing(true);
    setValidation(null);
    setError(null);
    setShowSecret(false);
  };

  const configurationOnly = mode === 'local';
  const verified = validationSucceeded(validation);
  const credentialValue = editing
    ? draft.apiKey
    : provider.api_key_masked ||
      (provider.credential_configured
        ? t('providers.credentialConfigured')
        : t('providers.credentialMissing'));

  return (
    <section className="provider-form-card">
      <header>
        <div>
          <span>{t('providers.connectionEyebrow')}</span>
          <h3>{t('providers.connectionTitle')}</h3>
          <p>{t('providers.connectionDescription')}</p>
        </div>
        {canManage ? (
          <button type="button" onClick={editing ? cancelEdit : startEdit}>
            <GearIcon />
            {t(editing ? 'providers.cancelEdit' : 'providers.editConnection')}
          </button>
        ) : null}
      </header>

      {!canManage ? (
        <div className="provider-capability-note">
          <LockClosedIcon />
          <span>
            <b>{t('providers.readOnly')}</b>
            <small>{t('providers.readOnlyDescription')}</small>
          </span>
        </div>
      ) : null}

      <div className="provider-form-section">
        <div className="provider-form-heading">
          <span>1</span>
          <div>
            <b>{t('providers.authentication')}</b>
            <small>{t('providers.authenticationDescription')}</small>
          </div>
        </div>
        <div
          className="provider-auth-options provider-auth-options-supported"
          role="group"
          aria-label={t('providers.authenticationMethod')}
        >
          {(['api_key', 'none'] as const).map((authMethod) => (
            <button
              className={draft.authMethod === authMethod ? 'selected' : ''}
              type="button"
              disabled={!editing || (mode === 'cloud' && authMethod === 'none')}
              key={authMethod}
              onClick={() => updateDraft('authMethod', authMethod)}
            >
              {authMethod === 'api_key' ? <LockClosedIcon /> : <Link2Icon />}
              <span>
                <b>{t(`providers.auth.${authMethod}`)}</b>
                <small>{t(`providers.auth.${authMethod}Description`)}</small>
              </span>
            </button>
          ))}
        </div>
        {draft.authMethod === 'api_key' ? (
          <label className="provider-input-label">
            <span>{t('providers.apiKey')}</span>
            <div className="provider-secret-input">
              <input
                disabled={!editing}
                type={showSecret ? 'text' : 'password'}
                value={credentialValue}
                autoComplete="new-password"
                onChange={(event) => updateDraft('apiKey', event.target.value)}
                placeholder={t('providers.apiKeyPlaceholder')}
              />
              <button
                type="button"
                disabled={!editing || !draft.apiKey}
                aria-label={t(showSecret ? 'providers.hideSecret' : 'providers.showSecret')}
                onClick={() => setShowSecret((current) => !current)}
              >
                {showSecret ? <EyeClosedIcon /> : <EyeOpenIcon />}
              </button>
            </div>
            <small>{t('providers.secretDescription')}</small>
          </label>
        ) : (
          <div className="provider-capability-note compact">
            <InfoCircledIcon />
            <span>
              <b>{t('providers.noAuthentication')}</b>
              <small>{t('providers.noAuthenticationDescription')}</small>
            </span>
          </div>
        )}
      </div>

      <div className="provider-form-section">
        <div className="provider-form-heading">
          <span>2</span>
          <div>
            <b>{t('providers.endpoint')}</b>
            <small>{t('providers.endpointDescription')}</small>
          </div>
        </div>
        <label className="provider-input-label">
          <span>{t('providers.baseUrl')}</span>
          <input
            disabled={!editing}
            type="url"
            value={draft.baseUrl}
            onChange={(event) => updateDraft('baseUrl', event.target.value)}
            placeholder="https://api.example.com/v1"
          />
        </label>
        <button
          className="provider-advanced-toggle"
          type="button"
          aria-expanded={advanced}
          onClick={() => setAdvanced((current) => !current)}
        >
          {t('providers.advancedSettings')}
          <ChevronDownIcon className={advanced ? 'open' : ''} />
        </button>
        {advanced ? (
          <div className="provider-advanced-grid">
            <label>
              <span>{t('providers.providerType')}</span>
              <input disabled value={draft.providerType} />
            </label>
            <label>
              <span>{t('providers.connectionName')}</span>
              <input
                disabled={!editing}
                value={draft.name}
                onChange={(event) => updateDraft('name', event.target.value)}
              />
            </label>
            <div className="provider-capability-note compact wide">
              <InfoCircledIcon />
              <span>
                <b>{t('providers.advancedUnavailable')}</b>
                <small>{t('providers.advancedUnavailableDescription')}</small>
              </span>
            </div>
          </div>
        ) : null}
      </div>

      <div className="provider-test-row">
        <div
          className={`provider-test-result ${verified ? 'success' : validation ? 'failed' : ''}`}
          role="status"
          aria-live="polite"
        >
          {busy === 'test' ? (
            <ReloadIcon className="spin" />
          ) : verified ? (
            <CheckCircledIcon />
          ) : validation || error ? (
            <ExclamationTriangleIcon />
          ) : (
            <InfoCircledIcon />
          )}
          <span>
            <b>
              {t(
                busy === 'test'
                  ? configurationOnly
                    ? 'providers.validatingConfiguration'
                    : 'providers.testingConnection'
                  : verified
                    ? configurationOnly
                      ? 'providers.configurationValid'
                      : 'providers.connectionVerified'
                    : validation
                      ? 'providers.connectionFailed'
                      : configurationOnly
                        ? 'providers.validateBeforeSaving'
                        : 'providers.testBeforeSaving',
              )}
            </b>
            <small>
              {error ||
                validation?.detail ||
                validation?.errorMessage ||
                t(
                  configurationOnly
                    ? 'providers.configurationValidationDescription'
                    : 'providers.connectionTestDescription',
                )}
            </small>
          </span>
        </div>
        {canManage ? (
          <button
            type="button"
            disabled={busy !== null || (editing && !providerDraftIsValid(draft))}
            onClick={() => void testConnection()}
          >
            {t(configurationOnly ? 'providers.validateConfiguration' : 'providers.testConnection')}
          </button>
        ) : null}
        {editing ? (
          <button
            className="primary"
            type="button"
            disabled={!verified || busy !== null}
            onClick={() => void saveConnection()}
          >
            {t('providers.saveConnection')}
          </button>
        ) : null}
      </div>
    </section>
  );
}
