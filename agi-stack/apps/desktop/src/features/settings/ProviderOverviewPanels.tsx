import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityLogIcon,
  ArrowRightIcon,
  CheckCircledIcon,
  CubeIcon,
  ExclamationTriangleIcon,
  InfoCircledIcon,
  Link2Icon,
  MixerHorizontalIcon,
  PlusIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  LlmProviderRoutingPolicy,
  LlmProviderRoutingPolicyMutationInput,
  LlmProviderUsage,
  LlmRouteTarget,
  LlmRoutingRole,
  ManagedLlmProvider,
  RuntimeMode,
} from '../../types';
import {
  localRuntimeRoutingModelIds,
  providerEnabledModelIds,
  providerRoutingOverview,
  routingFallbackCanAdd,
} from './providerManagementModel';
import { ProviderStatusBadge } from './ProviderStatusBadge';

export type ProviderTab = 'overview' | 'connection' | 'models' | 'routing' | 'usage';

type ProviderOverviewPanelProps = {
  provider: ManagedLlmProvider;
  providers: ManagedLlmProvider[];
  policy: LlmProviderRoutingPolicy | null;
  mode: RuntimeMode;
  onTabChange: (tab: ProviderTab) => void;
};

export function ProviderOverviewPanel({
  provider,
  providers,
  policy,
  mode,
  onTabChange,
}: ProviderOverviewPanelProps) {
  const { locale, t } = useI18n();
  const enabledModels = [
    ...new Set([provider.llm_model, ...(provider.allowed_models ?? [])].filter(Boolean)),
  ] as string[];
  const providerNames = useMemo(
    () => new Map(providers.map((item) => [item.id, item.name || item.provider_type])),
    [providers],
  );
  const routeLabel = (target: LlmRouteTarget | null | undefined): string | null =>
    target
      ? `${providerNames.get(target.provider_id) ?? target.provider_id} / ${target.model_id}`
      : null;
  const overviewRouting = providerRoutingOverview(provider, policy);
  const defaultRoute = routeLabel(overviewRouting.roles.default);
  const fastRoute = routeLabel(overviewRouting.roles.fast);
  const fallbackRoute = routeLabel(overviewRouting.fallbacks[0]);
  const policyBacked = mode === 'local' && policy !== null;
  const authMethod = provider.auth_method ?? 'api_key';
  const credentialReady =
    provider.auth_method === 'none' || provider.credential_configured === true;
  const credentialStatusKey =
    authMethod === 'none'
      ? 'providers.noAuthentication'
      : authMethod === 'environment'
        ? provider.credential_configured === true
          ? 'providers.environmentSecretAvailable'
          : provider.credential_configured === false
            ? 'providers.environmentSecretUnavailable'
            : 'providers.environmentSecretUnknown'
        : credentialReady
          ? 'providers.credentialConfigured'
          : provider.credential_configured === false
            ? 'providers.credentialMissing'
            : 'providers.credentialUnknown';
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
              {t(`providers.auth.${authMethod}`)}
              {' · '}
              {t(credentialStatusKey)}
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
            <b>{defaultRoute || t('providers.notConfigured')}</b>
            <em>
              {policyBacked
                ? t('providers.workspaceRoutingPolicy')
                : t('providers.providerPrimaryModel')}
            </em>
          </div>
          <div>
            <span>{t('providers.fastRole')}</span>
            <b>{fastRoute || t('providers.notConfigured')}</b>
            <em>
              {t(
                policyBacked
                  ? 'providers.workspaceRoutingPolicy'
                  : 'providers.readOnlyFromServer',
              )}
            </em>
          </div>
          <div>
            <span>{t('providers.fallbackRole')}</span>
            <b>{fallbackRoute || t('providers.notConfigured')}</b>
            <em>
              {t(
                policyBacked
                  ? 'providers.workspaceRoutingPolicy'
                  : 'providers.readOnlyFromServer',
              )}
            </em>
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
  providers: ManagedLlmProvider[];
  policy: LlmProviderRoutingPolicy | null;
  loading: boolean;
  loadError: string | null;
  mode: RuntimeMode;
  canManage: boolean;
  onSave: (mutation: RoutingPolicyDraftMutation) => Promise<LlmProviderRoutingPolicy>;
};

const ROUTING_ROLES: LlmRoutingRole[] = ['default', 'fast', 'coding', 'vision'];
const MAX_ROUTING_FALLBACKS = 8;

type RoutingPolicyDraftMutation = Omit<
  LlmProviderRoutingPolicyMutationInput,
  'projectId' | 'workspaceId'
>;

type RoutingDraft = {
  policyKey: string;
  roles: LlmProviderRoutingPolicy['roles'];
  fallbacks: LlmRouteTarget[];
};

type RoutingModelOption = {
  key: string;
  label: string;
  target: LlmRouteTarget;
  available: boolean;
};

function routeTargetKey(target: LlmRouteTarget): string {
  return JSON.stringify([target.provider_id, target.model_id]);
}

function sameRouteTarget(left: LlmRouteTarget | null, right: LlmRouteTarget | null): boolean {
  return (
    left === right ||
    (left?.provider_id === right?.provider_id && left?.model_id === right?.model_id)
  );
}

function routingDraftFromPolicy(
  policyKey: string,
  policy: LlmProviderRoutingPolicy,
): RoutingDraft {
  return {
    policyKey,
    roles: { ...policy.roles },
    fallbacks: [...policy.fallbacks],
  };
}

function routingDraftChanged(
  policy: LlmProviderRoutingPolicy,
  draft: RoutingDraft,
): boolean {
  if (ROUTING_ROLES.some((role) => !sameRouteTarget(policy.roles[role], draft.roles[role]))) {
    return true;
  }
  return (
    policy.fallbacks.length !== draft.fallbacks.length ||
    policy.fallbacks.some((target, index) => !sameRouteTarget(target, draft.fallbacks[index] ?? null))
  );
}

function cloudRoutingProjection(provider: ManagedLlmProvider): LlmProviderRoutingPolicy {
  const route = (modelId: string | null | undefined): LlmRouteTarget | null =>
    modelId ? { provider_id: provider.id, model_id: modelId } : null;
  return {
    tenant_id: 'cloud-read-only',
    project_id: 'cloud-read-only',
    workspace_id: 'cloud-read-only',
    revision: provider.revision ?? 0,
    roles: {
      default: route(provider.llm_model),
      fast: route(provider.llm_small_model),
      coding: null,
      vision: null,
    },
    fallbacks: (provider.secondary_models ?? []).flatMap((modelId) => {
      const target = route(modelId);
      return target ? [target] : [];
    }),
    updated_at: provider.updated_at ?? '',
  };
}

export function ProviderRoutingPanel({
  provider,
  providers,
  policy,
  loading,
  loadError,
  mode,
  canManage,
  onSave,
}: ProviderRoutingPanelProps) {
  const { t } = useI18n();
  const effectivePolicy = useMemo(
    () => policy ?? (mode === 'cloud' ? cloudRoutingProjection(provider) : null),
    [mode, policy, provider],
  );
  const policyKey = effectivePolicy
    ? [
        mode,
        effectivePolicy.tenant_id,
        effectivePolicy.project_id,
        effectivePolicy.workspace_id,
        String(effectivePolicy.revision),
        JSON.stringify(effectivePolicy.roles),
        JSON.stringify(effectivePolicy.fallbacks),
      ].join('\u0000')
    : `${mode}\u0000missing`;
  const modelOptions = useMemo(() => {
    const options = new Map<string, RoutingModelOption>();
    const providerNames = new Map(providers.map((item) => [item.id, item.name || item.provider_type]));
    for (const item of providers) {
      const modelCandidates =
        mode === 'local'
          ? localRuntimeRoutingModelIds(item)
          : providerEnabledModelIds(item);
      for (const model of modelCandidates) {
        const modelId = model.trim();
        if (!modelId) continue;
        const target = { provider_id: item.id, model_id: modelId };
        const key = routeTargetKey(target);
        options.set(key, {
          key,
          label: `${item.name || item.provider_type} / ${modelId}`,
          target,
          available: true,
        });
      }
    }
    const referencedTargets = effectivePolicy
      ? [
          ...ROUTING_ROLES.flatMap((role) => {
            const target = effectivePolicy.roles[role];
            return target ? [target] : [];
          }),
          ...effectivePolicy.fallbacks,
        ]
      : [];
    for (const target of referencedTargets) {
      const key = routeTargetKey(target);
      if (options.has(key)) continue;
      const providerLabel = providerNames.get(target.provider_id) ?? target.provider_id;
      options.set(key, {
        key,
        label: `${providerLabel} / ${target.model_id} · ${t('providers.routeUnavailable')}`,
        target,
        available: false,
      });
    }
    return [...options.values()];
  }, [effectivePolicy, mode, providers, t]);
  const enabledOptions = modelOptions.filter((option) => option.available);
  const optionByKey = useMemo(
    () => new Map(modelOptions.map((option) => [option.key, option])),
    [modelOptions],
  );
  const [storedDraft, setStoredDraft] = useState<RoutingDraft | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<{
    policyKey: string;
    message: string;
  } | null>(null);
  const saveRequestRef = useRef(0);
  const storedOrPolicyDraft =
    storedDraft?.policyKey === policyKey
      ? storedDraft
      : effectivePolicy
        ? routingDraftFromPolicy(policyKey, effectivePolicy)
        : null;
  const draft = storedOrPolicyDraft;
  const saving = savingKey === policyKey;
  const error = saveError?.policyKey === policyKey ? saveError.message : null;
  const dirty = Boolean(effectivePolicy && draft && routingDraftChanged(effectivePolicy, draft));
  const editable = mode === 'local' && canManage && policy !== null && !loading && !loadError;

  useEffect(() => {
    return () => {
      saveRequestRef.current += 1;
    };
  }, [policyKey]);

  const updateRole = (role: LlmRoutingRole, optionKey: string) => {
    if (!effectivePolicy) return;
    const target = optionKey ? (optionByKey.get(optionKey)?.target ?? null) : null;
    setStoredDraft((current) => {
      const base =
        current?.policyKey === policyKey
          ? current
          : routingDraftFromPolicy(policyKey, effectivePolicy);
      return { ...base, roles: { ...base.roles, [role]: target } };
    });
  };

  const updateFallback = (index: number, optionKey: string) => {
    if (!effectivePolicy) return;
    const target = optionByKey.get(optionKey)?.target;
    if (!target) return;
    setStoredDraft((current) => {
      const base =
        current?.policyKey === policyKey
          ? current
          : routingDraftFromPolicy(policyKey, effectivePolicy);
      return {
        ...base,
        fallbacks: base.fallbacks.map((item, currentIndex) =>
          currentIndex === index ? target : item,
        ),
      };
    });
  };

  const removeFallback = (index: number) => {
    if (!effectivePolicy) return;
    setStoredDraft((current) => {
      const base =
        current?.policyKey === policyKey
          ? current
          : routingDraftFromPolicy(policyKey, effectivePolicy);
      return {
        ...base,
        fallbacks: base.fallbacks.filter((_, currentIndex) => currentIndex !== index),
      };
    });
  };

  const addFallback = () => {
    if (!effectivePolicy || !draft) return;
    if (draft.fallbacks.length >= MAX_ROUTING_FALLBACKS) return;
    const used = new Set(draft.fallbacks.map(routeTargetKey));
    const next = enabledOptions.find((option) => !used.has(option.key));
    if (!next) return;
    setStoredDraft({ ...draft, fallbacks: [...draft.fallbacks, next.target] });
  };

  const saveRouting = async () => {
    if (!editable || !policy || !draft || !draft.roles.default) return;
    const requestId = ++saveRequestRef.current;
    setSavingKey(policyKey);
    setSaveError(null);
    try {
      await onSave({
        roles: draft.roles,
        fallbacks: draft.fallbacks,
        expectedRevision: policy.revision,
      });
    } catch (caught) {
      if (saveRequestRef.current === requestId) {
        setSaveError({
          policyKey,
          message: caught instanceof Error ? caught.message : String(caught),
        });
      }
    } finally {
      if (saveRequestRef.current === requestId) {
        setSavingKey((current) => (current === policyKey ? null : current));
      }
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
        {mode === 'local' && canManage ? (
          <button
            className="primary"
            type="button"
            disabled={!editable || saving || !dirty || !draft?.roles.default}
            onClick={() => void saveRouting()}
          >
            {saving ? <ReloadIcon className="spin" /> : <CheckCircledIcon />}
            {t(saving ? 'providers.savingRouting' : 'providers.saveRouting')}
          </button>
        ) : null}
      </header>

      {mode === 'cloud' ? (
        <div className="provider-capability-note">
          <InfoCircledIcon />
          <span>
            <b>{t('providers.routingMutationUnavailable')}</b>
            <small>{t('providers.routingMutationUnavailableDescription')}</small>
          </span>
        </div>
      ) : null}

      {loading ? (
        <div className="provider-loading-state" role="status">
          <ReloadIcon className="spin" />
          <span>{t('providers.loadingRouting')}</span>
        </div>
      ) : null}
      {!loading && loadError ? (
        <div className="provider-inline-error" role="alert">
          <ExclamationTriangleIcon />
          <span>{loadError}</span>
        </div>
      ) : null}
      {!loading && !loadError && mode === 'local' && !effectivePolicy ? (
        <div className="provider-empty-state large">
          <InfoCircledIcon />
          <b>{t('providers.routingUnavailable')}</b>
          <span>{t('providers.routingUnavailableDescription')}</span>
        </div>
      ) : null}
      {!loading && !loadError && effectivePolicy && enabledOptions.length === 0 ? (
        <div className="provider-empty-state large">
          <ExclamationTriangleIcon />
          <b>{t('providers.noRoutingModels')}</b>
          <span>{t('providers.noRoutingModelsDescription')}</span>
        </div>
      ) : null}

      {!loading && !loadError && effectivePolicy && draft ? (
        <>
          <div className="provider-role-grid">
            {ROUTING_ROLES.map((role) => {
              const selectedTarget = draft.roles[role];
              return (
                <label key={role}>
                  <span>
                    <b>{t(`providers.${role}Model`)}</b>
                    <small>{t(`providers.${role}ModelDescription`)}</small>
                  </span>
                  <select
                    value={selectedTarget ? routeTargetKey(selectedTarget) : ''}
                    disabled={!editable}
                    onChange={(event) => updateRole(role, event.target.value)}
                  >
                    <option value="" disabled={role === 'default'}>
                      {t('providers.notConfigured')}
                    </option>
                    {modelOptions.map((option) => (
                      <option value={option.key} disabled={!option.available} key={option.key}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              );
            })}
          </div>

          <section className="provider-fallback-editor">
            <header>
              <div>
                <span>{t('providers.failoverEyebrow')}</span>
                <h3>{t('providers.fallbackOrder')}</h3>
              </div>
              <small>{t('providers.fallbackReadOnlyDescription')}</small>
            </header>
            {draft.fallbacks.length > 0 ? (
              draft.fallbacks.map((target, index) => {
                const currentKey = routeTargetKey(target);
                const usedElsewhere = new Set(
                  draft.fallbacks
                    .filter((_, currentIndex) => currentIndex !== index)
                    .map(routeTargetKey),
                );
                return (
                  <div key={`${currentKey}-${index}`}>
                    <span>{index + 1}</span>
                    <select
                      value={currentKey}
                      disabled={!editable}
                      onChange={(event) => updateFallback(index, event.target.value)}
                    >
                      {modelOptions.map((option) => (
                        <option
                          value={option.key}
                          disabled={!option.available || usedElsewhere.has(option.key)}
                          key={option.key}
                        >
                          {option.label}
                        </option>
                      ))}
                    </select>
                    {editable ? (
                      <button
                        type="button"
                        aria-label={t('providers.removeFallback', { count: index + 1 })}
                        onClick={() => removeFallback(index)}
                      >
                        {t('providers.remove')}
                      </button>
                    ) : (
                      <em>{t('providers.readOnly')}</em>
                    )}
                  </div>
                );
              })
            ) : (
              <div className="provider-fallback-empty">
                <InfoCircledIcon />
                <span>{t('providers.noFallbacks')}</span>
              </div>
            )}
            {editable ? (
              <button
                type="button"
                disabled={
                  !routingFallbackCanAdd(
                    draft.fallbacks,
                    enabledOptions.map((option) => option.target),
                    MAX_ROUTING_FALLBACKS,
                  )
                }
                onClick={addFallback}
              >
                <PlusIcon /> {t('providers.addFallback')}
              </button>
            ) : null}
          </section>
        </>
      ) : null}

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
  onLoadUsage: (providerId: string, signal?: AbortSignal) => Promise<LlmProviderUsage>;
};

export function ProviderUsagePanel({
  provider,
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
  }, [onLoadUsage, provider.id]);

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

  if (usage?.availability === 'unavailable') {
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
