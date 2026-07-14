import { useEffect, useMemo, useState } from 'react';
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
  RuntimeMode,
} from '../../types';
import { providerTypeDisplayName } from './providerManagementModel';

type AddProviderDialogProps = {
  mode: RuntimeMode;
  onClose: () => void;
  onLoadTypes: () => Promise<LlmProviderTypeDescriptor[]>;
  onLoadCatalog: (providerType: string) => Promise<LlmProviderModelCatalog>;
  onValidateDraft: (
    input: LlmProviderCreateInput,
  ) => Promise<LlmProviderValidationOutcome>;
  onCreate: (input: LlmProviderCreateInput) => Promise<ManagedLlmProvider>;
};

const providerDefaults: Record<
  string,
  { baseUrl: string; model: string; authMethod: 'api_key' | 'none' }
> = {
  openai: {
    baseUrl: 'https://api.openai.com/v1',
    model: 'gpt-4o-mini',
    authMethod: 'api_key',
  },
  anthropic: {
    baseUrl: 'https://api.anthropic.com',
    model: 'claude-3-5-sonnet-latest',
    authMethod: 'api_key',
  },
  openai_compatible: {
    baseUrl: 'http://127.0.0.1:11434/v1',
    model: '',
    authMethod: 'none',
  },
  azure_openai: { baseUrl: '', model: '', authMethod: 'api_key' },
  ollama: {
    baseUrl: 'http://127.0.0.1:11434/v1',
    model: '',
    authMethod: 'none',
  },
  lmstudio: {
    baseUrl: 'http://127.0.0.1:1234/v1',
    model: '',
    authMethod: 'none',
  },
};

function validationSucceeded(outcome: LlmProviderValidationOutcome | null): boolean {
  return outcome?.status === 'healthy' || outcome?.status === 'configuration_valid';
}

export function AddProviderDialog({
  mode,
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

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    void onLoadTypes()
      .then((nextTypes) => {
        setTypes(nextTypes);
        if (nextTypes[0]) chooseType(nextTypes[0]);
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)))
      .finally(() => setBusy((current) => (current === 'types' ? null : current)));
    return () => window.removeEventListener('keydown', handleKeyDown);
    // Dialog callbacks are stable for the lifetime of this modal.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const chooseType = (descriptor: LlmProviderTypeDescriptor) => {
    const defaults = providerDefaults[descriptor.providerType] ?? {
      baseUrl: '',
      model: '',
      authMethod: 'api_key' as const,
    };
    const nextAuth = descriptor.authMethods.includes(defaults.authMethod)
      ? defaults.authMethod
      : descriptor.authMethods[0] || 'api_key';
    setSelectedType(descriptor.providerType);
    setName(providerTypeDisplayName(descriptor.providerType));
    setAuthMethod(nextAuth);
    setBaseUrl(defaults.baseUrl);
    setPrimaryModel(defaults.model);
    setApiKey('');
    setValidation(null);
    setCatalog(null);
    setSelectedModels(defaults.model ? new Set([defaults.model]) : new Set());
    setBusy('catalog');
    setError(null);
    void onLoadCatalog(descriptor.providerType)
      .then((nextCatalog) => {
        setCatalog(nextCatalog);
        const firstModel = nextCatalog.models.find((model) => model.capability === 'chat')?.id;
        if (firstModel) {
          setPrimaryModel(firstModel);
          setSelectedModels(new Set([firstModel]));
        }
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)))
      .finally(() => setBusy(null));
  };

  const input = useMemo<LlmProviderCreateInput>(
    () => ({
      name: name.trim(),
      providerType: selectedType,
      authMethod,
      baseUrl: baseUrl.trim().replace(/\/$/, ''),
      primaryModel: primaryModel.trim(),
      allowedModels: [...selectedModels],
      active: false,
      ...(authMethod === 'api_key' && apiKey.trim() ? { apiKey: apiKey.trim() } : {}),
    }),
    [apiKey, authMethod, baseUrl, name, primaryModel, selectedModels, selectedType],
  );

  const formValid = Boolean(
    input.name &&
      input.providerType &&
      input.baseUrl &&
      input.primaryModel &&
      (input.authMethod === 'none' || input.apiKey),
  );
  const verified = validationSucceeded(validation);

  const testDraft = async () => {
    setBusy('test');
    setError(null);
    try {
      setValidation(await onValidateDraft(input));
    } catch (caught) {
      setValidation(null);
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
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
    setSelectedModels((current) => {
      const next = new Set(current);
      if (next.has(modelId)) next.delete(modelId);
      else next.add(modelId);
      if (!next.has(primaryModel) && next.size > 0) setPrimaryModel([...next][0]);
      return next;
    });
  };

  return createPortal(
    <div className="provider-dialog-backdrop" onMouseDown={onClose}>
      <section
        className="provider-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={t('providers.addProvider')}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <span>{t('providers.productName')}</span>
            <h2>{t('providers.addProviderStep', { step })}</h2>
          </div>
          <button type="button" aria-label={t('providers.closeWizard')} onClick={onClose}>
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
                <div className="provider-loading-state">
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
                            descriptor.source === 'local_runtime'
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
                <p>
                  {t(
                    mode === 'local'
                      ? 'providers.connectProviderLocalDescription'
                      : 'providers.connectProviderDescription',
                  )}
                </p>
              </header>
              <div className="provider-wizard-form">
                <label>
                  <span>{t('providers.connectionName')}</span>
                  <input
                    value={name}
                    onChange={(event) => {
                      setName(event.target.value);
                      setValidation(null);
                    }}
                  />
                </label>
                {types.find((type) => type.providerType === selectedType)?.authMethods.length ? (
                  <label>
                    <span>{t('providers.authenticationMethod')}</span>
                    <select
                      value={authMethod}
                      onChange={(event) => {
                        setAuthMethod(event.target.value === 'none' ? 'none' : 'api_key');
                        setValidation(null);
                      }}
                    >
                      {types
                        .find((type) => type.providerType === selectedType)
                        ?.authMethods.map((method) => (
                          <option value={method} key={method}>
                            {t(`providers.auth.${method}`)}
                          </option>
                        ))}
                    </select>
                  </label>
                ) : null}
                {authMethod === 'api_key' ? (
                  <label>
                    <span>{t('providers.apiKey')}</span>
                    <input
                      type="password"
                      autoComplete="new-password"
                      value={apiKey}
                      onChange={(event) => {
                        setApiKey(event.target.value);
                        setValidation(null);
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
                      setValidation(null);
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
                      setValidation(null);
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
                      ? mode === 'local'
                        ? 'providers.validatingConfiguration'
                        : 'providers.testingConnection'
                      : verified
                        ? mode === 'local'
                          ? 'providers.configurationValid'
                          : 'providers.connectionVerified'
                        : mode === 'local'
                          ? 'providers.validateConfiguration'
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
              onClick={step === 1 ? onClose : () => setStep((current) => current - 1)}
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
                step === 3
                  ? () => void createProvider()
                  : () => setStep((current) => current + 1)
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
