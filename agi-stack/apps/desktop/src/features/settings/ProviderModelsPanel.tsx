import { useEffect, useMemo, useRef, useState } from 'react';
import {
  CheckCircledIcon,
  CubeIcon,
  ExclamationTriangleIcon,
  MagnifyingGlassIcon,
  PlusIcon,
  ReloadIcon,
  SewingPinIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  LlmProviderModelCatalog,
  LlmProviderMutationInput,
  ManagedLlmProvider,
  RuntimeMode,
} from '../../types';
import {
  modelProfileFacts,
  providerEnabledModelIds,
  providerAudioInputDeclarationSupported,
  providerModelCanBeDisabled,
  providerMutationForEnabledModels,
} from './providerManagementModel';
import { ProviderEmbeddingDeclarationField } from './ProviderEmbeddingDeclarationField';
import { boundaryForCapability } from './modelRoleFit';

type ProviderModelsPanelProps = {
  provider: ManagedLlmProvider;
  mode?: RuntimeMode;
  canManage: boolean;
  allowEmbeddingDeclaration?: boolean;
  allowAudioInputDeclaration?: boolean;
  onLoadCatalog: (provider: ManagedLlmProvider) => Promise<LlmProviderModelCatalog>;
  onSave: (
    provider: ManagedLlmProvider,
    mutation: LlmProviderMutationInput
  ) => Promise<ManagedLlmProvider>;
};

type VisibleModel = {
  id: string;
  capability: 'chat' | 'embedding' | 'rerank';
  source: 'catalog' | 'staticFallback' | 'configured';
  profile?: LlmProviderModelCatalog['models'][number]['profile'];
};

export function ProviderModelsPanel({
  provider,
  mode = 'local',
  canManage,
  allowEmbeddingDeclaration = false,
  allowAudioInputDeclaration = false,
  onLoadCatalog,
  onSave,
}: ProviderModelsPanelProps) {
  const { t } = useI18n();
  const [catalog, setCatalog] = useState<LlmProviderModelCatalog | null>(null);
  const [embeddingModel, setEmbeddingModel] = useState(provider.embedding_model ?? '');
  useEffect(() => {
    setEmbeddingModel(provider.embedding_model ?? '');
  }, [provider.id, provider.revision, canManage, provider.embedding_model]);
  const [query, setQuery] = useState('');
  const [manualModel, setManualModel] = useState('');
  const [enabled, setEnabled] = useState<Set<string>>(
    () => new Set(providerEnabledModelIds(provider, mode))
  );
  const [audioInputModels, setAudioInputModels] = useState<Set<string>>(
    () => new Set(provider.audio_input_models ?? [])
  );
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const catalogRequestId = useRef(0);
  const saveRequestId = useRef(0);
  const activeProviderIdRef = useRef(provider.id);
  const onLoadCatalogRef = useRef(onLoadCatalog);
  activeProviderIdRef.current = provider.id;
  onLoadCatalogRef.current = onLoadCatalog;

  const loadCatalog = async () => {
    const requestId = catalogRequestId.current + 1;
    catalogRequestId.current = requestId;
    setLoading(true);
    setError(null);
    try {
      const nextCatalog = await onLoadCatalogRef.current(provider);
      if (requestId !== catalogRequestId.current) return;
      setCatalog(nextCatalog);
    } catch (caught) {
      if (requestId !== catalogRequestId.current) return;
      setCatalog(null);
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      if (requestId === catalogRequestId.current) setLoading(false);
    }
  };

  useEffect(() => {
    setCatalog(null);
    setQuery('');
    setManualModel('');
    catalogRequestId.current += 1;
    saveRequestId.current += 1;
    setEnabled(new Set(providerEnabledModelIds(provider, mode)));
    setAudioInputModels(new Set(provider.audio_input_models ?? []));
    setSaving(false);
    setError(null);
    void loadCatalog();
    return () => {
      catalogRequestId.current += 1;
      saveRequestId.current += 1;
    };
    // A new persisted revision invalidates catalog results and unsaved selections.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider.id, provider.revision, mode]);

  const catalogIsStaticFallback = catalog?.source === 'static-fallback';

  const models = useMemo<VisibleModel[]>(() => {
    const byId = new Map<string, VisibleModel>();
    const catalogSource = catalogIsStaticFallback ? 'staticFallback' : 'catalog';
    for (const model of catalog?.models ?? []) {
      byId.set(model.id, {
        ...model,
        source: model.id === provider.embedding_model ? 'configured' : catalogSource,
      });
    }
    for (const id of providerEnabledModelIds(provider, mode)) {
      if (!byId.has(id)) byId.set(id, { id, capability: 'chat', source: 'configured' });
    }
    if (provider.llm_model && !byId.has(provider.llm_model)) {
      byId.set(provider.llm_model, {
        id: provider.llm_model,
        capability: 'chat',
        source: 'configured',
      });
    }
    for (const id of enabled) {
      if (!byId.has(id)) byId.set(id, { id, capability: 'chat', source: 'configured' });
    }
    return [...byId.values()];
  }, [
    catalog,
    catalogIsStaticFallback,
    enabled,
    provider.allowed_models,
    provider.llm_model,
    provider.llm_small_model,
    provider.secondary_models,
    provider.embedding_model,
    mode,
  ]);

  const visibleModels = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return models;
    return models.filter((model) => model.id.toLowerCase().includes(normalized));
  }, [models, query]);

  const configuredModels = providerEnabledModelIds(provider, mode);
  const canDeclareAudioInput =
    allowAudioInputDeclaration && providerAudioInputDeclarationSupported(provider.provider_type);
  const dirty =
    [...enabled].sort().join('\n') !== [...configuredModels].sort().join('\n') ||
    (allowEmbeddingDeclaration && embeddingModel !== (provider.embedding_model ?? '')) ||
    (canDeclareAudioInput &&
      [...audioInputModels].sort().join('\n') !==
        [...(provider.audio_input_models ?? [])].sort().join('\n'));

  const toggleModel = (modelId: string) => {
    if (!canManage || !providerModelCanBeDisabled(provider, modelId)) return;
    if (enabled.has(modelId) && embeddingModel === modelId) setEmbeddingModel('');
    if (enabled.has(modelId))
      setAudioInputModels((current) => {
        const next = new Set(current);
        next.delete(modelId);
        return next;
      });
    setEnabled((current) => {
      const next = new Set(current);
      if (next.has(modelId)) next.delete(modelId);
      else next.add(modelId);
      return next;
    });
  };

  const addManualModel = () => {
    const id = manualModel.trim();
    if (!id) return;
    setEnabled((current) => new Set([...current, id]));
    setManualModel('');
  };

  const saveModels = async () => {
    const requestId = saveRequestId.current + 1;
    saveRequestId.current = requestId;
    const providerId = provider.id;
    setSaving(true);
    setError(null);
    try {
      await onSave(provider, {
        ...providerMutationForEnabledModels(provider, enabled, mode),
        ...(allowEmbeddingDeclaration ? { embeddingModel } : {}),
        ...(canDeclareAudioInput
          ? {
              audioInputModels: [...audioInputModels].filter((model) => enabled.has(model)),
            }
          : {}),
      });
    } catch (caught) {
      if (requestId !== saveRequestId.current || providerId !== activeProviderIdRef.current) {
        return;
      }
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      if (requestId === saveRequestId.current && providerId === activeProviderIdRef.current) {
        setSaving(false);
      }
    }
  };

  const catalogUnavailable = catalog?.availability === 'unavailable';

  return (
    <section className="provider-model-catalog">
      <header>
        <div>
          <span>{t('providers.modelCatalogEyebrow')}</span>
          <h3>{t('providers.modelCatalogTitle')}</h3>
          <p>
            {t(
              catalogIsStaticFallback
                ? 'providers.staticCatalogDescription'
                : 'providers.modelCatalogDescription'
            )}
          </p>
        </div>
        {dirty ? (
          <button
            className="primary"
            type="button"
            disabled={!canManage || saving || enabled.size === 0}
            onClick={() => void saveModels()}
          >
            <CheckCircledIcon />
            {t(saving ? 'providers.savingModels' : 'providers.saveModels')}
          </button>
        ) : (
          <button type="button" disabled={loading} onClick={() => void loadCatalog()}>
            <ReloadIcon className={loading ? 'spin' : ''} />
            {t(
              catalogIsStaticFallback
                ? loading
                  ? 'providers.loadingStaticCatalog'
                  : 'providers.reloadStaticCatalog'
                : loading
                  ? 'providers.loadingModels'
                  : 'providers.refreshModels'
            )}
          </button>
        )}
      </header>

      <div className="provider-role-guide">
        {(['primary', 'fast', 'embedding', 'rerank', 'voice'] as const).map((role) => (
          <p key={role}>
            <b>{t(`providers.role.${role}`)}</b>
            <span>{t(`providers.rolePurpose.${role}`)}</span>
          </p>
        ))}
      </div>

      {models.some(
        (model) => model.id === provider.llm_model && model.capability !== 'chat'
      ) ? (
        <div className="provider-inline-error" role="status">
          <ExclamationTriangleIcon />
          <span>{t('providers.roleReason.not_a_chat_model')}</span>
        </div>
      ) : null}

      {allowEmbeddingDeclaration ? (
        <ProviderEmbeddingDeclarationField
          value={embeddingModel}
          models={[...enabled]}
          disabled={!canManage || saving}
          onChange={setEmbeddingModel}
        />
      ) : null}

      {canDeclareAudioInput ? (
        <p className="provider-audio-declaration-help">
          {t('providers.audioInputDeclarationHelp')}
        </p>
      ) : null}

      <div className="provider-model-tools">
        <label>
          <MagnifyingGlassIcon />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('providers.searchModelIds')}
          />
        </label>
        <span>
          {catalogIsStaticFallback
            ? t('providers.staticModelCounts', {
                enabled: enabled.size,
                suggested: catalog?.models.length ?? 0,
              })
            : t('providers.modelCounts', {
                enabled: enabled.size,
                discovered: catalog?.models.length ?? 0,
              })}
        </span>
      </div>

      {error ? (
        <div className="provider-inline-error" role="alert">
          <ExclamationTriangleIcon />
          <span>{error}</span>
        </div>
      ) : null}

      {visibleModels.length > 0 ? (
        <div className="provider-model-table">
          <div className="provider-model-table-head">
            <span>{t('providers.model')}</span>
            <span>{t('providers.capability')}</span>
            <span>{t('providers.source')}</span>
            <span>{t('providers.available')}</span>
          </div>
          {visibleModels.map((model) => (
            <div className="provider-model-row" key={model.id}>
              <div>
                <CubeIcon />
                <span>
                  <b>{model.id}</b>
                  <small>
                    {model.id === provider.llm_model
                      ? t('providers.currentDefault')
                      : t('providers.exactModelId')}
                  </small>
                  <small>
                    {t(`providers.roleReason.${
                      boundaryForCapability(
                        model.capability,
                        audioInputModels.has(model.id),
                        canDeclareAudioInput
                      ).reason
                    }`)}
                  </small>
                  <ModelProfileLine profile={model.profile} />
                </span>
              </div>
              <div className="provider-capabilities">
                <span>{t(`providers.capability.${model.capability}`)}</span>
                {canDeclareAudioInput ? (
                  <label className="provider-audio-declaration">
                    <input
                      type="checkbox"
                      aria-label={t('providers.audioInputDeclarationToggle', {
                        model: model.id,
                      })}
                      checked={audioInputModels.has(model.id)}
                      disabled={!canManage || saving || !enabled.has(model.id)}
                      onChange={(event) => {
                        if (!canManage || saving || !enabled.has(model.id)) return;
                        const checked = event.target.checked;
                        setAudioInputModels((current) => {
                          const next = new Set(current);
                          if (checked) next.add(model.id);
                          else next.delete(model.id);
                          return next;
                        });
                      }}
                    />
                    {t('providers.audioInputDeclaration')}
                  </label>
                ) : null}
              </div>
              <span>{t(`providers.source.${model.source}`)}</span>
              <button
                className={`provider-switch ${enabled.has(model.id) ? 'on' : ''}`}
                type="button"
                role="switch"
                aria-label={t('providers.toggleModel', { model: model.id })}
                aria-checked={enabled.has(model.id)}
                disabled={!canManage || !providerModelCanBeDisabled(provider, model.id)}
                title={
                  providerModelCanBeDisabled(provider, model.id)
                    ? undefined
                    : t('providers.currentDefault')
                }
                onClick={() => toggleModel(model.id)}
              >
                <i />
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div className="provider-empty-state large">
          <ExclamationTriangleIcon />
          <b>
            {t(
              catalogUnavailable
                ? 'providers.discoveryUnavailable'
                : catalogIsStaticFallback
                  ? 'providers.noSuggestedModels'
                  : 'providers.noModelsReturned'
            )}
          </b>
          <span>
            {t(
              catalogUnavailable
                ? 'providers.discoveryUnavailableDescription'
                : catalogIsStaticFallback
                  ? 'providers.noSuggestedModelsDescription'
                  : 'providers.noModelsReturnedDescription'
            )}
          </span>
        </div>
      )}

      <div className="provider-manual-model">
        <div>
          <SewingPinIcon />
          <span>
            <b>{t('providers.addManualModel')}</b>
            <small>
              {t(
                catalogIsStaticFallback
                  ? 'providers.addManualModelStaticDescription'
                  : 'providers.addManualModelDescription'
              )}
            </small>
          </span>
        </div>
        <label>
          <input
            value={manualModel}
            disabled={!canManage}
            onChange={(event) => setManualModel(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                addManualModel();
              }
            }}
            placeholder="provider/exact-model-id"
          />
          <button
            type="button"
            disabled={!canManage || !manualModel.trim()}
            onClick={addManualModel}
          >
            <PlusIcon />
            {t('providers.addModel')}
          </button>
        </label>
      </div>
    </section>
  );
}

function ModelProfileLine({ profile }: { profile: VisibleModel['profile'] }) {
  const { t } = useI18n();
  const facts = modelProfileFacts(profile);
  if (!facts) return null;
  const input = facts.inputCost == null ? '?' : `$${String(facts.inputCost)}`;
  const output = facts.outputCost == null ? '?' : `$${String(facts.outputCost)}`;
  const price =
    facts.inputCost == null && facts.outputCost == null
      ? t('providers.profile.priceUnknown')
      : t('providers.profile.price', { input, output });
  return (
    <small className="provider-model-limits">
      {facts.deprecated ? <b>{t('providers.profile.deprecated')}</b> : null}
      {facts.context ? <span>{t('providers.profile.context', { value: facts.context })}</span> : null}
      {facts.maxOutput ? (
        <span>{t('providers.profile.maxOutput', { value: facts.maxOutput })}</span>
      ) : null}
      <span>{price}</span>
      {facts.flags.map((flag) => (
        <span key={flag}>{t(`providers.profile.flag.${flag}`)}</span>
      ))}
    </small>
  );
}
