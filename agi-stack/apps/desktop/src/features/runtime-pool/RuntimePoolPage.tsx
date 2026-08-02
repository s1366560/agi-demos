import { useMemo, useState } from 'react';

import { useI18n } from '../../i18n';
import type {
  RuntimePoolInstance,
  RuntimePoolInstanceStatus,
  RuntimePoolTier,
} from './runtimePoolClient';
import type {
  RuntimePoolController,
  RuntimePoolResourceState,
  RuntimePoolViewModel,
} from './runtimePoolController';
import './RuntimePoolPage.css';

const INSTANCE_STATUSES: readonly RuntimePoolInstanceStatus[] = [
  'created',
  'initializing',
  'initialization_failed',
  'ready',
  'executing',
  'paused',
  'unhealthy',
  'degraded',
  'terminating',
  'terminated',
];

export function RuntimePoolPage({
  model,
  controller,
  onRetry,
  autoRefresh,
  onAutoRefreshChange,
}: Readonly<{
  model: RuntimePoolViewModel;
  controller: RuntimePoolController;
  onRetry: () => void;
  autoRefresh: boolean;
  onAutoRefreshChange: (enabled: boolean) => void;
}>) {
  const { t } = useI18n();
  const [search, setSearch] = useState('');
  const [pendingTerminate, setPendingTerminate] =
    useState<RuntimePoolInstance | null>(null);
  const visibleInstances = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    return query
      ? model.instances.filter((instance) =>
          instance.instanceKey.toLocaleLowerCase().includes(query),
        )
      : model.instances;
  }, [model.instances, search]);
  const status = model.status;
  const reasonCode =
    status?.reasonCode ??
    model.statusReasonCode ??
    model.metricsReasonCode ??
    model.instancesReasonCode;
  const loading =
    model.statusState === 'loading' || model.instancesState === 'loading';

  return (
    <section className="runtime-pool-page" aria-labelledby="runtime-pool-title">
      <header className="runtime-pool-header">
        <div>
          <span>{t('runtimePool.eyebrow')}</span>
          <h1 id="runtime-pool-title">{t('runtimePool.title')}</h1>
          <p>{t('runtimePool.subtitle')}</p>
        </div>
        <div className="runtime-pool-header-actions">
          <label className="runtime-pool-auto-refresh">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(event) => onAutoRefreshChange(event.target.checked)}
            />
            {t('runtimePool.autoRefresh')}
          </label>
          <button type="button" onClick={onRetry} disabled={loading}>
            {t('runtimePool.refresh')}
          </button>
        </div>
      </header>

      <div className="runtime-pool-scope">
        <span>{t('runtimePool.scope')}</span>
        <strong>{model.scope.tenantId}</strong>
        {model.lastUpdatedAt ? (
          <small>
            {t('runtimePool.updated', {
              time: new Date(model.lastUpdatedAt).toLocaleTimeString(),
            })}
          </small>
        ) : null}
      </div>

      <ResourceNotice
        state={highestState(
          model.statusState,
          model.instancesState,
          model.metricsState,
        )}
        reasonCode={reasonCode}
        onRetry={onRetry}
      />

      <div className="runtime-pool-summary">
        <SummaryCard
          label={t('runtimePool.summary.total')}
          value={status?.totalInstances}
          state={model.statusState}
        />
        <SummaryCard
          label={t('runtimePool.summary.ready')}
          value={status?.readyInstances}
          state={model.statusState}
        />
        <SummaryCard
          label={t('runtimePool.summary.executing')}
          value={status?.executingInstances}
          state={model.statusState}
        />
        <SummaryCard
          label={t('runtimePool.summary.unhealthy')}
          value={status?.unhealthyInstances}
          state={model.statusState}
        />
      </div>

      <div className="runtime-pool-insights">
        <article>
          <h2>{t('runtimePool.tier.title')}</h2>
          <dl>
            <div>
              <dt>{t('runtimePool.tier.hot')}</dt>
              <dd>{status?.hotInstances ?? '—'}</dd>
            </div>
            <div>
              <dt>{t('runtimePool.tier.warm')}</dt>
              <dd>{status?.warmInstances ?? '—'}</dd>
            </div>
            <div>
              <dt>{t('runtimePool.tier.cold')}</dt>
              <dd>{status?.coldInstances ?? '—'}</dd>
            </div>
          </dl>
        </article>
        <article>
          <h2>{t('runtimePool.capacity.title')}</h2>
          <p>{t('runtimePool.capacity.unavailable')}</p>
          {reasonCode ? <code>{reasonCode}</code> : null}
        </article>
      </div>

      <article className="runtime-pool-catalog">
        <header>
          <div>
            <h2>{t('runtimePool.instances.title')}</h2>
            <p>{t('runtimePool.instances.count', { count: model.total })}</p>
          </div>
          <div className="runtime-pool-filters">
            <label>
              <span>{t('runtimePool.instances.search')}</span>
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </label>
            <label>
              <span>{t('runtimePool.instances.filterTier')}</span>
              <select
                value={model.query.tier}
                onChange={(event) =>
                  void controller.setQuery({
                    tier: event.target.value as RuntimePoolTier | 'all',
                    page: 1,
                  })
                }
              >
                <option value="all">
                  {t('runtimePool.instances.allTiers')}
                </option>
                {(['hot', 'warm', 'cold'] as const).map((tier) => (
                  <option value={tier} key={tier}>
                    {t(`runtimePool.tier.${tier}`)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>{t('runtimePool.instances.filterStatus')}</span>
              <select
                value={model.query.status}
                onChange={(event) =>
                  void controller.setQuery({
                    status: event.target.value as
                      | RuntimePoolInstanceStatus
                      | 'all',
                    page: 1,
                  })
                }
              >
                <option value="all">
                  {t('runtimePool.instances.allStatuses')}
                </option>
                {INSTANCE_STATUSES.map((instanceStatus) => (
                  <option value={instanceStatus} key={instanceStatus}>
                    {t(`runtimePool.status.${instanceStatus}`)}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </header>

        {model.instancesState === 'empty' ? (
          <div className="runtime-pool-empty">
            <h3>{t('runtimePool.empty.title')}</h3>
            <p>{t('runtimePool.empty.description')}</p>
          </div>
        ) : (
          <InstanceTable
            instances={visibleInstances}
            model={model}
            controller={controller}
            onTerminate={setPendingTerminate}
          />
        )}

        <footer>
          <button
            type="button"
            disabled={model.query.page <= 1 || loading}
            onClick={() =>
              void controller.setQuery({ page: model.query.page - 1 })
            }
          >
            {t('runtimePool.pagination.previous')}
          </button>
          <span>
            {t('runtimePool.pagination.summary', {
              page: model.query.page,
              count: model.total,
            })}
          </span>
          <button
            type="button"
            disabled={
              model.query.page * model.query.pageSize >= model.total || loading
            }
            onClick={() =>
              void controller.setQuery({ page: model.query.page + 1 })
            }
          >
            {t('runtimePool.pagination.next')}
          </button>
        </footer>
      </article>

      {model.mutationState !== 'idle' ? (
        <div
          className="runtime-pool-mutation-notice"
          data-state={model.mutationState}
          role="status"
        >
          <strong>{t(`runtimePool.state.${model.mutationState}`)}</strong>
          {model.mutationReasonCode ? (
            <code>{model.mutationReasonCode}</code>
          ) : null}
        </div>
      ) : null}

      {pendingTerminate ? (
        <div className="runtime-pool-dialog-backdrop">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="terminate-title"
          >
            <h2 id="terminate-title">{t('runtimePool.confirm.title')}</h2>
            <p>{t('runtimePool.confirm.description')}</p>
            <code>{pendingTerminate.instanceKey}</code>
            <div>
              <button type="button" onClick={() => setPendingTerminate(null)}>
                {t('runtimePool.confirm.cancel')}
              </button>
              <button
                type="button"
                onClick={() => {
                  const key = pendingTerminate.instanceKey;
                  setPendingTerminate(null);
                  void controller.terminateInstance(key);
                }}
              >
                {t('runtimePool.action.terminate')}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function InstanceTable({
  instances,
  model,
  controller,
  onTerminate,
}: Readonly<{
  instances: readonly RuntimePoolInstance[];
  model: RuntimePoolViewModel;
  controller: RuntimePoolController;
  onTerminate: (instance: RuntimePoolInstance) => void;
}>) {
  const { t } = useI18n();
  return (
    <div className="runtime-pool-table-scroll">
      <table>
        <thead>
          <tr>
            {[
              'instance',
              'scope',
              'tier',
              'status',
              'health',
              'requests',
              'memory',
              'lastRequest',
              'actions',
            ].map((column) => (
              <th key={column}>{t(`runtimePool.column.${column}`)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {instances.map((instance) => {
            const busy = model.busyInstanceKey === instance.instanceKey;
            return (
              <tr key={instance.instanceKey}>
                <td>
                  <code>{instance.instanceKey}</code>
                </td>
                <td>
                  <strong>{instance.projectId}</strong>
                  <span>{instance.agentMode}</span>
                </td>
                <td>{t(`runtimePool.tier.${instance.tier}`)}</td>
                <td>
                  <span className={`runtime-status status-${instance.status}`}>
                    {t(`runtimePool.status.${instance.status}`)}
                  </span>
                </td>
                <td>{t(`runtimePool.health.${instance.healthStatus}`)}</td>
                <td>
                  {instance.activeRequests} / {instance.totalRequests}
                </td>
                <td>{Math.round(instance.memoryUsedMb)} MB</td>
                <td>{instance.lastRequestAt ?? '—'}</td>
                <td>
                  <div className="runtime-pool-row-actions">
                    {instance.status === 'ready' ||
                    instance.status === 'executing' ? (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          void controller.pauseInstance(instance.instanceKey)
                        }
                      >
                        {t('runtimePool.action.pause')}
                      </button>
                    ) : null}
                    {instance.status === 'paused' ? (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          void controller.resumeInstance(instance.instanceKey)
                        }
                      >
                        {t('runtimePool.action.resume')}
                      </button>
                    ) : null}
                    {instance.status !== 'terminated' &&
                    instance.status !== 'terminating' ? (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => onTerminate(instance)}
                      >
                        {t('runtimePool.action.terminate')}
                      </button>
                    ) : null}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  state,
}: Readonly<{
  label: string;
  value: number | undefined;
  state: RuntimePoolResourceState;
}>) {
  return (
    <article data-state={state}>
      <span>{label}</span>
      <strong>{value ?? '—'}</strong>
    </article>
  );
}

function ResourceNotice({
  state,
  reasonCode,
  onRetry,
}: Readonly<{
  state: RuntimePoolResourceState;
  reasonCode: string | null;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  if (state === 'ready' || state === 'empty') return null;
  return (
    <div
      className="runtime-pool-resource-notice"
      data-state={state}
      role="status"
    >
      <strong>{t(`runtimePool.state.${state}`)}</strong>
      {reasonCode ? <code>{reasonCode}</code> : null}
      {state !== 'loading' && state !== 'unavailable' ? (
        <button type="button" onClick={onRetry}>
          {t('runtimePool.retry')}
        </button>
      ) : null}
    </div>
  );
}

function highestState(
  ...states: readonly RuntimePoolResourceState[]
): RuntimePoolResourceState {
  for (const state of [
    'forbidden',
    'unavailable',
    'error',
    'stale',
    'loading',
  ] as const) {
    if (states.includes(state)) return state;
  }
  return states.every((state) => state === 'empty') ? 'empty' : 'ready';
}
