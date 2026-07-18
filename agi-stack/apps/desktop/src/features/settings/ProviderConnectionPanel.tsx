import { useEffect, useMemo, useRef, useState } from 'react';
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
  LlmProviderAuthMethod,
  LlmProviderMutationInput,
  LlmProviderProbeInput,
  LlmProviderTypeDescriptor,
  LlmProviderValidationOutcome,
  ManagedLlmProvider,
  RuntimeMode,
} from '../../types';
import {
  providerConfigurationValidationOutcome,
  providerDraftFromProvider,
  providerMutationFromDraft,
  providerProbeInputFromDraft,
  providerProbeInputIsValid,
  providerValidationAccepted,
  type ProviderEditorDraft,
} from './providerManagementModel';

const AUTH_METHOD_ORDER: LlmProviderAuthMethod[] = ['oauth', 'api_key', 'environment', 'none'];

type ProviderConnectionPanelProps = {
  provider: ManagedLlmProvider;
  providerTypeDescriptor?: LlmProviderTypeDescriptor;
  mode: RuntimeMode;
  canManage: boolean;
  onSave: (
    provider: ManagedLlmProvider,
    mutation: LlmProviderMutationInput,
  ) => Promise<ManagedLlmProvider>;
  onValidate: (
    providerId: string,
    expectedRevision: number,
  ) => Promise<LlmProviderValidationOutcome>;
  onValidateDraft: (input: LlmProviderProbeInput) => Promise<LlmProviderValidationOutcome>;
};

export function ProviderConnectionPanel({
  provider,
  providerTypeDescriptor,
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
  const activeProviderIdRef = useRef(provider.id);
  const validationRequestId = useRef(0);
  const saveRequestId = useRef(0);
  activeProviderIdRef.current = provider.id;

  useEffect(() => {
    validationRequestId.current += 1;
    saveRequestId.current += 1;
    setEditing(false);
    setAdvanced(false);
    setShowSecret(false);
    setDraft(providerDraftFromProvider(provider));
    setValidation(null);
    setBusy(null);
    setError(null);
    return () => {
      validationRequestId.current += 1;
      saveRequestId.current += 1;
    };
    // Provider identity is the reset and request-cancellation boundary.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider.id]);

  const mutation = useMemo(() => providerMutationFromDraft(draft), [draft]);
  const probeInput = useMemo(() => providerProbeInputFromDraft(draft), [draft]);
  const normalizedProviderBaseUrl = (provider.base_url ?? '').trim().replace(/\/$/, '');
  const endpointChanged =
    draft.providerType.trim() !== provider.provider_type ||
    draft.baseUrl.trim().replace(/\/$/, '') !== normalizedProviderBaseUrl;
  const credentialRequiredForDraft =
    draft.authMethod === 'api_key' && endpointChanged && !probeInput.apiKey;
  const probeInputValid = providerProbeInputIsValid(
    probeInput,
    provider.credential_configured === true && !endpointChanged,
  );
  const updateDraft = <Key extends keyof ProviderEditorDraft>(
    key: Key,
    value: ProviderEditorDraft[Key],
  ) => {
    if (busy === 'save') return;
    validationRequestId.current += 1;
    setDraft((current) => ({ ...current, [key]: value }));
    setValidation(null);
    setError(null);
    setBusy((current) => (current === 'test' ? null : current));
  };

  const selectAuthMethod = (authMethod: LlmProviderAuthMethod) => {
    if (busy === 'save' || draft.authMethod === authMethod) return;
    validationRequestId.current += 1;
    setDraft((current) => ({
      ...current,
      authMethod,
      apiKey: '',
      environmentVariable: '',
    }));
    setShowSecret(false);
    setValidation(null);
    setError(null);
    setBusy((current) => (current === 'test' ? null : current));
  };

  const testConnection = async () => {
    const requestId = validationRequestId.current + 1;
    validationRequestId.current = requestId;
    const providerId = provider.id;
    const draftProbeInput = probeInput;
    const validateDraft = editing && !(draft.authMethod === 'api_key' && !draftProbeInput.apiKey);
    setBusy('test');
    setError(null);
    setValidation(null);
    if (credentialRequiredForDraft) {
      setError(t('providers.secretRequiredForEndpointChange'));
      setBusy(null);
      return;
    }
    if (!probeInputValid) {
      setError(t('providers.configurationValidationFailed'));
      setBusy(null);
      return;
    }
    try {
      const outcome =
        !editing && !probeSupported
          ? providerConfigurationValidationOutcome(provider)
          : validateDraft
            ? await onValidateDraft(draftProbeInput)
            : await onValidate(providerId, provider.revision ?? 0);
      if (requestId !== validationRequestId.current || providerId !== activeProviderIdRef.current) {
        return;
      }
      setValidation(outcome);
    } catch (caught) {
      if (requestId !== validationRequestId.current || providerId !== activeProviderIdRef.current) {
        return;
      }
      setValidation(null);
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      if (requestId === validationRequestId.current && providerId === activeProviderIdRef.current) {
        setBusy(null);
      }
    }
  };

  const saveConnection = async () => {
    const requestId = saveRequestId.current + 1;
    saveRequestId.current = requestId;
    const providerId = provider.id;
    const draftMutation = mutation;
    setBusy('save');
    setError(null);
    try {
      const updated = await onSave(provider, draftMutation);
      if (requestId !== saveRequestId.current || providerId !== activeProviderIdRef.current) {
        return;
      }
      setEditing(false);
      setDraft(providerDraftFromProvider(updated));
      setShowSecret(false);
    } catch (caught) {
      if (requestId !== saveRequestId.current || providerId !== activeProviderIdRef.current) {
        return;
      }
      setDraft((current) => ({ ...current, apiKey: '' }));
      setValidation(null);
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      if (requestId === saveRequestId.current && providerId === activeProviderIdRef.current) {
        setBusy(null);
      }
    }
  };

  const cancelEdit = () => {
    validationRequestId.current += 1;
    setDraft(providerDraftFromProvider(provider));
    setEditing(false);
    setValidation(null);
    setError(null);
    setBusy((current) => (current === 'test' ? null : current));
  };

  const startEdit = () => {
    validationRequestId.current += 1;
    setDraft(providerDraftFromProvider(provider));
    setEditing(true);
    setValidation(null);
    setError(null);
    setShowSecret(false);
    setBusy((current) => (current === 'test' ? null : current));
  };

  const authMethods = providerTypeDescriptor?.authMethods ?? [];
  const unavailableAuthMethods = providerTypeDescriptor?.unavailableAuthMethods ?? [];
  const authOptions = AUTH_METHOD_ORDER.filter(
    (authMethod) => authMethods.includes(authMethod) || unavailableAuthMethods.includes(authMethod),
  );
  const authMethodUnavailable = (authMethod: LlmProviderAuthMethod) =>
    unavailableAuthMethods.includes(authMethod) || !authMethods.includes(authMethod);
  const authCapabilityAvailable =
    authMethods.includes(draft.authMethod) && !authMethodUnavailable(draft.authMethod);
  const probeSupported = providerTypeDescriptor?.probeSupported !== false;
  const providerHealth = provider.health_status?.trim().toLowerCase();
  const currentProviderVerified =
    !editing &&
    validation == null &&
    error == null &&
    (providerHealth === 'healthy' || providerHealth === 'connected' || providerHealth === 'ready');
  const currentProviderConfigured =
    !editing &&
    validation == null &&
    error == null &&
    !probeSupported &&
    (providerHealth === 'configuration_valid' ||
      (!providerHealth &&
        providerProbeInputIsValid(probeInput, provider.credential_configured === true)));
  const validationAccepted =
    providerValidationAccepted(validation, probeSupported) ||
    currentProviderVerified ||
    currentProviderConfigured;
  const validationAvailable = authCapabilityAvailable;
  const secretDescriptionKey =
    mode === 'local' ? 'providers.secretDescription.local' : 'providers.secretDescription.cloud';
  const credentialValue = editing
    ? draft.apiKey
    : provider.credential_configured === true
      ? provider.api_key_masked || t('providers.credentialConfigured')
      : '';
  const credentialPlaceholder = editing
    ? t('providers.apiKeyPlaceholder')
    : provider.credential_configured === true
      ? t('providers.credentialConfigured')
      : provider.credential_configured === false
        ? t('providers.credentialMissing')
        : t('providers.credentialUnknown');
  const persistedEnvironmentVariable = (provider.environment_variable ?? '').trim();
  const environmentVariableChanged =
    draft.environmentVariable.trim() !== persistedEnvironmentVariable;
  const environmentSecretStatus =
    validation?.probed === true
      ? 'available'
      : validation?.probed === false && validation.status === 'configuration_valid'
        ? 'available'
        : validation?.probed === false
          ? 'unavailable'
          : provider.auth_method === 'environment' && !environmentVariableChanged
            ? provider.credential_configured === true
              ? 'available'
              : provider.credential_configured === false
                ? 'unavailable'
                : 'unknown'
            : 'unknown';
  const environmentSecretStatusKey =
    environmentSecretStatus === 'available'
      ? 'providers.environmentSecretAvailable'
      : environmentSecretStatus === 'unavailable'
        ? 'providers.environmentSecretUnavailable'
        : 'providers.environmentSecretUnknown';
  const environmentSecretHintId = `provider-environment-secret-${provider.id}`;
  const discoveredModelCount = validation?.catalog?.models.length ?? 0;
  const validationDetail =
    error ||
    validation?.errorMessage ||
    (currentProviderVerified
      ? t('providers.connectionPreviouslyVerified')
      : currentProviderConfigured
        ? t('providers.configurationValidationDescription')
        : validationAccepted
          ? discoveredModelCount > 0
            ? t('providers.connectionVerifiedWithModels', {
                count: discoveredModelCount,
              })
            : t('providers.connectionVerifiedDiscoveryUnavailable')
          : validation?.detail ||
            t(
              probeSupported
                ? 'providers.connectionTestDescription'
                : 'providers.configurationValidationDescription',
            ));

  return (
    <section className="provider-form-card">
      <header>
        <div>
          <span>{t('providers.connectionEyebrow')}</span>
          <h3>{t('providers.connectionTitle')}</h3>
          <p>{t('providers.connectionDescription')}</p>
        </div>
        {canManage ? (
          <button
            type="button"
            disabled={busy === 'save'}
            onClick={editing ? cancelEdit : startEdit}
          >
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
          {authOptions.map((authMethod) => {
            const unavailable = authMethodUnavailable(authMethod);
            return (
              <button
                className={`${draft.authMethod === authMethod ? 'selected' : ''} ${
                  unavailable ? 'provider-auth-option-unavailable' : ''
                }`}
                type="button"
                disabled={!editing || busy === 'save' || unavailable}
                aria-pressed={draft.authMethod === authMethod}
                aria-label={`${t(`providers.auth.${authMethod}`)} · ${t(
                  unavailable ? 'providers.authUnavailable' : 'providers.authAvailable',
                )}`}
                key={authMethod}
                onClick={() => selectAuthMethod(authMethod)}
              >
                {authMethod === 'api_key' ? (
                  <LockClosedIcon />
                ) : authMethod === 'environment' ? (
                  <GearIcon />
                ) : authMethod === 'none' ? (
                  <InfoCircledIcon />
                ) : (
                  <Link2Icon />
                )}
                <span>
                  <b>{t(`providers.auth.${authMethod}`)}</b>
                  <small>{t(`providers.auth.${authMethod}Description`)}</small>
                  {unavailable ? <em>{t('providers.authUnavailable')}</em> : null}
                </span>
              </button>
            );
          })}
        </div>
        {authOptions.length === 0 ? (
          <div className="provider-capability-note compact">
            <ExclamationTriangleIcon />
            <span>
              <b>{t('providers.authCapabilityUnavailable')}</b>
              <small>{t('providers.authCapabilityUnavailableDescription')}</small>
            </span>
          </div>
        ) : null}
        {providerTypeDescriptor && !probeSupported ? (
          <div className="provider-capability-note compact" role="status">
            <InfoCircledIcon />
            <span>
              <b>{t('providers.configurationOnlyValidation')}</b>
              <small>{t('providers.configurationOnlyValidationDescription')}</small>
            </span>
          </div>
        ) : null}
        {authCapabilityAvailable ? (
          draft.authMethod === 'api_key' ? (
            <label className="provider-input-label">
              <span>{t('providers.apiKey')}</span>
              <div className="provider-secret-input">
                <input
                  disabled={!editing || busy === 'save'}
                  type={showSecret ? 'text' : 'password'}
                  value={credentialValue}
                  autoComplete="new-password"
                  onChange={(event) => updateDraft('apiKey', event.target.value)}
                  placeholder={credentialPlaceholder}
                />
                <button
                  type="button"
                  disabled={!editing || busy === 'save' || !draft.apiKey}
                  aria-label={t(showSecret ? 'providers.hideSecret' : 'providers.showSecret')}
                  onClick={() => setShowSecret((current) => !current)}
                >
                  {showSecret ? <EyeClosedIcon /> : <EyeOpenIcon />}
                </button>
              </div>
              <small>{t(secretDescriptionKey)}</small>
            </label>
          ) : draft.authMethod === 'environment' ? (
            <label className="provider-input-label">
              <span className="provider-input-label-heading">
                <span>{t('providers.environmentVariable')}</span>
                <em className={`provider-secret-status ${environmentSecretStatus}`} role="status">
                  {t(environmentSecretStatusKey)}
                </em>
              </span>
              <input
                disabled={!editing || busy === 'save'}
                type="text"
                value={draft.environmentVariable}
                autoCapitalize="none"
                autoComplete="off"
                spellCheck={false}
                aria-describedby={environmentSecretHintId}
                onChange={(event) => updateDraft('environmentVariable', event.target.value)}
                placeholder={t('providers.environmentVariablePlaceholder')}
              />
              <small id={environmentSecretHintId}>
                {t('providers.environmentSecretDescription')}
              </small>
            </label>
          ) : draft.authMethod === 'none' ? (
            <div className="provider-capability-note compact">
              <InfoCircledIcon />
              <span>
                <b>{t('providers.noAuthentication')}</b>
                <small>{t('providers.noAuthenticationDescription')}</small>
              </span>
            </div>
          ) : (
            <div className="provider-capability-note compact" role="status">
              <Link2Icon />
              <span>
                <b>{t('providers.authUnavailable')}</b>
                <small>{t('providers.oauthUnavailableDescription')}</small>
              </span>
            </div>
          )
        ) : null}
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
            disabled={!editing || busy === 'save'}
            type="url"
            value={draft.baseUrl}
            onChange={(event) => updateDraft('baseUrl', event.target.value)}
            placeholder="https://api.example.com/v1"
          />
        </label>
        {credentialRequiredForDraft ? (
          <div className="provider-capability-note compact" role="alert">
            <ExclamationTriangleIcon />
            <span>
              <b>{t('providers.secretRequiredForEndpointChange')}</b>
              <small>{t(secretDescriptionKey)}</small>
            </span>
          </div>
        ) : null}
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
                disabled={!editing || busy === 'save'}
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
          className={`provider-test-result ${validationAccepted ? 'success' : validation ? 'failed' : ''}`}
          role="status"
          aria-live="polite"
        >
          {busy === 'test' ? (
            <ReloadIcon className="spin" />
          ) : validationAccepted ? (
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
                  ? probeSupported
                    ? 'providers.testingConnection'
                    : 'providers.validatingConfiguration'
                  : validationAccepted
                    ? probeSupported
                      ? 'providers.connectionVerified'
                      : 'providers.configurationValidated'
                    : validation
                      ? probeSupported
                        ? 'providers.connectionFailed'
                        : 'providers.configurationValidationFailed'
                      : probeSupported
                        ? 'providers.testBeforeSaving'
                        : 'providers.validateBeforeSaving',
              )}
            </b>
            <small>{validationDetail}</small>
          </span>
        </div>
        {canManage ? (
          <button
            type="button"
            disabled={
              busy !== null ||
              !validationAvailable ||
              credentialRequiredForDraft ||
              !probeInputValid
            }
            onClick={() => void testConnection()}
          >
            {t(probeSupported ? 'providers.testConnection' : 'providers.validateConfiguration')}
          </button>
        ) : null}
        {editing ? (
          <button
            className="primary"
            type="button"
            disabled={!validationAccepted || busy !== null}
            onClick={() => void saveConnection()}
          >
            {t('providers.saveConnection')}
          </button>
        ) : null}
      </div>
    </section>
  );
}
