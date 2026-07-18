import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  ArrowRightIcon,
  CheckCircledIcon,
  Cross2Icon,
  CubeIcon,
  ExclamationTriangleIcon,
  LightningBoltIcon,
  PlusIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  LlmProviderAuthMethod,
  LlmProviderCreateInput,
  LlmProviderModelCatalog,
  LlmProviderProbeInput,
  LlmProviderTypeDescriptor,
  LlmProviderValidationOutcome,
  ManagedLlmProvider,
} from '../../types';
import {
  providerAuthMethodSupported,
  providerProbeInputIsValid,
  providerTypeDisplayName,
  providerValidationAccepted,
} from './providerManagementModel';
import { useModalDialog } from './useModalDialog';

const AUTH_METHOD_ORDER: LlmProviderAuthMethod[] = [
  'oauth',
  'api_key',
  'environment',
  'none',
];

type AddProviderDialogProps = {
  onClose: () => void;
  onLoadTypes: () => Promise<LlmProviderTypeDescriptor[]>;
  onValidateDraft: (input: LlmProviderProbeInput) => Promise<LlmProviderValidationOutcome>;
  onCreate: (input: LlmProviderCreateInput) => Promise<ManagedLlmProvider>;
};

const providerDefaults: Record<string, { baseUrl: string }> = {
  openai: {
    baseUrl: 'https://api.openai.com/v1',
  },
  anthropic: {
    baseUrl: 'https://api.anthropic.com/v1',
  },
  openai_compatible: {
    baseUrl: 'http://127.0.0.1:11434/v1',
  },
  azure_openai: { baseUrl: '' },
  ollama: {
    baseUrl: 'http://127.0.0.1:11434',
  },
  lmstudio: {
    baseUrl: 'http://127.0.0.1:1234/v1',
  },
};

export function AddProviderDialog({
  onClose,
  onLoadTypes,
  onValidateDraft,
  onCreate,
}: AddProviderDialogProps) {
  const { t } = useI18n();
  const [step, setStep] = useState(1);
  const [types, setTypes] = useState<LlmProviderTypeDescriptor[]>([]);
  const [selectedType, setSelectedType] = useState('');
  const [name, setName] = useState('');
  const [authMethod, setAuthMethod] = useState<LlmProviderAuthMethod>('api_key');
  const [apiKey, setApiKey] = useState('');
  const [environmentVariable, setEnvironmentVariable] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [primaryModel, setPrimaryModel] = useState('');
  const [catalog, setCatalog] = useState<LlmProviderModelCatalog | null>(null);
  const [selectedModels, setSelectedModels] = useState<Set<string>>(new Set());
  const [validation, setValidation] = useState<LlmProviderValidationOutcome | null>(null);
  const [busy, setBusy] = useState<'types' | 'test' | 'create' | null>('types');
  const [error, setError] = useState<string | null>(null);
  const validationRequestId = useRef(0);
  const onLoadTypesRef = useRef(onLoadTypes);
  onLoadTypesRef.current = onLoadTypes;
  const dialogRef = useModalDialog({ nested: true, onClose });

  const invalidateValidation = () => {
    validationRequestId.current += 1;
    setValidation(null);
    setCatalog(null);
    setPrimaryModel('');
    setSelectedModels(new Set());
    setError(null);
    setBusy((current) => (current === 'test' ? null : current));
  };

  useEffect(() => {
    let cancelled = false;
    void onLoadTypesRef
      .current()
      .then((nextTypes) => {
        if (cancelled) return;
        const chatProviderTypes = nextTypes.filter(
          (descriptor) => descriptor.operationType === 'llm',
        );
        setTypes(chatProviderTypes);
        if (chatProviderTypes[0]) chooseType(chatProviderTypes[0]);
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : String(caught));
      })
      .finally(() => {
        if (!cancelled) setBusy((current) => (current === 'types' ? null : current));
      });
    return () => {
      cancelled = true;
      validationRequestId.current += 1;
    };
    // Dialog callbacks are stable for the lifetime of this modal.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const chooseType = (descriptor: LlmProviderTypeDescriptor) => {
    invalidateValidation();
    const defaults = providerDefaults[descriptor.providerType] ?? {
      baseUrl: '',
    };
    const nextAuth =
      descriptor.authMethods[0] ?? descriptor.unavailableAuthMethods[0] ?? 'api_key';
    setSelectedType(descriptor.providerType);
    setName(providerTypeDisplayName(descriptor.providerType));
    setAuthMethod(nextAuth);
    setBaseUrl(defaults.baseUrl);
    setApiKey('');
    setEnvironmentVariable('');
    setError(null);
  };

  const selectAuthMethod = (nextAuthMethod: LlmProviderAuthMethod) => {
    if (nextAuthMethod === authMethod) return;
    setAuthMethod(nextAuthMethod);
    setApiKey('');
    setEnvironmentVariable('');
    invalidateValidation();
  };

  const probeInput = useMemo<LlmProviderProbeInput>(
    () => ({
      name: name.trim(),
      providerType: selectedType,
      authMethod,
      baseUrl: baseUrl.trim().replace(/\/$/, ''),
      active: true,
      ...(authMethod === 'api_key' && apiKey.trim() ? { apiKey: apiKey.trim() } : {}),
      ...(authMethod === 'environment' && environmentVariable.trim()
        ? { environmentVariable: environmentVariable.trim() }
        : {}),
    }),
    [apiKey, authMethod, baseUrl, environmentVariable, name, selectedType],
  );

  const input = useMemo<LlmProviderCreateInput>(
    () => ({
      name: name.trim(),
      providerType: selectedType,
      authMethod,
      baseUrl: baseUrl.trim().replace(/\/$/, ''),
      primaryModel: primaryModel.trim(),
      allowedModels: [...selectedModels],
      active: true,
      ...(authMethod === 'api_key' && apiKey.trim() ? { apiKey: apiKey.trim() } : {}),
      ...(authMethod === 'environment' && environmentVariable.trim()
        ? { environmentVariable: environmentVariable.trim() }
        : {}),
    }),
    [
      apiKey,
      authMethod,
      baseUrl,
      environmentVariable,
      name,
      primaryModel,
      selectedModels,
      selectedType,
    ],
  );

  const selectedDescriptor = types.find((descriptor) => descriptor.providerType === selectedType);
  const unavailableAuthMethods = selectedDescriptor?.unavailableAuthMethods ?? [];
  const wizardAuthOptions = AUTH_METHOD_ORDER.filter(
    (method) =>
      selectedDescriptor?.authMethods.includes(method) || unavailableAuthMethods.includes(method),
  );
  const authMethodUnavailable = (method: LlmProviderAuthMethod) =>
    unavailableAuthMethods.includes(method) ||
    selectedDescriptor?.authMethods.includes(method) !== true;
  const catalogIsStaticFallback = catalog?.source === 'static-fallback';
  const catalogUnavailable = !catalog || catalog.availability === 'unavailable';
  const probeSupported = selectedDescriptor?.probeSupported === true;
  const authCapabilityAvailable = selectedDescriptor
    ? providerAuthMethodSupported(selectedDescriptor, authMethod)
    : false;

  const formValid = authCapabilityAvailable && providerProbeInputIsValid(probeInput);
  const validationAccepted = providerValidationAccepted(validation, probeSupported);
  const environmentSecretStatus = validation?.probed === true
    ? 'available'
    : validation?.probed === false
      ? 'unavailable'
      : 'unknown';
  const environmentSecretStatusKey =
    environmentSecretStatus === 'available'
      ? 'providers.environmentSecretAvailable'
      : environmentSecretStatus === 'unavailable'
        ? 'providers.environmentSecretUnavailable'
        : 'providers.environmentSecretUnknown';

  const testDraft = async () => {
    const requestId = validationRequestId.current + 1;
    validationRequestId.current = requestId;
    const draftInput = probeInput;
    setBusy('test');
    setError(null);
    setValidation(null);
    setCatalog(null);
    setSelectedModels(new Set());
    setPrimaryModel('');
    try {
      const outcome = await onValidateDraft(draftInput);
      if (requestId !== validationRequestId.current) return;
      setValidation(outcome);
      if (providerValidationAccepted(outcome, probeSupported)) {
        setCatalog(outcome.catalog);
        setSelectedModels(new Set());
        setPrimaryModel('');
      }
    } catch (caught) {
      if (requestId !== validationRequestId.current) return;
      setValidation(null);
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      if (requestId === validationRequestId.current) setBusy(null);
    }
  };

  const createProvider = async () => {
    setBusy('create');
    setError(null);
    try {
      await onCreate(input);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      setBusy(null);
    }
  };

  const toggleCatalogModel = (modelId: string) => {
    if (modelId === primaryModel) return;
    setSelectedModels((current) => {
      const next = new Set(current);
      if (next.has(modelId)) next.delete(modelId);
      else next.add(modelId);
      if (!next.has(primaryModel) && next.size > 0) setPrimaryModel([...next][0]);
      return next;
    });
  };

  return createPortal(
    <div
      className="provider-dialog-backdrop"
      onMouseDown={(event) => {
        event.stopPropagation();
        if (event.target === event.currentTarget && busy !== 'create') onClose();
      }}
    >
      <section
        ref={dialogRef}
        className="provider-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={t('providers.addProvider')}
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <span>{t('providers.productName')}</span>
            <h2>{t('providers.addProviderStep', { step })}</h2>
          </div>
          <button
            type="button"
            disabled={busy === 'create'}
            aria-label={t('providers.closeWizard')}
            onClick={onClose}
          >
            <Cross2Icon />
          </button>
        </header>
        <div className="provider-wizard">
          <div className="provider-wizard-steps">
            {[1, 2, 3].map((value) => (
              <span className={step >= value ? 'active' : ''} key={value}>
                <i>{step > value ? <CheckCircledIcon /> : value}</i>
                {t(`providers.wizard.step${value}`)}
              </span>
            ))}
          </div>

          {step === 1 ? (
            <section>
              <header>
                <h3>{t('providers.chooseProvider')}</h3>
                <p>{t('providers.chooseProviderDescription')}</p>
              </header>
              {busy === 'types' ? (
                <div className="provider-loading-state" role="status" aria-live="polite">
                  <ReloadIcon className="spin" />
                  <span>{t('providers.loadingProviderTypes')}</span>
                </div>
              ) : (
                <div className="provider-option-grid">
                  {types.map((descriptor) => (
                    <button
                      className={selectedType === descriptor.providerType ? 'selected' : ''}
                      type="button"
                      key={descriptor.providerType}
                      onClick={() => chooseType(descriptor)}
                    >
                      <span>
                        <CubeIcon />
                      </span>
                      <div>
                        <b>{providerTypeDisplayName(descriptor.providerType)}</b>
                        <small>
                          {t(
                            descriptor.authMethods.includes('none')
                              ? 'providers.localRuntime'
                              : 'providers.cloudApi',
                          )}
                        </small>
                      </div>
                      {selectedType === descriptor.providerType ? <CheckCircledIcon /> : null}
                    </button>
                  ))}
                </div>
              )}
            </section>
          ) : null}

          {step === 2 ? (
            <section>
              <header>
                <h3>{t('providers.connectProvider', { provider: name })}</h3>
                <p>{t('providers.connectProviderDescription')}</p>
              </header>
              <div className="provider-wizard-form">
                <label>
                  <span>{t('providers.connectionName')}</span>
                  <input
                    value={name}
                    onChange={(event) => {
                      setName(event.target.value);
                      invalidateValidation();
                    }}
                  />
                </label>
                {wizardAuthOptions.length ? (
                  <label>
                    <span>{t('providers.authenticationMethod')}</span>
                    <select
                      value={authMethod}
                      onChange={(event) => {
                        selectAuthMethod(event.target.value as LlmProviderAuthMethod);
                      }}
                    >
                      {wizardAuthOptions.map((method) => (
                        <option
                          value={method}
                          disabled={authMethodUnavailable(method)}
                          key={method}
                        >
                          {t(`providers.auth.${method}`)}
                          {authMethodUnavailable(method)
                            ? ` — ${t('providers.authUnavailable')}`
                            : ''}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <div className="provider-capability-note compact">
                    <ExclamationTriangleIcon />
                    <span>
                      <b>{t('providers.authCapabilityUnavailable')}</b>
                      <small>{t('providers.authCapabilityUnavailableDescription')}</small>
                    </span>
                  </div>
                )}
                {authCapabilityAvailable && authMethod === 'api_key' ? (
                  <label>
                    <span>{t('providers.apiKey')}</span>
                    <input
                      type="password"
                      autoComplete="new-password"
                      value={apiKey}
                      onChange={(event) => {
                        setApiKey(event.target.value);
                        invalidateValidation();
                      }}
                      placeholder={t('providers.apiKeyPlaceholder')}
                    />
                  </label>
                ) : null}
                {authCapabilityAvailable && authMethod === 'environment' ? (
                  <label>
                    <span className="provider-input-label-heading">
                      <span>{t('providers.environmentVariable')}</span>
                      <em
                        className={`provider-secret-status ${environmentSecretStatus}`}
                        role="status"
                      >
                        {t(environmentSecretStatusKey)}
                      </em>
                    </span>
                    <input
                      type="text"
                      autoCapitalize="none"
                      autoComplete="off"
                      spellCheck={false}
                      value={environmentVariable}
                      aria-describedby="provider-wizard-environment-secret-description"
                      onChange={(event) => {
                        setEnvironmentVariable(event.target.value);
                        invalidateValidation();
                      }}
                      placeholder={t('providers.environmentVariablePlaceholder')}
                    />
                    <small id="provider-wizard-environment-secret-description">
                      {t('providers.environmentSecretDescription')}
                    </small>
                  </label>
                ) : null}
                {authCapabilityAvailable && authMethod === 'none' ? (
                  <div className="provider-capability-note compact" role="status">
                    <ExclamationTriangleIcon />
                    <span>
                      <b>{t('providers.noAuthentication')}</b>
                      <small>{t('providers.noAuthenticationDescription')}</small>
                    </span>
                  </div>
                ) : null}
                {authMethod === 'oauth' ? (
                  <div className="provider-capability-note compact" role="status">
                    <ExclamationTriangleIcon />
                    <span>
                      <b>{t('providers.authUnavailable')}</b>
                      <small>{t('providers.oauthUnavailableDescription')}</small>
                    </span>
                  </div>
                ) : null}
                <label>
                  <span>{t('providers.baseUrl')}</span>
                  <input
                    type="url"
                    value={baseUrl}
                    onChange={(event) => {
                      setBaseUrl(event.target.value);
                      invalidateValidation();
                    }}
                    placeholder="https://api.example.com/v1"
                  />
                </label>
                <button
                  className={`provider-wizard-test ${validationAccepted ? 'success' : ''}`}
                  type="button"
                  disabled={!formValid || busy !== null}
                  onClick={() => void testDraft()}
                >
                  {busy === 'test' ? (
                    <ReloadIcon className="spin" />
                  ) : validationAccepted ? (
                    <CheckCircledIcon />
                  ) : (
                    <LightningBoltIcon />
                  )}
                  {t(
                    busy === 'test'
                      ? probeSupported
                        ? 'providers.testingConnection'
                        : 'providers.validatingConfiguration'
                      : validationAccepted
                        ? probeSupported
                          ? 'providers.connectionVerified'
                          : 'providers.configurationValidated'
                        : probeSupported
                          ? 'providers.testConnection'
                          : 'providers.validateConfiguration',
                  )}
                </button>
                {validation && !validationAccepted ? (
                  <div className="provider-inline-error" role="alert">
                    <ExclamationTriangleIcon />
                    <span>{validation.errorMessage || validation.detail || validation.status}</span>
                  </div>
                ) : null}
              </div>
            </section>
          ) : null}

          {step === 3 ? (
            <section>
              <header>
                <h3>
                  {t(
                    catalogIsStaticFallback
                      ? 'providers.enableSuggestedModels'
                      : catalogUnavailable
                        ? 'providers.confirmManualModel'
                        : 'providers.enableModels',
                  )}
                </h3>
                <p>
                  {t(
                    catalogIsStaticFallback
                      ? 'providers.enableSuggestedModelsDescription'
                      : catalogUnavailable
                        ? 'providers.confirmManualModelDescription'
                        : 'providers.enableModelsDescription',
                  )}
                </p>
              </header>
              <div className="provider-wizard-models">
                {(catalog?.models ?? []).length > 0 ? (
                  catalog?.models.map((model) => (
                    <label key={model.id}>
                      <input
                        type="checkbox"
                        checked={selectedModels.has(model.id)}
                        disabled={model.id === primaryModel}
                        onChange={() => toggleCatalogModel(model.id)}
                      />
                      <CubeIcon />
                      <span>
                        <b>{model.id}</b>
                        <small>{t(`providers.capability.${model.capability}`)}</small>
                      </span>
                    </label>
                  ))
                ) : (
                  <div className="provider-wizard-form">
                    <label>
                      <span>{t('providers.manualModel')}</span>
                      <input
                        value={primaryModel}
                        onChange={(event) => {
                          const nextModel = event.target.value;
                          setPrimaryModel(nextModel);
                          setSelectedModels(
                            nextModel.trim() ? new Set([nextModel.trim()]) : new Set(),
                          );
                        }}
                        placeholder="provider/exact-model-id"
                      />
                    </label>
                  </div>
                )}
              </div>
              <div className="provider-capability-note">
                <PlusIcon />
                <span>
                  <b>
                    {t(
                      catalogIsStaticFallback
                        ? 'providers.addMoreSuggestedModelsLater'
                        : catalogUnavailable
                          ? 'providers.addMoreManualModelsLater'
                          : 'providers.addMoreModelsLater',
                    )}
                  </b>
                  <small>
                    {t(
                      catalogIsStaticFallback
                        ? 'providers.addMoreSuggestedModelsLaterDescription'
                        : catalogUnavailable
                          ? 'providers.addMoreManualModelsLaterDescription'
                          : 'providers.addMoreModelsLaterDescription',
                    )}
                  </small>
                </span>
              </div>
            </section>
          ) : null}

          {error ? (
            <div className="provider-inline-error" role="alert">
              <ExclamationTriangleIcon />
              <span>{error}</span>
            </div>
          ) : null}

          <footer>
            <button
              type="button"
              disabled={busy === 'create'}
              onClick={
                step === 1
                  ? onClose
                  : () => {
                      invalidateValidation();
                      setStep((current) => current - 1);
                    }
              }
            >
              {t(step === 1 ? 'providers.cancel' : 'providers.back')}
            </button>
            <button
              className="primary"
              type="button"
              disabled={
                busy !== null ||
                (step === 1 && !selectedType) ||
                (step === 2 && !validationAccepted) ||
                (step === 3 && selectedModels.size === 0)
              }
              onClick={
                step === 3 ? () => void createProvider() : () => setStep((current) => current + 1)
              }
            >
              {t(
                busy === 'create'
                  ? 'providers.addingProvider'
                  : step === 3
                    ? 'providers.addProvider'
                    : 'providers.continue',
              )}
              {busy === 'create' ? <ReloadIcon className="spin" /> : <ArrowRightIcon />}
            </button>
          </footer>
        </div>
      </section>
    </div>,
    document.body,
  );
}
