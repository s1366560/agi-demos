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
  LlmProviderCreateInput,
  LlmProviderModelCatalog,
  LlmProviderTypeDescriptor,
  LlmProviderValidationOutcome,
  ManagedLlmProvider,
} from '../../types';
import {
  providerAuthMethodSupported,
  providerTypeDisplayName,
  providerValidationSucceeded,
} from './providerManagementModel';
import { useModalDialog } from './useModalDialog';

type AddProviderDialogProps = {
  onClose: () => void;
  onLoadTypes: () => Promise<LlmProviderTypeDescriptor[]>;
  onLoadCatalog: (providerType: string) => Promise<LlmProviderModelCatalog>;
  onValidateDraft: (input: LlmProviderCreateInput) => Promise<LlmProviderValidationOutcome>;
  onCreate: (input: LlmProviderCreateInput) => Promise<ManagedLlmProvider>;
};

const providerDefaults: Record<string, { baseUrl: string; model: string }> = {
  openai: {
    baseUrl: 'https://api.openai.com/v1',
    model: 'gpt-4o-mini',
  },
  anthropic: {
    baseUrl: 'https://api.anthropic.com',
    model: 'claude-3-5-sonnet-latest',
  },
  openai_compatible: {
    baseUrl: 'http://127.0.0.1:11434/v1',
    model: '',
  },
  azure_openai: { baseUrl: '', model: '' },
  ollama: {
    baseUrl: 'http://127.0.0.1:11434',
    model: '',
  },
  lmstudio: {
    baseUrl: 'http://127.0.0.1:1234/v1',
    model: '',
  },
};

export function AddProviderDialog({
  onClose,
  onLoadTypes,
  onLoadCatalog,
  onValidateDraft,
  onCreate,
}: AddProviderDialogProps) {
  const { t } = useI18n();
  const [step, setStep] = useState(1);
  const [types, setTypes] = useState<LlmProviderTypeDescriptor[]>([]);
  const [selectedType, setSelectedType] = useState('');
  const [name, setName] = useState('');
  const [authMethod, setAuthMethod] = useState<'api_key' | 'none'>('api_key');
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [primaryModel, setPrimaryModel] = useState('');
  const [catalog, setCatalog] = useState<LlmProviderModelCatalog | null>(null);
  const [selectedModels, setSelectedModels] = useState<Set<string>>(new Set());
  const [validation, setValidation] = useState<LlmProviderValidationOutcome | null>(null);
  const [busy, setBusy] = useState<'types' | 'catalog' | 'test' | 'create' | null>('types');
  const [error, setError] = useState<string | null>(null);
  const catalogRequestId = useRef(0);
  const validationRequestId = useRef(0);
  const onLoadCatalogRef = useRef(onLoadCatalog);
  const onLoadTypesRef = useRef(onLoadTypes);
  onLoadCatalogRef.current = onLoadCatalog;
  onLoadTypesRef.current = onLoadTypes;
  const dialogRef = useModalDialog({ nested: true, onClose });

  const invalidateValidation = () => {
    validationRequestId.current += 1;
    setValidation(null);
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
          (descriptor) => descriptor.operationType === 'llm' && descriptor.probeSupported,
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
      catalogRequestId.current += 1;
      validationRequestId.current += 1;
    };
    // Dialog callbacks are stable for the lifetime of this modal.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const chooseType = (descriptor: LlmProviderTypeDescriptor) => {
    invalidateValidation();
    const requestId = catalogRequestId.current + 1;
    catalogRequestId.current = requestId;
    const defaults = providerDefaults[descriptor.providerType] ?? {
      baseUrl: '',
      model: '',
    };
    const nextAuth = descriptor.authMethods[0] || 'api_key';
    setSelectedType(descriptor.providerType);
    setName(providerTypeDisplayName(descriptor.providerType));
    setAuthMethod(nextAuth);
    setBaseUrl(defaults.baseUrl);
    setPrimaryModel(defaults.model);
    setApiKey('');
    setCatalog(null);
    setSelectedModels(defaults.model ? new Set([defaults.model]) : new Set());
    setBusy('catalog');
    setError(null);
    void onLoadCatalogRef
      .current(descriptor.providerType)
      .then((nextCatalog) => {
        if (requestId !== catalogRequestId.current) return;
        setCatalog(nextCatalog);
        const firstModel = nextCatalog.models.find((model) => model.capability === 'chat')?.id;
        if (firstModel) {
          setPrimaryModel(firstModel);
          setSelectedModels(new Set([firstModel]));
        }
      })
      .catch((caught) => {
        if (requestId !== catalogRequestId.current) return;
        setError(caught instanceof Error ? caught.message : String(caught));
      })
      .finally(() => {
        if (requestId === catalogRequestId.current) setBusy(null);
      });
  };

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
    }),
    [apiKey, authMethod, baseUrl, name, primaryModel, selectedModels, selectedType],
  );

  const selectedDescriptor = types.find((descriptor) => descriptor.providerType === selectedType);
  const authCapabilityAvailable = selectedDescriptor
    ? providerAuthMethodSupported(selectedDescriptor, authMethod)
    : false;

  const formValid = Boolean(
    input.name &&
      input.providerType &&
      authCapabilityAvailable &&
      input.baseUrl &&
      input.primaryModel &&
      (input.authMethod === 'none' || input.apiKey),
  );
  const verified = providerValidationSucceeded(validation);

  const testDraft = async () => {
    const requestId = validationRequestId.current + 1;
    validationRequestId.current = requestId;
    const draftInput = input;
    setBusy('test');
    setError(null);
    setValidation(null);
    try {
      const outcome = await onValidateDraft(draftInput);
      if (requestId !== validationRequestId.current) return;
      setValidation(outcome);
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

  const toggleDiscoveredModel = (modelId: string) => {
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
                {selectedDescriptor?.authMethods.length ? (
                  <label>
                    <span>{t('providers.authenticationMethod')}</span>
                    <select
                      value={authMethod}
                      onChange={(event) => {
                        setAuthMethod(event.target.value === 'none' ? 'none' : 'api_key');
                        invalidateValidation();
                      }}
                    >
                      {selectedDescriptor.authMethods.map((method) => (
                        <option value={method} key={method}>
                          {t(`providers.auth.${method}`)}
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
                <label>
                  <span>{t('providers.testModelId')}</span>
                  <input
                    value={primaryModel}
                    onChange={(event) => {
                      const next = event.target.value;
                      setPrimaryModel(next);
                      setSelectedModels(next.trim() ? new Set([next.trim()]) : new Set());
                      invalidateValidation();
                    }}
                    placeholder="provider/exact-model-id"
                  />
                </label>
                <button
                  className={`provider-wizard-test ${verified ? 'success' : ''}`}
                  type="button"
                  disabled={!formValid || busy !== null}
                  onClick={() => void testDraft()}
                >
                  {busy === 'test' ? (
                    <ReloadIcon className="spin" />
                  ) : verified ? (
                    <CheckCircledIcon />
                  ) : (
                    <LightningBoltIcon />
                  )}
                  {t(
                    busy === 'test'
                      ? 'providers.testingConnection'
                      : verified
                        ? 'providers.connectionVerified'
                          : 'providers.testConnection',
                  )}
                </button>
                {validation && !verified ? (
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
                <h3>{t('providers.enableModels')}</h3>
                <p>{t('providers.enableModelsDescription')}</p>
              </header>
              <div className="provider-wizard-models">
                {(catalog?.models ?? []).length > 0 ? (
                  catalog?.models.map((model) => (
                    <label key={model.id}>
                      <input
                        type="checkbox"
                        checked={selectedModels.has(model.id)}
                        disabled={model.id === primaryModel}
                        onChange={() => toggleDiscoveredModel(model.id)}
                      />
                      <CubeIcon />
                      <span>
                        <b>{model.id}</b>
                        <small>{t(`providers.capability.${model.capability}`)}</small>
                      </span>
                    </label>
                  ))
                ) : (
                  <label>
                    <input type="checkbox" checked readOnly />
                    <CubeIcon />
                    <span>
                      <b>{primaryModel}</b>
                      <small>{t('providers.manualModel')}</small>
                    </span>
                  </label>
                )}
              </div>
              <div className="provider-capability-note">
                <PlusIcon />
                <span>
                  <b>{t('providers.addMoreModelsLater')}</b>
                  <small>{t('providers.addMoreModelsLaterDescription')}</small>
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
                (step === 2 && !verified) ||
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
