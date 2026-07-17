import { useEffect, useMemo, useState } from 'react';
import {
  ActivityLogIcon,
  ArrowRightIcon,
  CheckCircledIcon,
  CubeIcon,
  ExclamationTriangleIcon,
  InfoCircledIcon,
  Link2Icon,
  MixerHorizontalIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  LlmProviderMutationInput,
  LlmProviderUsage,
  ManagedLlmProvider,
  RuntimeMode,
} from '../../types';
import { providerDraftFromProvider, providerMutationFromDraft } from './providerManagementModel';
import { ProviderStatusBadge } from './ProviderStatusBadge';

export type ProviderTab = 'overview' | 'connection' | 'models' | 'routing' | 'usage';

type ProviderOverviewPanelProps = {
  provider: ManagedLlmProvider;
  mode: RuntimeMode;
  runtimeSelected: boolean;
  onTabChange: (tab: ProviderTab) => void;
};

export function ProviderOverviewPanel({
  provider,
  mode,
  runtimeSelected,
  onTabChange,
}: ProviderOverviewPanelProps) {
  const { locale, t } = useI18n();
  const enabledModels = provider.allowed_models ?? [];
  const checkedAt = provider.health_last_check
    ? new Date(provider.health_last_check).toLocaleString(locale)
    : t('providers.neverChecked');
  return (
    <div className="provider-panel-grid">
      <section className="provider-health-card">
        <header>
          <div>
            <span>{t('providers.connectionEyebrow')}</span>
            <h3>{t('providers.providerHealth')}</h3>
          </div>
          <ProviderStatusBadge provider={provider} />
        </header>
        <div className="provider-health-row">
          <div className="provider-health-icon">
            <Link2Icon />
          </div>
          <div>
            <b>{provider.base_url || t('providers.providerDefaultEndpoint')}</b>
            <span>
              {t(
                provider.auth_method === 'none' ? 'providers.auth.none' : 'providers.auth.api_key',
              )}
              {' · '}
              {provider.auth_method === 'none' ||
              provider.credential_configured ||
              provider.api_key_masked
                ? t('providers.credentialConfigured')
                : t('providers.credentialMissing')}
            </span>
          </div>
          <button type="button" onClick={() => onTabChange('connection')}>
            {t('providers.manage')}
          </button>
        </div>
        <div className="provider-health-meta">
          <span>
            <CheckCircledIcon />
            {t('providers.lastChecked', { time: checkedAt })}
          </span>
          {provider.response_time_ms != null ? (
            <span>
              <ActivityLogIcon />
              {t('providers.responseTime', {
                count: provider.response_time_ms,
              })}
            </span>
          ) : null}
        </div>
      </section>

      <section className="provider-model-summary">
        <header>
          <div>
            <span>{t('providers.modelCatalogEyebrow')}</span>
            <h3>{t('providers.enabledModels')}</h3>
          </div>
          <button type="button" onClick={() => onTabChange('models')}>
            {t('providers.manageModels')} <ArrowRightIcon />
          </button>
        </header>
        {enabledModels.length > 0 ? (
          enabledModels.slice(0, 4).map((model) => (
            <article key={model}>
              <CubeIcon />
              <div>
                <b>{model}</b>
                <span>{t('providers.exactModelId')}</span>
              </div>
              <em>
                {t(
                  model === provider.llm_model ? 'providers.defaultRole' : 'providers.enabledRole',
                )}
              </em>
            </article>
          ))
        ) : (
          <div className="provider-empty-state">
            <ExclamationTriangleIcon />
            <b>{t('providers.noModelsEnabled')}</b>
            <span>{t('providers.noModelsEnabledDescription')}</span>
            <button type="button" onClick={() => onTabChange('models')}>
              {t('providers.chooseModels')}
            </button>
          </div>
        )}
      </section>

      <section className="provider-routing-card">
        <header>
          <div>
            <span>{t('providers.routingEyebrow')}</span>
            <h3>{t('providers.currentModelRoles')}</h3>
          </div>
          <MixerHorizontalIcon />
        </header>
        <div className="provider-routing-list">
          <div>
            <span>{t('providers.defaultRole')}</span>
            <b>{provider.llm_model || t('providers.notConfigured')}</b>
            <em>
              {mode === 'local' && runtimeSelected
                ? t('providers.localRuntimeSelected')
                : t('providers.providerPrimaryModel')}
            </em>
          </div>
          <div>
            <span>{t('providers.fastRole')}</span>
            <b>{provider.llm_small_model || t('providers.notConfigured')}</b>
            <em>{t('providers.readOnlyFromServer')}</em>
          </div>
          <div>
            <span>{t('providers.fallbackRole')}</span>
            <b>{provider.secondary_models?.[0] || t('providers.notConfigured')}</b>
            <em>{t('providers.readOnlyFromServer')}</em>
          </div>
        </div>
        <button type="button" onClick={() => onTabChange('routing')}>
          {t('providers.inspectRouting')} <ArrowRightIcon />
        </button>
      </section>
    </div>
  );
}

type ProviderRoutingPanelProps = {
  provider: ManagedLlmProvider;
  mode: RuntimeMode;
  runtimeSelected: boolean;
  canManage: boolean;
  onSave: (
    provider: ManagedLlmProvider,
    mutation: LlmProviderMutationInput,
  ) => Promise<ManagedLlmProvider>;
  onRuntimeSelected: (provider: ManagedLlmProvider) => Promise<void>;
};

export function ProviderRoutingPanel({
  provider,
  mode,
  runtimeSelected,
  canManage,
  onSave,
  onRuntimeSelected,
}: ProviderRoutingPanelProps) {
  const { t } = useI18n();
  const availableModels = useMemo(
    () =>
      [
        ...new Set([provider.llm_model, ...(provider.allowed_models ?? [])].filter(Boolean)),
      ] as string[],
    [provider.allowed_models, provider.llm_model],
  );
  const initialDefaultModel = provider.llm_model ?? availableModels[0] ?? '';
  const [routingDraft, setRoutingDraft] = useState({
    providerId: provider.id,
    defaultModel: initialDefaultModel,
  });
  const [savingProviderId, setSavingProviderId] = useState<string | null>(null);
  const [providerError, setProviderError] = useState<{
    providerId: string;
    message: string;
  } | null>(null);
  const defaultModel =
    routingDraft.providerId === provider.id ? routingDraft.defaultModel : initialDefaultModel;
  const saving = savingProviderId === provider.id;
  const error = providerError?.providerId === provider.id ? providerError.message : null;

  const localRoutingAvailable = mode === 'local';
  const saveDefaultRoute = async () => {
    setSavingProviderId(provider.id);
    setProviderError(null);
    try {
      const draft = providerDraftFromProvider(provider);
      draft.primaryModel = defaultModel;
      draft.active = true;
      const enabled = new Set(provider.allowed_models ?? []);
      enabled.add(defaultModel);
      draft.allowedModels = [...enabled].join('\n');
      const updated = await onSave(provider, providerMutationFromDraft(draft));
      await onRuntimeSelected(updated);
    } catch (caught) {
      setProviderError({
        providerId: provider.id,
        message: caught instanceof Error ? caught.message : String(caught),
      });
    } finally {
      setSavingProviderId((current) => (current === provider.id ? null : current));
    }
  };

  return (
    <section className="provider-routing-form">
      <header>
        <div>
          <span>{t('providers.routingEyebrow')}</span>
          <h3>{t('providers.routingTitle')}</h3>
          <p>{t('providers.routingDescription')}</p>
        </div>
        {localRoutingAvailable && canManage ? (
          <button
            className="primary"
            type="button"
            disabled={
              saving || !defaultModel || (runtimeSelected && defaultModel === provider.llm_model)
            }
            onClick={() => void saveDefaultRoute()}
          >
            {saving ? <ReloadIcon className="spin" /> : <CheckCircledIcon />}
            {t(saving ? 'providers.savingRouting' : 'providers.saveRouting')}
          </button>
        ) : null}
      </header>

      {!localRoutingAvailable ? (
        <div className="provider-capability-note">
          <InfoCircledIcon />
          <span>
            <b>{t('providers.routingMutationUnavailable')}</b>
            <small>{t('providers.routingMutationUnavailableDescription')}</small>
          </span>
        </div>
      ) : null}

      <div className="provider-role-grid">
        <label>
          <span>
            <b>{t('providers.defaultModel')}</b>
            <small>{t('providers.defaultModelDescription')}</small>
          </span>
          <select
            value={defaultModel}
            disabled={!localRoutingAvailable || !canManage}
            onChange={(event) =>
              setRoutingDraft({ providerId: provider.id, defaultModel: event.target.value })
            }
          >
            {availableModels.map((model) => (
              <option value={model} key={model}>
                {provider.name} / {model}
              </option>
            ))}
          </select>
        </label>
        {[
          ['fast', provider.llm_small_model],
          ['coding', null],
          ['vision', null],
        ].map(([role, model]) => (
          <label key={role}>
            <span>
              <b>{t(`providers.${role}Model`)}</b>
              <small>{t('providers.roleContractUnavailable')}</small>
            </span>
            <select value={model || ''} disabled>
              <option value="">{model || t('providers.notExposedByServer')}</option>
            </select>
          </label>
        ))}
      </div>

      <section className="provider-fallback-editor">
        <header>
          <div>
            <span>{t('providers.failoverEyebrow')}</span>
            <h3>{t('providers.fallbackOrder')}</h3>
          </div>
          <small>{t('providers.fallbackReadOnlyDescription')}</small>
        </header>
        {(provider.secondary_models ?? []).length > 0 ? (
          provider.secondary_models?.map((model, index) => (
            <div key={`${model}-${index}`}>
              <span>{index + 1}</span>
              <select value={model} disabled>
                <option value={model}>
                  {provider.name} / {model}
                </option>
              </select>
              <em>{t('providers.readOnly')}</em>
            </div>
          ))
        ) : (
          <div className="provider-fallback-empty">
            <InfoCircledIcon />
            <span>{t('providers.noFallbacks')}</span>
          </div>
        )}
      </section>

      {error ? (
        <div className="provider-inline-error" role="alert">
          <ExclamationTriangleIcon />
          <span>{error}</span>
        </div>
      ) : null}
    </section>
  );
}

type ProviderUsagePanelProps = {
  provider: ManagedLlmProvider;
  canReadUsage: boolean;
  onLoadUsage: (providerId: string, signal?: AbortSignal) => Promise<LlmProviderUsage>;
};

export function ProviderUsagePanel({
  provider,
  canReadUsage,
  onLoadUsage,
}: ProviderUsagePanelProps) {
  const { locale, t } = useI18n();
  const [usage, setUsage] = useState<LlmProviderUsage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setUsage(null);
    setError(null);
    if (!canReadUsage) return () => controller.abort();
    setLoading(true);
    void onLoadUsage(provider.id, controller.signal)
      .then((nextUsage) => {
        if (!controller.signal.aborted) setUsage(nextUsage);
      })
      .catch((caught) => {
        if (!controller.signal.aborted) {
          setError(caught instanceof Error ? caught.message : String(caught));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [canReadUsage, onLoadUsage, provider.id]);

  const totals = useMemo(() => {
    const statistics = usage?.statistics ?? [];
    const requests = statistics.reduce((sum, item) => sum + item.total_requests, 0);
    const tokens = statistics.reduce((sum, item) => sum + item.total_tokens, 0);
    const cost = statistics.reduce((sum, item) => sum + (item.total_cost_usd ?? 0), 0);
    const latencyNumerator = statistics.reduce(
      (sum, item) => sum + (item.avg_response_time_ms ?? 0) * item.total_requests,
      0,
    );
    return {
      requests,
      tokens,
      cost,
      latency: requests > 0 ? latencyNumerator / requests : null,
    };
  }, [usage]);

  if (!canReadUsage || usage?.availability === 'unavailable') {
    return (
      <section className="provider-activity-card provider-unavailable-card">
        <InfoCircledIcon />
        <div>
          <span>{t('providers.usageEyebrow')}</span>
          <h3>{t('providers.usageUnavailable')}</h3>
          <p>{t('providers.usageUnavailableDescription')}</p>
        </div>
      </section>
    );
  }

  if (loading) {
    return (
      <div className="provider-loading-state" role="status">
        <ReloadIcon className="spin" />
        <span>{t('providers.loadingUsage')}</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="provider-inline-error" role="alert">
        <ExclamationTriangleIcon />
        <span>{error}</span>
      </div>
    );
  }

  const number = new Intl.NumberFormat(locale);
  const currency = new Intl.NumberFormat(locale, {
    style: 'currency',
    currency: 'USD',
  });
  return (
    <div className="provider-panel-grid">
      <section className="provider-metric-grid">
        {[
          [t('providers.totalRequests'), number.format(totals.requests)],
          [t('providers.totalTokens'), number.format(totals.tokens)],
          [
            t('providers.averageLatency'),
            totals.latency == null
              ? t('providers.notAvailable')
              : t('providers.milliseconds', {
                  count: Math.round(totals.latency),
                }),
          ],
          [t('providers.totalCost'), currency.format(totals.cost)],
        ].map(([label, value]) => (
          <div className="provider-fact" key={label}>
            <span>{label}</span>
            <b>{value}</b>
          </div>
        ))}
      </section>
      <section className="provider-activity-card">
        <header>
          <div>
            <span>{t('providers.usageEyebrow')}</span>
            <h3>{t('providers.usageByOperation')}</h3>
          </div>
          <ActivityLogIcon />
        </header>
        {(usage?.statistics ?? []).length > 0 ? (
          usage?.statistics.map((statistic) => (
            <div key={`${statistic.operation_type}-${statistic.tenant_id}`}>
              <span>
                <CheckCircledIcon />
              </span>
              <div>
                <b>{statistic.operation_type || t('providers.unknownOperation')}</b>
                <small>
                  {t('providers.operationUsage', {
                    requests: number.format(statistic.total_requests),
                    tokens: number.format(statistic.total_tokens),
                  })}
                </small>
              </div>
            </div>
          ))
        ) : (
          <div className="provider-usage-empty">
            <InfoCircledIcon />
            <span>{t('providers.noUsage')}</span>
          </div>
        )}
      </section>
    </div>
  );
}
