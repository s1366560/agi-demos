import type { ChangeEvent } from 'react';

import { useI18n } from '../../i18n';
import type {
  RuntimeClusterSummary,
  RuntimeClustersModel,
  RuntimeClustersQuery,
} from './runtimeClustersTypes';
import './RuntimeClustersPage.css';

export function RuntimeClustersPage({
  model,
  onRetry,
  onQueryChange,
  onFiltersChange,
  onInspectHealth,
  onCloseHealth,
}: Readonly<{
  model: RuntimeClustersModel;
  onRetry(): void;
  onQueryChange(query: RuntimeClustersQuery): void;
  onFiltersChange(query: RuntimeClustersQuery): void;
  onInspectHealth(clusterId: string): Promise<void>;
  onCloseHealth(): void;
}>) {
  const { t } = useI18n();
  const loading = model.state === 'loading';
  const pageCount = Math.max(1, Math.ceil(model.total / model.query.pageSize));
  const updateSearch = (event: ChangeEvent<HTMLInputElement>) => {
    onFiltersChange({ search: event.target.value });
  };
  const updateStatus = (event: ChangeEvent<HTMLSelectElement>) => {
    onFiltersChange({ status: event.target.value });
  };

  return (
    <section className="runtime-clusters-page" aria-labelledby="runtime-clusters-title">
      <header className="runtime-clusters-header">
        <div>
          <span>{t('runtimeClusters.eyebrow')}</span>
          <h1 id="runtime-clusters-title">{t('runtimeClusters.title')}</h1>
          <p>{t('runtimeClusters.subtitle')}</p>
        </div>
        <button type="button" onClick={onRetry} disabled={loading}>
          {t('common.refresh')}
        </button>
      </header>

      <div className="runtime-clusters-scope">
        <span>{t('runtimeClusters.scope')}</span>
        <strong>{model.scope.tenantId}</strong>
        <code>{model.authority}</code>
        <small>{t(`runtimeClusters.state.${model.state}`)}</small>
      </div>

      <article className="runtime-clusters-deviation" data-authority={model.authority}>
        <div>
          <strong>{t(`runtimeClusters.deviation.${model.authority}.title`)}</strong>
          <p>{t(`runtimeClusters.deviation.${model.authority}.description`)}</p>
        </div>
        <code>{model.reasonCode}</code>
      </article>

      <div className="runtime-clusters-summary">
        <Summary label={t('runtimeClusters.summary.total')} value={model.total} />
        <Summary
          label={t('runtimeClusters.summary.visible')}
          value={model.visibleClusters.length}
        />
        <Summary
          label={t('runtimeClusters.summary.active')}
          value={
            model.visibleClusters.filter((cluster) => cluster.status === 'active')
              .length
          }
        />
      </div>

      <article className="runtime-clusters-inventory">
        <header>
          <div>
            <h2>{t('runtimeClusters.inventory.title')}</h2>
            <p>
              {t('runtimeClusters.inventory.count', {
                count: model.visibleClusters.length,
              })}
            </p>
          </div>
          <div className="runtime-clusters-filters">
            <label>
              <span>{t('runtimeClusters.search')}</span>
              <input
                type="search"
                value={model.query.search}
                onChange={updateSearch}
                disabled={loading || model.authority === 'local'}
              />
            </label>
            <label>
              <span>{t('runtimeClusters.statusFilter')}</span>
              <select
                value={model.query.status}
                onChange={updateStatus}
                disabled={loading || model.authority === 'local'}
              >
                {['all', 'active', 'pending', 'provisioning', 'maintenance', 'error', 'inactive'].map(
                  (status) => (
                    <option value={status} key={status}>
                      {t(`runtimeClusters.status.${status}`)}
                    </option>
                  ),
                )}
              </select>
            </label>
          </div>
        </header>

        {model.state === 'loading' && model.clusters.length === 0 ? (
          <StateNotice model={model} onRetry={onRetry} />
        ) : model.state === 'conflict' ||
          model.state === 'forbidden' ||
          model.state === 'unavailable' ? (
          <StateNotice model={model} onRetry={onRetry} />
        ) : model.visibleClusters.length === 0 && !loading ? (
          <div className="runtime-clusters-empty">
            <h3>{t('runtimeClusters.empty.title')}</h3>
            <p>{t('runtimeClusters.empty.description')}</p>
          </div>
        ) : (
          <ClusterTable
            clusters={model.visibleClusters}
            loading={model.healthState === 'loading'}
            selectedClusterId={model.selectedClusterId}
            onInspectHealth={onInspectHealth}
          />
        )}

        <footer className="runtime-clusters-pagination">
          <span>
            {t('runtimeClusters.pagination', {
              page: model.query.page,
              pages: pageCount,
            })}
          </span>
          <div>
            <button
              type="button"
              disabled={loading || model.query.page <= 1 || model.authority === 'local'}
              onClick={() => onQueryChange({ page: model.query.page - 1 })}
            >
              {t('runtimeClusters.previous')}
            </button>
            <button
              type="button"
              disabled={
                loading ||
                model.authority === 'local' ||
                model.query.page >= pageCount
              }
              onClick={() => onQueryChange({ page: model.query.page + 1 })}
            >
              {t('runtimeClusters.next')}
            </button>
          </div>
        </footer>
      </article>

      {model.selectedClusterId ? (
        <HealthDialog model={model} onClose={onCloseHealth} />
      ) : null}
    </section>
  );
}

function ClusterTable({
  clusters,
  loading,
  selectedClusterId,
  onInspectHealth,
}: Readonly<{
  clusters: readonly RuntimeClusterSummary[];
  loading: boolean;
  selectedClusterId: string | null;
  onInspectHealth(clusterId: string): Promise<void>;
}>) {
  const { t } = useI18n();
  return (
    <div className="runtime-clusters-table-scroll">
      <table>
        <thead>
          <tr>
            {['name', 'provider', 'endpoint', 'status', 'health', 'checked', 'actions'].map(
              (column) => (
                <th key={column}>{t(`runtimeClusters.column.${column}`)}</th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {clusters.map((cluster) => (
            <tr key={cluster.id}>
              <td>
                <strong>{cluster.name}</strong>
                <code>{cluster.id}</code>
              </td>
              <td>{cluster.computeProvider}</td>
              <td>{cluster.proxyEndpoint ?? '—'}</td>
              <td>
                <span className="runtime-clusters-status" data-state={cluster.status}>
                  {cluster.status}
                </span>
              </td>
              <td>{cluster.healthStatus ?? '—'}</td>
              <td>{cluster.lastHealthCheck ?? '—'}</td>
              <td>
                <button
                  type="button"
                  disabled={loading && selectedClusterId === cluster.id}
                  onClick={() => void onInspectHealth(cluster.id).catch(() => {})}
                >
                  {t('runtimeClusters.inspectHealth')}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HealthDialog({
  model,
  onClose,
}: Readonly<{ model: RuntimeClustersModel; onClose(): void }>) {
  const { t } = useI18n();
  return (
    <div className="runtime-clusters-dialog-backdrop">
      <aside role="dialog" aria-modal="true" aria-labelledby="cluster-health-title">
        <header>
          <h2 id="cluster-health-title">{t('runtimeClusters.health.title')}</h2>
          <button type="button" onClick={onClose}>
            {t('common.close')}
          </button>
        </header>
        {model.healthState === 'loading' ? (
          <p>{t('runtimeClusters.health.loading')}</p>
        ) : model.health ? (
          <dl>
            <HealthRow label={t('runtimeClusters.health.status')} value={model.health.status} />
            <HealthRow
              label={t('runtimeClusters.health.nodes')}
              value={String(model.health.nodeCount)}
            />
            <HealthRow
              label={t('runtimeClusters.health.cpu')}
              value={percentage(model.health.cpuUsage)}
            />
            <HealthRow
              label={t('runtimeClusters.health.memory')}
              value={percentage(model.health.memoryUsage)}
            />
            <HealthRow
              label={t('runtimeClusters.health.checked')}
              value={model.health.checkedAt ?? '—'}
            />
          </dl>
        ) : (
          <code>{model.healthReasonCode}</code>
        )}
      </aside>
    </div>
  );
}

function HealthRow({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function Summary({ label, value }: Readonly<{ label: string; value: number }>) {
  return (
    <article>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function StateNotice({
  model,
  onRetry,
}: Readonly<{ model: RuntimeClustersModel; onRetry(): void }>) {
  const { t } = useI18n();
  return (
    <div className="runtime-clusters-empty">
      <h3>{t(`runtimeClusters.state.${model.state}`)}</h3>
      <code>{model.reasonCode}</code>
      {model.retryVisible ? (
        <button type="button" onClick={onRetry}>
          {t('common.retry')}
        </button>
      ) : null}
    </div>
  );
}

function percentage(value: number | null): string {
  return value === null ? '—' : `${value.toFixed(2)}%`;
}
