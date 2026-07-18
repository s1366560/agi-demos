import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowRightIcon,
  CopyIcon,
  CubeIcon,
  ExclamationTriangleIcon,
  LockClosedIcon,
  MagnifyingGlassIcon,
  PlusIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import { DesktopApiClient, DesktopApiError } from '../../api/client';
import { useI18n } from '../../i18n';
import type {
  DesktopRuntimeConfig,
  LocalRuntimeProvider,
  LlmProviderCreateInput,
  LlmProviderModelCatalog,
  LlmProviderMutationInput,
  LlmProviderRoutingPolicy,
  LlmProviderRoutingPolicyMutationInput,
  LlmProviderTypeDescriptor,
  LlmProviderValidationOutcome,
  ManagedLlmProvider,
} from '../../types';
import { AddProviderDialog } from './AddProviderDialog';
import { ProviderConnectionPanel } from './ProviderConnectionPanel';
import { ProviderModelsPanel } from './ProviderModelsPanel';
import {
  ProviderOverviewPanel,
  ProviderRoutingPanel,
  ProviderUsagePanel,
  type ProviderTab,
} from './ProviderOverviewPanels';
import { ProviderStatusBadge } from './ProviderStatusBadge';
import {
  filterProviders,
  providerModelsFromProvider,
  providerTypeDisplayName,
  type ProviderListFilter,
} from './providerManagementModel';
import './ModelProviderWorkspace.css';

type ModelProviderWorkspaceProps = {
  config: DesktopRuntimeConfig;
  runtimeProvider: LocalRuntimeProvider | null;
  canManage: boolean;
  onRuntimeStatusRefresh: () => Promise<void>;
  onCountChange?: (count: number | null) => void;
};

function endpointLabel(provider: ManagedLlmProvider, fallback: string): string {
  if (!provider.base_url) return fallback;
  try {
    return new URL(provider.base_url).host;
  } catch {
    return provider.base_url;
  }
}

export function ModelProviderWorkspace({
  config,
  runtimeProvider,
  canManage,
  onRuntimeStatusRefresh,
  onCountChange,
}: ModelProviderWorkspaceProps) {
  const { locale, t } = useI18n();
  const client = useMemo(() => new DesktopApiClient(config), [config]);
  const [providers, setProviders] = useState<ManagedLlmProvider[]>([]);
  const [providerTypes, setProviderTypes] = useState<LlmProviderTypeDescriptor[]>([]);
  const [routingPolicy, setRoutingPolicy] = useState<LlmProviderRoutingPolicy | null>(null);
  const [routingLoading, setRoutingLoading] = useState(config.mode === 'local');
  const [routingError, setRoutingError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<ProviderTab>('overview');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<ProviderListFilter>('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<number | null>(null);
  const mountedRef = useRef(true);
  const clientRef = useRef(client);
  clientRef.current = client;
  const scopeKey = `${config.mode}\u0000${config.apiBaseUrl}\u0000${config.tenantId}`;
  const scopeKeyRef = useRef(scopeKey);
  scopeKeyRef.current = scopeKey;

  const showToast = useCallback((message: string) => {
    if (toastTimer.current != null) window.clearTimeout(toastTimer.current);
    setToast(message);
    toastTimer.current = window.setTimeout(() => setToast(null), 2800);
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (toastTimer.current != null) window.clearTimeout(toastTimer.current);
    };
  }, []);

  const loadProviders = useCallback(
    async (signal?: AbortSignal) => {
      const requestScope = scopeKey;
      const requestClient = client;
      setLoading(true);
      setError(null);
      setRoutingLoading(config.mode === 'local');
      setRoutingError(null);
      try {
        const policyRequest =
          config.mode === 'local'
            ? requestClient
                .getLlmProviderRoutingPolicy(signal)
                .then((policy) => ({ policy, error: null }))
                .catch((caught: unknown) => ({
                  policy: null,
                  error: caught instanceof Error ? caught.message : String(caught),
                }))
            : Promise.resolve({ policy: null, error: null });
        const [items, types, policyOutcome] = await Promise.all([
          requestClient.listLlmProviders(signal),
          requestClient.listLlmProviderTypes(signal).catch(() => []),
          policyRequest,
        ]);
        if (
          signal?.aborted ||
          !mountedRef.current ||
          clientRef.current !== requestClient ||
          scopeKeyRef.current !== requestScope
        ) {
          return;
        }
        const modelProviders = items.filter(
          (item) => !item.operation_type || item.operation_type === 'llm',
        );
        setProviders(modelProviders);
        setProviderTypes(types);
        setRoutingPolicy(policyOutcome.policy);
        setRoutingError(policyOutcome.error);
        onCountChange?.(modelProviders.length);
        setSelectedId((current) =>
          current && modelProviders.some((item) => item.id === current)
            ? current
            : (modelProviders[0]?.id ?? null),
        );
      } catch (caught) {
        if (
          signal?.aborted ||
          !mountedRef.current ||
          clientRef.current !== requestClient ||
          scopeKeyRef.current !== requestScope
        ) {
          return;
        }
        setProviders([]);
        setProviderTypes([]);
        setRoutingPolicy(null);
        setRoutingError(null);
        onCountChange?.(null);
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        if (
          !signal?.aborted &&
          mountedRef.current &&
          clientRef.current === requestClient &&
          scopeKeyRef.current === requestScope
        ) {
          setLoading(false);
          setRoutingLoading(false);
        }
      }
    },
    [client, config.mode, onCountChange, scopeKey],
  );

  useEffect(() => {
    const controller = new AbortController();
    void loadProviders(controller.signal);
    return () => controller.abort();
  }, [loadProviders]);

  const filteredProviders = useMemo(
    () => filterProviders(providers, query, filter),
    [filter, providers, query],
  );
  const provider = providers.find((item) => item.id === selectedId) ?? providers[0] ?? null;
  const providerTypeDescriptor = providerTypes.find(
    (descriptor) => descriptor.providerType === provider?.provider_type,
  );

  const replaceProvider = useCallback((nextProvider: ManagedLlmProvider) => {
    setProviders((current) =>
      current.map((item) => (item.id === nextProvider.id ? nextProvider : item)),
    );
  }, []);

  const refreshRuntimeProjection = useCallback(
    async (requestScope: string, requestClient: DesktopApiClient): Promise<void> => {
      if (
        !mountedRef.current ||
        clientRef.current !== requestClient ||
        scopeKeyRef.current !== requestScope
      ) {
        return;
      }
      try {
        await onRuntimeStatusRefresh();
      } catch {
        if (
          mountedRef.current &&
          clientRef.current === requestClient &&
          scopeKeyRef.current === requestScope
        ) {
          showToast(t('providers.runtimeRefreshFailed'));
        }
      }
    },
    [onRuntimeStatusRefresh, showToast, t],
  );

  const updateProvider = useCallback(
    async (
      currentProvider: ManagedLlmProvider,
      mutation: LlmProviderMutationInput,
    ): Promise<ManagedLlmProvider> => {
      const requestScope = scopeKey;
      const requestClient = client;
      const updated = await requestClient.updateLlmProvider(currentProvider.id, mutation);
      if (
        !mountedRef.current ||
        clientRef.current !== requestClient ||
        scopeKeyRef.current !== requestScope
      ) {
        throw new Error(t('providers.contextChanged'));
      }
      replaceProvider(updated);
      showToast(t('providers.providerSaved', { provider: updated.name }));
      return updated;
    },
    [client, replaceProvider, scopeKey, showToast, t],
  );

  const saveProvider = useCallback(
    async (
      currentProvider: ManagedLlmProvider,
      mutation: LlmProviderMutationInput,
    ): Promise<ManagedLlmProvider> => {
      const requestScope = scopeKey;
      const requestClient = client;
      const updated = await updateProvider(currentProvider, mutation);
      await refreshRuntimeProjection(requestScope, requestClient);
      return updated;
    },
    [client, refreshRuntimeProjection, scopeKey, updateProvider],
  );

  const saveRoutingPolicy = useCallback(
    async (
      mutation: LlmProviderRoutingPolicyMutationInput,
    ): Promise<LlmProviderRoutingPolicy> => {
      const requestScope = scopeKey;
      const requestClient = client;
      let updated: LlmProviderRoutingPolicy;
      try {
        updated = await requestClient.updateLlmProviderRoutingPolicy(mutation);
      } catch (caught) {
        if (!(caught instanceof DesktopApiError) || caught.status !== 409) throw caught;
        const [latestItems, latestPolicy] = await Promise.all([
          requestClient.listLlmProviders(),
          requestClient.getLlmProviderRoutingPolicy(),
        ]);
        if (
          !mountedRef.current ||
          clientRef.current !== requestClient ||
          scopeKeyRef.current !== requestScope
        ) {
          throw new Error(t('providers.contextChanged'));
        }
        const modelProviders = latestItems.filter(
          (item) => !item.operation_type || item.operation_type === 'llm',
        );
        setProviders(modelProviders);
        setSelectedId((current) =>
          current && modelProviders.some((item) => item.id === current)
            ? current
            : (modelProviders[0]?.id ?? null),
        );
        onCountChange?.(modelProviders.length);
        setRoutingPolicy(latestPolicy);
        setRoutingError(null);
        await refreshRuntimeProjection(requestScope, requestClient);
        showToast(t('providers.routingConflictReloaded'));
        return latestPolicy;
      }
      if (
        !mountedRef.current ||
        clientRef.current !== requestClient ||
        scopeKeyRef.current !== requestScope
      ) {
        throw new Error(t('providers.contextChanged'));
      }
      setRoutingPolicy(updated);
      setRoutingError(null);
      showToast(t('providers.routingSaved'));
      await refreshRuntimeProjection(requestScope, requestClient);
      return updated;
    },
    [client, onCountChange, refreshRuntimeProjection, scopeKey, showToast, t],
  );

  const validateProvider = useCallback(
    async (
      providerId: string,
      expectedRevision: number,
    ): Promise<LlmProviderValidationOutcome> => {
      const requestScope = scopeKey;
      const requestClient = client;
      const outcome = await requestClient.checkLlmProvider(providerId, expectedRevision);
      if (
        !mountedRef.current ||
        clientRef.current !== requestClient ||
        scopeKeyRef.current !== requestScope
      ) {
        throw new Error(t('providers.contextChanged'));
      }
      if (outcome.provider) {
        replaceProvider(outcome.provider);
      } else {
        setProviders((current) =>
          current.map((item) =>
            item.id === providerId
              ? {
                  ...item,
                  health_status: outcome.status,
                  health_last_check: outcome.lastChecked ?? item.health_last_check,
                  response_time_ms: outcome.responseTimeMs ?? item.response_time_ms,
                  error_message: outcome.errorMessage ?? null,
                }
              : item,
          ),
        );
      }
      return outcome;
    },
    [client, replaceProvider, scopeKey, t],
  );

  const loadProviderCatalog = useCallback(
    (targetProvider: ManagedLlmProvider): Promise<LlmProviderModelCatalog> =>
      config.mode === 'local'
        ? client.discoverLlmProviderModels(targetProvider.id, targetProvider.revision ?? 0)
        : client.listLlmProviderModels(targetProvider.provider_type),
    [client, config.mode],
  );

  const createProvider = useCallback(
    async (input: LlmProviderCreateInput) => {
      const requestScope = scopeKey;
      const requestClient = client;
      const created = await requestClient.createLlmProvider(input);
      if (
        !mountedRef.current ||
        clientRef.current !== requestClient ||
        scopeKeyRef.current !== requestScope
      ) {
        throw new Error(t('providers.contextChanged'));
      }
      let validationState: 'connected' | 'configured' | 'attention' = 'attention';
      let checkedProvider = created;
      try {
        const outcome = await requestClient.checkLlmProvider(created.id, created.revision ?? 0);
        validationState =
          outcome.probed && outcome.status === 'healthy'
            ? 'connected'
            : !outcome.probed && outcome.status === 'configuration_valid'
              ? 'configured'
              : 'attention';
        checkedProvider = {
          ...created,
          health_status: outcome.status,
          health_last_check: outcome.lastChecked ?? null,
          response_time_ms: outcome.responseTimeMs ?? null,
          error_message: outcome.errorMessage ?? null,
        };
      } catch {
        checkedProvider = { ...created, health_status: null };
      }
      if (
        !mountedRef.current ||
        clientRef.current !== requestClient ||
        scopeKeyRef.current !== requestScope
      ) {
        throw new Error(t('providers.contextChanged'));
      }
      setProviders((current) => [...current, checkedProvider]);
      onCountChange?.(providers.length + 1);
      setSelectedId(created.id);
      setTab('overview');
      setAdding(false);
      showToast(
        t(
          validationState === 'connected'
            ? 'providers.providerConnected'
            : validationState === 'configured'
              ? 'providers.providerConfigured'
              : 'providers.providerAddedNeedsAttention',
          { provider: created.name },
        ),
      );
      await refreshRuntimeProjection(requestScope, requestClient);
      return checkedProvider;
    },
    [client, onCountChange, providers.length, refreshRuntimeProjection, scopeKey, showToast, t],
  );

  const selectProvider = (providerId: string) => {
    setSelectedId(providerId);
    setTab('overview');
  };

  const copyProviderId = async () => {
    if (!provider) return;
    try {
      await navigator.clipboard.writeText(provider.id);
      showToast(t('providers.providerIdCopied'));
    } catch {
      showToast(t('providers.copyUnavailable'));
    }
  };

  const providerRuntimeSelected = Boolean(
    provider &&
      (config.mode === 'local'
        ? runtimeProvider?.provider_id === provider.id
        : provider.runtime_selected === true),
  );

  return (
    <main className="model-provider-workspace">
      <section className="provider-catalog">
        <header>
          <div>
            <span>{t('providers.inferenceEyebrow')}</span>
            <h2>{t('providers.title')}</h2>
            <p>{t('providers.subtitle')}</p>
          </div>
          <button
            className="provider-icon-button"
            type="button"
            disabled={!canManage}
            aria-label={t('providers.addProvider')}
            onClick={() => setAdding(true)}
          >
            <PlusIcon />
          </button>
        </header>
        <label className="provider-search">
          <MagnifyingGlassIcon />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('providers.searchProviders')}
          />
        </label>
        <div className="provider-filters" role="group" aria-label={t('providers.filterLabel')}>
          {(['all', 'connected', 'attention'] as const).map((value) => (
            <button
              className={filter === value ? 'active' : ''}
              type="button"
              key={value}
              onClick={() => setFilter(value)}
            >
              {t(`providers.filter.${value}`)}
            </button>
          ))}
        </div>
        <div className="provider-count">
          <span>{t('providers.providerCount', { count: filteredProviders.length })}</span>
          <button type="button" disabled={!canManage} onClick={() => setAdding(true)}>
            <PlusIcon /> {t('providers.add')}
          </button>
        </div>
        <div className="provider-list">
          {filteredProviders.map((item) => (
            <button
              className={provider?.id === item.id ? 'selected' : ''}
              type="button"
              key={item.id}
              onClick={() => selectProvider(item.id)}
            >
              <span className="provider-list-icon">
                <CubeIcon />
              </span>
              <span className="provider-list-copy">
                <b>{item.name || item.provider_type}</b>
                <small>
                  {providerTypeDisplayName(item.provider_type)} ·{' '}
                  {t('providers.modelCount', {
                    count: providerModelsFromProvider(item).length,
                  })}
                </small>
                <ProviderStatusBadge provider={item} />
              </span>
              <ArrowRightIcon />
            </button>
          ))}
          {!loading && !error && filteredProviders.length === 0 ? (
            <div className="provider-workspace-state">
              <CubeIcon />
              <span>{t('providers.noMatchingProviders')}</span>
            </div>
          ) : null}
        </div>
      </section>

      <section className="provider-detail">
        <header className="provider-detail-topbar">
          <div className="breadcrumb">
            <span>{t('settings.title')}</span>
            <span>/</span>
            <span>{t('settings.models')}</span>
            {provider ? (
              <>
                <span>/</span>
                <b>{provider.name}</b>
              </>
            ) : null}
          </div>
          <div>
            <span className="detail-scope">
              <LockClosedIcon />
              {config.mode === 'local'
                ? t('providers.localScope')
                : t('providers.globalProviderScope')}
            </span>
            {provider ? (
              <button
                className="provider-icon-button"
                type="button"
                aria-label={t('providers.copyProviderId')}
                onClick={() => void copyProviderId()}
              >
                <CopyIcon />
              </button>
            ) : null}
            <button
              className="provider-add-action"
              type="button"
              disabled={!canManage}
              onClick={() => setAdding(true)}
            >
              <PlusIcon /> {t('providers.addProvider')}
            </button>
          </div>
        </header>

        {loading && !provider ? (
          <div className="provider-workspace-state" role="status">
            <ReloadIcon className="spin" />
            <span>{t('providers.loadingProviders')}</span>
          </div>
        ) : null}
        {error ? (
          <div className="provider-workspace-state error" role="alert">
            <ExclamationTriangleIcon />
            <strong>{t('providers.loadFailed')}</strong>
            <span>{error}</span>
            <button type="button" onClick={() => void loadProviders()}>
              {t('providers.retry')}
            </button>
          </div>
        ) : null}
        {!loading && !error && !provider ? (
          <div className="provider-workspace-state">
            <CubeIcon />
            <strong>{t('providers.noProviders')}</strong>
            <span>{t('providers.noProvidersDescription')}</span>
            {canManage ? (
              <button type="button" onClick={() => setAdding(true)}>
                <PlusIcon /> {t('providers.addProvider')}
              </button>
            ) : null}
          </div>
        ) : null}

        {provider ? (
          <div className="provider-detail-scroll">
            <section className="provider-identity">
              <div className="provider-identity-icon">
                <CubeIcon />
              </div>
              <div>
                <span>
                  {t('providers.modelProviderEyebrow')} ·{' '}
                  {providerTypeDisplayName(provider.provider_type).toUpperCase()}
                </span>
                <h1>{provider.name || provider.provider_type}</h1>
                <p>{t('providers.identityDescription')}</p>
                <div>
                  <ProviderStatusBadge provider={provider} />
                  <span className="provider-auth-badge">
                    <LockClosedIcon />
                    {t(
                      provider.auth_method === 'none'
                        ? 'providers.auth.none'
                        : 'providers.auth.api_key',
                    )}
                  </span>
                </div>
              </div>
              <section>
                <small>{t('providers.endpointEyebrow')}</small>
                <b>{endpointLabel(provider, t('providers.providerDefaultEndpoint'))}</b>
                <span>
                  {provider.health_last_check
                    ? t('providers.lastChecked', {
                        time: new Date(provider.health_last_check).toLocaleString(locale),
                      })
                    : t('providers.neverChecked')}
                </span>
              </section>
            </section>
            <nav
              className="provider-tabs"
              role="tablist"
              aria-label={t('providers.providerSettings', {
                provider: provider.name,
              })}
            >
              {(['overview', 'connection', 'models', 'routing', 'usage'] as const).map((value) => (
                  <button
                    className={tab === value ? 'active' : ''}
                    type="button"
                  role="tab"
                  aria-selected={tab === value}
                    key={value}
                    onClick={() => setTab(value)}
                  >
                    {t(`providers.tab.${value}`)}
                  </button>
              ))}
            </nav>
            <div className="provider-tab-content">
              {!canManage ? (
                <div className="provider-readonly-banner">
                  <LockClosedIcon />
                  <span>{t('providers.readOnlyDescription')}</span>
                </div>
              ) : null}
              {tab === 'overview' ? (
                <ProviderOverviewPanel
                  provider={provider}
                  providers={providers}
                  policy={routingPolicy}
                  mode={config.mode}
                  runtimeSelected={providerRuntimeSelected}
                  onTabChange={setTab}
                />
              ) : null}
              {tab === 'connection' ? (
                <ProviderConnectionPanel
                  provider={provider}
                  providerTypeDescriptor={providerTypeDescriptor}
                  mode={config.mode}
                  canManage={canManage}
                  onSave={saveProvider}
                  onValidate={validateProvider}
                  onValidateDraft={client.testLlmProviderDraft.bind(client)}
                />
              ) : null}
              {tab === 'models' ? (
                <ProviderModelsPanel
                  key={`${scopeKey}:${provider.id}`}
                  provider={provider}
                  canManage={canManage}
                  onLoadCatalog={loadProviderCatalog}
                  onSave={saveProvider}
                />
              ) : null}
              {tab === 'routing' ? (
                <ProviderRoutingPanel
                  provider={provider}
                  providers={providers}
                  policy={routingPolicy}
                  loading={routingLoading}
                  loadError={routingError}
                  mode={config.mode}
                  canManage={canManage}
                  onSave={saveRoutingPolicy}
                />
              ) : null}
              {tab === 'usage' ? (
                <ProviderUsagePanel
                  provider={provider}
                  canReadUsage={canManage}
                  onLoadUsage={client.getLlmProviderUsage.bind(client)}
                />
              ) : null}
            </div>
          </div>
        ) : null}
      </section>

      {adding ? (
        <AddProviderDialog
          onClose={() => setAdding(false)}
          onLoadTypes={client.listLlmProviderTypes.bind(client)}
          onValidateDraft={client.testLlmProviderDraft.bind(client)}
          onCreate={createProvider}
        />
      ) : null}
      {toast ? (
        <div className="provider-toast" role="status" aria-live="polite">
          {toast}
        </div>
      ) : null}
    </main>
  );
}
