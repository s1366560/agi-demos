import { useMemo, useState } from 'react';

import { useI18n } from '../../i18n';
import type { UnifiedRuntimesModel } from './unifiedRuntimesTypes';
import './UnifiedRuntimesPage.css';

export function UnifiedRuntimesPage({
  model,
  onRetry,
  autoRefresh,
  onAutoRefreshChange,
}: Readonly<{
  model: UnifiedRuntimesModel;
  onRetry: () => void;
  autoRefresh: boolean;
  onAutoRefreshChange: (enabled: boolean) => void;
}>) {
  const { t } = useI18n();
  const [search, setSearch] = useState('');
  const query = search.trim().toLocaleLowerCase();
  const rows = useMemo(
    () =>
      query
        ? model.rows.filter((row) =>
            `${row.identifier} ${row.projectId} ${row.kind}`
              .toLocaleLowerCase()
              .includes(query),
          )
        : model.rows,
    [model.rows, query],
  );
  const poolRows = model.rows.filter((row) => row.kind === 'pool_actor');
  const sandboxRows = model.rows.filter((row) => row.kind === 'sandbox');
  const attentionRows = model.rows.filter(
    (row) => row.health === 'unhealthy' || row.health === 'degraded',
  );
  const loading = [
    model.poolState,
    model.sandboxState,
    model.sidecarState,
    model.capabilitiesState,
  ].includes('loading');

  return (
    <section
      className="unified-runtimes-page"
      aria-labelledby="unified-runtimes-title"
    >
      <header className="unified-runtimes-header">
        <div>
          <span>{t('unifiedRuntimes.eyebrow')}</span>
          <h1 id="unified-runtimes-title">{t('unifiedRuntimes.title')}</h1>
          <p>{t('unifiedRuntimes.subtitle')}</p>
        </div>
        <div className="unified-runtimes-actions">
          <label>
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(event) => onAutoRefreshChange(event.target.checked)}
            />
            {t('unifiedRuntimes.autoRefresh')}
          </label>
          <button type="button" onClick={onRetry} disabled={loading}>
            {t('common.refresh')}
          </button>
        </div>
      </header>

      <div className="unified-runtimes-scope">
        <span>{t('unifiedRuntimes.scope')}</span>
        <strong>{model.scope.tenantId}</strong>
        <code>{model.authority}</code>
        {model.lastUpdatedAt ? (
          <small>
            {t('unifiedRuntimes.updated', {
              time: new Date(model.lastUpdatedAt).toLocaleTimeString(),
            })}
          </small>
        ) : null}
      </div>

      <article className="unified-runtimes-deviation">
        <div>
          <strong>{t(`unifiedRuntimes.deviation.${model.authority}.title`)}</strong>
          <p>{t(`unifiedRuntimes.deviation.${model.authority}.description`)}</p>
        </div>
        <code>{model.reasonCode}</code>
      </article>

      <div className="unified-runtimes-authorities">
        <AuthorityCard
          label={t('unifiedRuntimes.authority.pool')}
          state={model.poolState}
          reasonCode={model.poolReasonCode}
        />
        <AuthorityCard
          label={t('unifiedRuntimes.authority.sandboxes')}
          state={model.sandboxState}
          reasonCode={model.sandboxReasonCode}
        />
        <AuthorityCard
          label={t('unifiedRuntimes.authority.sidecar')}
          state={model.sidecarState}
          reasonCode={model.sidecarReasonCode}
        />
        <AuthorityCard
          label={t('unifiedRuntimes.authority.capabilities')}
          state={model.capabilitiesState}
          reasonCode={model.capabilitiesReasonCode}
        />
      </div>

      <div className="unified-runtimes-summary">
        <SummaryCard
          label={t('unifiedRuntimes.summary.pool')}
          value={poolRows.length}
        />
        <SummaryCard
          label={t('unifiedRuntimes.summary.sandboxes')}
          value={sandboxRows.length}
        />
        <SummaryCard
          label={t('unifiedRuntimes.summary.total')}
          value={model.rows.length}
        />
        <SummaryCard
          label={t('unifiedRuntimes.summary.attention')}
          value={attentionRows.length}
        />
      </div>

      <article className="unified-runtimes-catalog">
        <header>
          <div>
            <h2>{t('unifiedRuntimes.inventory.title')}</h2>
            <p>
              {t('unifiedRuntimes.inventory.count', {
                count: model.rows.length,
              })}
            </p>
          </div>
          <label>
            <span>{t('unifiedRuntimes.inventory.search')}</span>
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
        </header>
        {model.rows.length === 0 && !loading ? (
          <div className="unified-runtimes-empty">
            <h3>{t('unifiedRuntimes.empty.title')}</h3>
            <p>{t('unifiedRuntimes.empty.description')}</p>
          </div>
        ) : (
          <div className="unified-runtimes-table-scroll">
            <table>
              <thead>
                <tr>
                  {[
                    'kind',
                    'identifier',
                    'scope',
                    'status',
                    'health',
                    'tier',
                    'load',
                    'activity',
                  ].map((column) => (
                    <th key={column}>
                      {t(`unifiedRuntimes.column.${column}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.key}>
                    <td>
                      <span className="unified-runtimes-kind" data-kind={row.kind}>
                        {t(`unifiedRuntimes.kind.${row.kind}`)}
                      </span>
                    </td>
                    <td>
                      <code>{row.identifier}</code>
                    </td>
                    <td>
                      <span>{row.projectId}</span>
                      <small>{row.tenantId}</small>
                    </td>
                    <td>
                      <span className="unified-runtimes-status" data-state={row.status}>
                        {row.status}
                      </span>
                    </td>
                    <td>
                      <span className="unified-runtimes-health" data-health={row.health}>
                        {row.health}
                      </span>
                    </td>
                    <td>{row.tier ?? '—'}</td>
                    <td>
                      {row.loadLabel ?? '—'}
                      {row.memoryMb === null
                        ? ''
                        : ` · ${String(Math.round(row.memoryMb))} MB`}
                    </td>
                    <td>
                      {row.lastActivity
                        ? new Date(row.lastActivity).toLocaleString()
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </article>
    </section>
  );
}

function AuthorityCard({
  label,
  state,
  reasonCode,
}: Readonly<{
  label: string;
  state: UnifiedRuntimesModel['poolState'];
  reasonCode: string | null;
}>) {
  const { t } = useI18n();
  return (
    <article data-state={state}>
      <span>{label}</span>
      <strong>{t(`unifiedRuntimes.state.${state}`)}</strong>
      {reasonCode ? <code title={reasonCode}>{reasonCode}</code> : null}
    </article>
  );
}

function SummaryCard({
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
