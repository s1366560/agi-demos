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
} from '../../types';
import {
  providerEnabledModelIds,
  providerModelCanBeDisabled,
  providerMutationForEnabledModels,
} from './providerManagementModel';

type ProviderModelsPanelProps = {
  provider: ManagedLlmProvider;
  canManage: boolean;
  onLoadCatalog: (provider: ManagedLlmProvider) => Promise<LlmProviderModelCatalog>;
  onSave: (
    provider: ManagedLlmProvider,
    mutation: LlmProviderMutationInput,
  ) => Promise<ManagedLlmProvider>;
};

type VisibleModel = {
  id: string;
  capability: 'chat' | 'embedding' | 'rerank';
  source: 'catalog' | 'staticFallback' | 'configured';
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
    () => new Set(providerEnabledModelIds(provider)),
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
    setEnabled(new Set(providerEnabledModelIds(provider)));
    setSaving(false);
    setError(null);
    void loadCatalog();
    return () => {
      catalogRequestId.current += 1;
      saveRequestId.current += 1;
    };
    // The provider identity is the reset boundary; the callback is stable in the parent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider.id]);

  const catalogIsStaticFallback = catalog?.source === 'static-fallback';

  const models = useMemo<VisibleModel[]>(() => {
    const byId = new Map<string, VisibleModel>();
    for (const model of catalog?.models ?? []) {
      byId.set(model.id, {
        ...model,
        source: catalogIsStaticFallback ? 'staticFallback' : 'catalog',
      });
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
  }, [catalog, catalogIsStaticFallback, enabled, provider.allowed_models, provider.llm_model]);

  const visibleModels = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return models;
    return models.filter((model) => model.id.toLowerCase().includes(normalized));
  }, [models, query]);

  const configuredModels = provider.allowed_models ?? [];
  const dirty =
    [...enabled].sort().join('\n') !== [...configuredModels].sort().join('\n');

  const toggleModel = (modelId: string) => {
    if (!canManage || !providerModelCanBeDisabled(provider, modelId)) return;
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
      await onSave(provider, providerMutationForEnabledModels(provider, enabled));
    } catch (caught) {
      if (
        requestId !== saveRequestId.current ||
        providerId !== activeProviderIdRef.current
      ) {
        return;
      }
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      if (
        requestId === saveRequestId.current &&
        providerId === activeProviderIdRef.current
      ) {
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
                : 'providers.modelCatalogDescription',
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
                  : 'providers.refreshModels',
            )}
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
                : 'providers.noModelsReturned',
            )}
          </b>
          <span>
            {t(
              catalogUnavailable
                ? 'providers.discoveryUnavailableDescription'
                : catalogIsStaticFallback
                  ? 'providers.noSuggestedModelsDescription'
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
            <small>
              {t(
                catalogIsStaticFallback
                  ? 'providers.addManualModelStaticDescription'
                  : 'providers.addManualModelDescription',
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
