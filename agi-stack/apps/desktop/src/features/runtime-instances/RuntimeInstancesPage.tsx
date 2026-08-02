import type { ChangeEvent } from 'react';

import { useI18n } from '../../i18n';
import type {
  RuntimeInstanceSummary,
  RuntimeInstancesModel,
  RuntimeInstancesQuery,
} from './runtimeInstancesTypes';
import './RuntimeInstancesPage.css';

export function RuntimeInstancesPage({
  model,
  onRetry,
  onQueryChange,
  onRestart,
  onDelete,
}: Readonly<{
  model: RuntimeInstancesModel;
  onRetry(): void;
  onQueryChange(query: RuntimeInstancesQuery): void;
  onRestart(instanceId: string): Promise<void>;
  onDelete(instanceId: string): Promise<void>;
}>) {
  const { t } = useI18n();
  const loading = model.state === 'loading';
  const canRestart = model.allowedActions.includes('restart');
  const canDelete = model.allowedActions.includes('delete');
  const pageCount = Math.max(1, Math.ceil(model.total / model.query.pageSize));

  const updateSearch = (event: ChangeEvent<HTMLInputElement>) => {
    onQueryChange({ search: event.target.value, page: 1 });
  };
  const updateStatus = (event: ChangeEvent<HTMLSelectElement>) => {
    onQueryChange({ status: event.target.value, page: 1 });
  };

  return (
    <section
      className="runtime-instances-page"
      aria-labelledby="runtime-instances-title"
    >
      <header className="runtime-instances-header">
        <div>
          <span>{t('runtimeInstances.eyebrow')}</span>
          <h1 id="runtime-instances-title">{t('runtimeInstances.title')}</h1>
          <p>{t('runtimeInstances.subtitle')}</p>
        </div>
        <button type="button" onClick={onRetry} disabled={loading}>
          {t('common.refresh')}
        </button>
      </header>

      <div className="runtime-instances-scope">
        <span>{t('runtimeInstances.scope')}</span>
        <strong>{model.scope.tenantId}</strong>
        <code>{model.authority}</code>
        <small>{t(`runtimeInstances.state.${model.state}`)}</small>
      </div>

      <article className="runtime-instances-deviation" data-authority={model.authority}>
        <div>
          <strong>{t(`runtimeInstances.deviation.${model.authority}.title`)}</strong>
          <p>{t(`runtimeInstances.deviation.${model.authority}.description`)}</p>
        </div>
        <code>{model.reasonCode}</code>
      </article>

      <div className="runtime-instances-summary">
        <Summary
          label={t('runtimeInstances.summary.total')}
          value={model.total}
        />
        <Summary
          label={t('runtimeInstances.summary.visible')}
          value={model.instances.length}
        />
        <Summary
          label={t('runtimeInstances.summary.running')}
          value={
            model.instances.filter((instance) => instance.status === 'running')
              .length
          }
        />
      </div>

      <article className="runtime-instances-inventory">
        <header>
          <div>
            <h2>{t('runtimeInstances.inventory.title')}</h2>
            <p>
              {t('runtimeInstances.inventory.count', {
                count: model.instances.length,
              })}
            </p>
          </div>
          <div className="runtime-instances-filters">
            <label>
              <span>{t('runtimeInstances.search')}</span>
              <input
                type="search"
                value={model.query.search}
                onChange={updateSearch}
                disabled={loading}
              />
            </label>
            <label>
              <span>{t('runtimeInstances.statusFilter')}</span>
              <select
                value={model.query.status}
                onChange={updateStatus}
                disabled={loading}
              >
                <option value="all">{t('runtimeInstances.status.all')}</option>
                <option value="running">{t('runtimeInstances.status.running')}</option>
                <option value="stopped">{t('runtimeInstances.status.stopped')}</option>
                <option value="error">{t('runtimeInstances.status.error')}</option>
              </select>
            </label>
          </div>
        </header>

        {model.state === 'forbidden' || model.state === 'unavailable' ? (
          <StateNotice model={model} onRetry={onRetry} />
        ) : model.instances.length === 0 && !loading ? (
          <div className="runtime-instances-empty">
            <h3>{t('runtimeInstances.empty.title')}</h3>
            <p>{t('runtimeInstances.empty.description')}</p>
          </div>
        ) : (
          <div className="runtime-instances-table-scroll">
            <table>
              <thead>
                <tr>
                  {['name', 'status', 'health', 'image', 'replicas', 'cluster', 'updated'].map(
                    (column) => (
                      <th key={column}>{t(`runtimeInstances.column.${column}`)}</th>
                    ),
                  )}
                  {canRestart || canDelete ? (
                    <th>{t('runtimeInstances.column.actions')}</th>
                  ) : null}
                </tr>
              </thead>
              <tbody>
                {model.instances.map((instance) => (
                  <InstanceRow
                    key={instance.id}
                    instance={instance}
                    busy={model.busyInstanceId === instance.id}
                    canRestart={canRestart}
                    canDelete={canDelete}
                    onRestart={onRestart}
                    onDelete={onDelete}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}

        <footer className="runtime-instances-pagination">
          <span>
            {t('runtimeInstances.pagination', {
              page: model.query.page,
              pages: pageCount,
            })}
          </span>
          <div>
            <button
              type="button"
              disabled={loading || model.query.page <= 1}
              onClick={() => onQueryChange({ page: model.query.page - 1 })}
            >
              {t('runtimeInstances.previous')}
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
              {t('runtimeInstances.next')}
            </button>
          </div>
        </footer>
      </article>

      {model.mutationState !== 'idle' && model.mutationReasonCode ? (
        <div className="runtime-instances-mutation-error" role="status">
          <strong>{t(`runtimeInstances.mutation.${model.mutationState}`)}</strong>
          <code>{model.mutationReasonCode}</code>
        </div>
      ) : null}
    </section>
  );
}

function InstanceRow({
  instance,
  busy,
  canRestart,
  canDelete,
  onRestart,
  onDelete,
}: Readonly<{
  instance: RuntimeInstanceSummary;
  busy: boolean;
  canRestart: boolean;
  canDelete: boolean;
  onRestart(instanceId: string): Promise<void>;
  onDelete(instanceId: string): Promise<void>;
}>) {
  const { t } = useI18n();
  return (
    <tr>
      <td>
        <strong>{instance.name}</strong>
        <code>{instance.id}</code>
        <small>{t(`runtimeInstances.projection.${instance.projection}`)}</small>
      </td>
      <td>
        <span className="runtime-instances-status" data-state={instance.status}>
          {instance.status}
        </span>
      </td>
      <td>{instance.healthStatus ?? '—'}</td>
      <td>{instance.imageVersion ?? '—'}</td>
      <td>
        {instance.replicas === null
          ? '—'
          : `${String(instance.availableReplicas ?? 0)} / ${String(instance.replicas)}`}
      </td>
      <td>{instance.clusterId ?? '—'}</td>
      <td>
        {instance.updatedAt ?? instance.createdAt
          ? new Date(instance.updatedAt ?? instance.createdAt ?? '').toLocaleString()
          : '—'}
      </td>
      {canRestart || canDelete ? (
        <td>
          <div className="runtime-instances-row-actions">
            {canRestart ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => void onRestart(instance.id).catch(() => {})}
              >
                {t('runtimeInstances.restart')}
              </button>
            ) : null}
            {canDelete ? (
              <button
                type="button"
                className="danger"
                disabled={busy}
                onClick={() => {
                  if (window.confirm(t('runtimeInstances.deleteConfirm'))) {
                    void onDelete(instance.id).catch(() => {});
                  }
                }}
              >
                {t('common.delete')}
              </button>
            ) : null}
          </div>
        </td>
      ) : null}
    </tr>
  );
}

function Summary({
  label,
  value,
}: Readonly<{ label: string; value: number }>) {
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
}: Readonly<{ model: RuntimeInstancesModel; onRetry(): void }>) {
  const { t } = useI18n();
  return (
    <div className="runtime-instances-empty">
      <h3>{t(`runtimeInstances.state.${model.state}`)}</h3>
      <code>{model.reasonCode}</code>
      {model.retryVisible ? (
        <button type="button" onClick={onRetry}>
          {t('common.retry')}
        </button>
      ) : null}
    </div>
  );
}
