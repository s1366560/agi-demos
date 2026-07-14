import { useEffect, useMemo, useState } from 'react';
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
} from '../../types';
import {
  providerDraftFromProvider,
  providerMutationFromDraft,
} from './providerManagementModel';

type ProviderModelsPanelProps = {
  provider: ManagedLlmProvider;
  canManage: boolean;
  onLoadCatalog: (providerType: string) => Promise<LlmProviderModelCatalog>;
  onSave: (
    provider: ManagedLlmProvider,
    mutation: LlmProviderMutationInput,
  ) => Promise<ManagedLlmProvider>;
};

type VisibleModel = {
  id: string;
  capability: 'chat' | 'embedding' | 'rerank';
  source: 'catalog' | 'configured';
};

export function ProviderModelsPanel({
  provider,
  canManage,
  onLoadCatalog,
  onSave,
}: ProviderModelsPanelProps) {
  const { t } = useI18n();
  const [catalog, setCatalog] = useState<LlmProviderModelCatalog | null>(null);
  const [query, setQuery] = useState('');
  const [manualModel, setManualModel] = useState('');
  const [enabled, setEnabled] = useState<Set<string>>(
    () => new Set(provider.allowed_models ?? []),
  );
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadCatalog = async () => {
    setLoading(true);
    setError(null);
    try {
      const nextCatalog = await onLoadCatalog(provider.provider_type);
      setCatalog(nextCatalog);
      setEnabled((current) => {
        if (current.size > 0 || nextCatalog.availability !== 'available') return current;
        return new Set(nextCatalog.models.map((model) => model.id));
      });
    } catch (caught) {
      setCatalog(null);
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setCatalog(null);
    setQuery('');
    setManualModel('');
    setEnabled(new Set(provider.allowed_models ?? []));
    setError(null);
    void loadCatalog();
    // The provider identity is the reset boundary; the callback is stable in the parent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider.id]);

  const models = useMemo<VisibleModel[]>(() => {
    const byId = new Map<string, VisibleModel>();
    for (const model of catalog?.models ?? []) {
      byId.set(model.id, { ...model, source: 'catalog' });
    }
    for (const id of provider.allowed_models ?? []) {
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
  }, [catalog, enabled, provider.allowed_models, provider.llm_model]);

  const visibleModels = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return models;
    return models.filter((model) => model.id.toLowerCase().includes(normalized));
  }, [models, query]);

  const configuredModels = provider.allowed_models ?? [];
  const dirty =
    [...enabled].sort().join('\n') !== [...configuredModels].sort().join('\n');

  const toggleModel = (modelId: string) => {
    if (!canManage) return;
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
    setSaving(true);
    setError(null);
    try {
      const draft = providerDraftFromProvider(provider);
      draft.allowedModels = [...enabled].join('\n');
      if (!draft.primaryModel && enabled.size > 0) draft.primaryModel = [...enabled][0];
      await onSave(provider, providerMutationFromDraft(draft));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSaving(false);
    }
  };

  const catalogUnavailable = catalog?.availability === 'unavailable';

  return (
    <section className="provider-model-catalog">
      <header>
        <div>
          <span>{t('providers.modelCatalogEyebrow')}</span>
          <h3>{t('providers.modelCatalogTitle')}</h3>
          <p>{t('providers.modelCatalogDescription')}</p>
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
            {t(loading ? 'providers.loadingModels' : 'providers.refreshModels')}
          </button>
        )}
      </header>

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
          {t('providers.modelCounts', { enabled: enabled.size, discovered: models.length })}
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
                </span>
              </div>
              <div className="provider-capabilities">
                <span>{t(`providers.capability.${model.capability}`)}</span>
              </div>
              <span>{t(`providers.source.${model.source}`)}</span>
              <button
                className={`provider-switch ${enabled.has(model.id) ? 'on' : ''}`}
                type="button"
                role="switch"
                aria-label={t('providers.toggleModel', { model: model.id })}
                aria-checked={enabled.has(model.id)}
                disabled={!canManage}
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
                : 'providers.noModelsReturned',
            )}
          </b>
          <span>
            {t(
              catalogUnavailable
                ? 'providers.discoveryUnavailableDescription'
                : 'providers.noModelsReturnedDescription',
            )}
          </span>
        </div>
      )}

      <div className="provider-manual-model">
        <div>
          <SewingPinIcon />
          <span>
            <b>{t('providers.addManualModel')}</b>
            <small>{t('providers.addManualModelDescription')}</small>
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
