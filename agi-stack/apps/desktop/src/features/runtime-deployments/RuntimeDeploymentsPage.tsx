import { useI18n } from '../../i18n';
import type {
  RuntimeDeployment,
  RuntimeDeploymentsModel,
  RuntimeDeploymentsQuery,
} from './runtimeDeploymentsTypes';
import './RuntimeDeploymentsPage.css';

export function RuntimeDeploymentsPage({
  model,
  onRetry,
  onQueryChange,
  onInspect,
  onCloseDetail,
  onReconnectProgress,
}: Readonly<{
  model: RuntimeDeploymentsModel;
  onRetry(): void;
  onQueryChange(query: RuntimeDeploymentsQuery): void;
  onInspect(deploymentId: string): Promise<void>;
  onCloseDetail(): void;
  onReconnectProgress(): Promise<void>;
}>) {
  const { t } = useI18n();
  const pageCount = Math.max(
    1,
    Math.ceil(model.total / model.query.pageSize),
  );

  return (
    <main
      className="runtime-deployments"
      aria-labelledby="runtime-deployments-title"
    >
      <header className="runtime-deployments__header">
        <div>
          <span>{t('runtimeDeployments.eyebrow')}</span>
          <h1 id="runtime-deployments-title">
            {t('runtimeDeployments.title')}
          </h1>
          <p>{t('runtimeDeployments.subtitle')}</p>
        </div>
        <button
          type="button"
          onClick={onRetry}
          disabled={
            model.state === 'loading' ||
            !model.allowedActions.includes('refresh')
          }
        >
          {t('common.refresh')}
        </button>
      </header>

      <section className="runtime-deployments__scope" aria-live="polite">
        <div>
          <span>{t('runtimeDeployments.scope.tenant')}</span>
          <strong>{model.scope.tenantId || '—'}</strong>
        </div>
        <div>
          <span>{t('runtimeDeployments.scope.instance')}</span>
          <strong>{model.scope.instanceId || '—'}</strong>
        </div>
        <div>
          <span>{t('runtimeDeployments.scope.state')}</span>
          <strong>{t(`runtimeDeployments.state.${model.state}`)}</strong>
        </div>
      </section>

      <aside className="runtime-deployments__deviation">
        <strong>
          {t(`runtimeDeployments.deviation.${model.authority}.title`)}
        </strong>
        <p>
          {t(`runtimeDeployments.deviation.${model.authority}.description`)}
        </p>
        <code>{model.reasonCode}</code>
      </aside>

      {resourceUnavailable(model) ? (
        <ResourceState model={model} onRetry={onRetry} />
      ) : (
        <section className="runtime-deployments__panel">
          <div className="runtime-deployments__panel-heading">
            <div>
              <h2>{t('runtimeDeployments.history.title')}</h2>
              <p>
                {t('runtimeDeployments.history.count', {
                  count: model.deployments.length,
                  total: model.total,
                })}
              </p>
            </div>
            <span>{t('runtimeDeployments.readOnly')}</span>
          </div>

          {model.deployments.length === 0 ? (
            <div className="runtime-deployments__empty">
              <h3>{t('runtimeDeployments.empty.title')}</h3>
              <p>{t('runtimeDeployments.empty.description')}</p>
            </div>
          ) : (
            <div className="runtime-deployments__table-wrap">
              <table>
                <thead>
                  <tr>
                    {[
                      'id',
                      'action',
                      'revision',
                      'status',
                      'image',
                      'created',
                    ].map((column) => (
                      <th key={column}>
                        {t(`runtimeDeployments.column.${column}`)}
                      </th>
                    ))}
                    <th>{t('runtimeDeployments.column.actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {model.deployments.map((deployment) => (
                    <DeploymentRow
                      key={deployment.id}
                      deployment={deployment}
                      onInspect={onInspect}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <footer className="runtime-deployments__pagination">
            <span>
              {t('runtimeDeployments.pagination', {
                page: model.query.page,
                pages: pageCount,
              })}
            </span>
            <div>
              <button
                type="button"
                disabled={model.query.page <= 1}
                onClick={() =>
                  onQueryChange({ page: model.query.page - 1 })
                }
              >
                {t('runtimeDeployments.previous')}
              </button>
              <button
                type="button"
                disabled={model.query.page >= pageCount}
                onClick={() =>
                  onQueryChange({ page: model.query.page + 1 })
                }
              >
                {t('runtimeDeployments.next')}
              </button>
            </div>
          </footer>
        </section>
      )}

      {model.detailState === 'loading' && (
        <section className="runtime-deployments__detail" aria-live="polite">
          <p>{t('runtimeDeployments.detail.loading')}</p>
        </section>
      )}
      {detailUnavailable(model) && (
        <section className="runtime-deployments__detail" role="status">
          <h3>{t(`runtimeDeployments.detailState.${model.detailState}`)}</h3>
          <code>{model.detailReasonCode}</code>
        </section>
      )}
      {model.selectedDeployment && (
        <DeploymentDetail
          model={model}
          deployment={model.selectedDeployment}
          onClose={onCloseDetail}
          onReconnect={onReconnectProgress}
        />
      )}
    </main>
  );
}

function DeploymentRow({
  deployment,
  onInspect,
}: Readonly<{
  deployment: RuntimeDeployment;
  onInspect(deploymentId: string): Promise<void>;
}>) {
  const { t } = useI18n();
  return (
    <tr>
      <td>
        <code>{deployment.id}</code>
      </td>
      <td>{deployment.action}</td>
      <td>{deployment.revision}</td>
      <td>
        <span
          className="runtime-deployments__status"
          data-status={deployment.status}
        >
          {t(`runtimeDeployments.status.${deployment.status}`)}
        </span>
      </td>
      <td>{deployment.imageVersion || '—'}</td>
      <td>{formatDate(deployment.createdAt)}</td>
      <td>
        <button
          type="button"
          onClick={() => void onInspect(deployment.id)}
        >
          {t('runtimeDeployments.inspect')}
        </button>
      </td>
    </tr>
  );
}

function DeploymentDetail({
  model,
  deployment,
  onClose,
  onReconnect,
}: Readonly<{
  model: RuntimeDeploymentsModel;
  deployment: RuntimeDeployment;
  onClose(): void;
  onReconnect(): Promise<void>;
}>) {
  const { t } = useI18n();
  return (
    <section
      className="runtime-deployments__detail"
      aria-labelledby="runtime-deployment-detail-title"
    >
      <div className="runtime-deployments__detail-heading">
        <div>
          <span>{t('runtimeDeployments.detail.eyebrow')}</span>
          <h2 id="runtime-deployment-detail-title">{deployment.id}</h2>
        </div>
        <button type="button" onClick={onClose}>
          {t('common.close')}
        </button>
      </div>
      <div className="runtime-deployments__detail-grid">
        <DetailItem
          label={t('runtimeDeployments.column.status')}
          value={t(`runtimeDeployments.status.${deployment.status}`)}
        />
        <DetailItem
          label={t('runtimeDeployments.column.action')}
          value={deployment.action}
        />
        <DetailItem
          label={t('runtimeDeployments.column.revision')}
          value={String(deployment.revision)}
        />
        <DetailItem
          label={t('runtimeDeployments.detail.progress')}
          value={t(`runtimeDeployments.progress.${model.progressState}`)}
        />
        <DetailItem
          label={t('runtimeDeployments.detail.started')}
          value={formatDate(deployment.startedAt)}
        />
        <DetailItem
          label={t('runtimeDeployments.detail.finished')}
          value={formatDate(deployment.finishedAt)}
        />
        <DetailItem
          label={t('runtimeDeployments.detail.replicas')}
          value={
            deployment.replicas === null
              ? '—'
              : String(deployment.replicas)
          }
        />
      </div>
      {model.progressRetryVisible && (
        <div className="runtime-deployments__stream-warning">
          <div>
            <strong>{t('runtimeDeployments.progress.stale')}</strong>
            <code>{model.progressReasonCode}</code>
          </div>
          <button type="button" onClick={() => void onReconnect()}>
            {t('runtimeDeployments.reconnect')}
          </button>
        </div>
      )}
    </section>
  );
}

function DetailItem({
  label,
  value,
}: Readonly<{ label: string; value: string }>) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ResourceState({
  model,
  onRetry,
}: Readonly<{ model: RuntimeDeploymentsModel; onRetry(): void }>) {
  const { t } = useI18n();
  return (
    <section className="runtime-deployments__resource" role="status">
      <h3>{t(`runtimeDeployments.state.${model.state}`)}</h3>
      <p>{t(`runtimeDeployments.reason.${model.reasonCode}`)}</p>
      <code>{model.reasonCode}</code>
      {model.retryVisible && (
        <button type="button" onClick={onRetry}>
          {t('common.retry')}
        </button>
      )}
    </section>
  );
}

function resourceUnavailable(model: RuntimeDeploymentsModel): boolean {
  return (
    model.state === 'error' ||
    model.state === 'forbidden' ||
    model.state === 'conflict' ||
    model.state === 'unavailable'
  );
}

function detailUnavailable(model: RuntimeDeploymentsModel): boolean {
  return (
    model.state !== 'unavailable' &&
    model.selectedDeployment === null &&
    model.detailState !== 'idle' &&
    model.detailState !== 'loading' &&
    model.detailState !== 'ready'
  );
}

function formatDate(value: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
