import {
  BarChartIcon,
  ExclamationTriangleIcon,
  LockClosedIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';
import { Button } from '@radix-ui/themes';

import { useI18n } from '../../i18n';
import type { TenantAnalyticsPresentationModel } from './tenantAnalyticsPresentationModel';
import './TenantAnalyticsPage.css';

export function TenantAnalyticsPage({
  model,
  tenantPlan,
  onRetry,
}: Readonly<{
  model: TenantAnalyticsPresentationModel;
  tenantPlan: string | null;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  if (
    model.state !== 'ready' &&
    model.state !== 'degraded' &&
    model.state !== 'empty'
  ) {
    return <TenantAnalyticsState model={model} onRetry={onRetry} />;
  }
  const maxMemoryCount = Math.max(
    1,
    ...model.memoryGrowth.points.map((point) => point.count),
  );
  const maxStorage = Math.max(
    1,
    ...model.projects.map((project) => project.storageBytes ?? 0),
  );
  return (
    <section className="tenant-analytics-page" data-state={model.state}>
      <header className="tenant-analytics-header">
        <div>
          <span>{t('tenantAnalytics.eyebrow')}</span>
          <h1>{t('tenantAnalytics.title')}</h1>
          <p>{t('tenantAnalytics.subtitle')}</p>
        </div>
        <div className="tenant-analytics-context">
          <code>{model.scope.tenantId}</code>
          <span>{tenantPlan ?? t('tenantAnalytics.unavailable')}</span>
        </div>
      </header>

      {model.state === 'degraded' ? (
        <div className="tenant-analytics-notice" role="status">
          <ExclamationTriangleIcon />
          <span>{t('tenantAnalytics.degraded')}</span>
          <code>{model.reasonCode}</code>
        </div>
      ) : null}

      <div className="tenant-analytics-summary">
        {model.summary.map((item) => (
          <article key={item.id} data-availability={item.availability}>
            <span>{t(`tenantAnalytics.summary.${item.id}`)}</span>
            <strong>{item.value ?? t('tenantAnalytics.unavailable')}</strong>
            {item.id === 'memories' && model.trend ? (
              <small>{t(`tenantAnalytics.trend.${model.trend}`)}</small>
            ) : null}
            {item.reasonCode ? <code>{item.reasonCode}</code> : null}
          </article>
        ))}
      </div>

      <div className="tenant-analytics-panels">
        <section className="tenant-analytics-panel">
          <div className="tenant-analytics-panel-heading">
            <BarChartIcon />
            <div>
              <h2>{t('tenantAnalytics.growth.title')}</h2>
              <p>{t('tenantAnalytics.growth.description')}</p>
            </div>
          </div>
          {model.memoryGrowth.availability === 'unavailable' ? (
            <UnavailableProjection
              reasonCode={model.memoryGrowth.reasonCode}
            />
          ) : model.memoryGrowth.points.length === 0 ? (
            <p className="tenant-analytics-empty">
              {t('tenantAnalytics.growth.empty')}
            </p>
          ) : (
            <div className="tenant-analytics-bars" role="img">
              {model.memoryGrowth.points.map((point) => (
                <div key={point.date}>
                  <span
                    style={{
                      height: `${Math.max(4, (point.count / maxMemoryCount) * 100)}%`,
                    }}
                  />
                  <small>{point.date}</small>
                  <strong>{point.count}</strong>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="tenant-analytics-panel">
          <div className="tenant-analytics-panel-heading">
            <BarChartIcon />
            <div>
              <h2>{t('tenantAnalytics.storage.title')}</h2>
              <p>{t('tenantAnalytics.storage.description')}</p>
            </div>
          </div>
          {model.projects.length === 0 ? (
            <p className="tenant-analytics-empty">
              {t('tenantAnalytics.storage.empty')}
            </p>
          ) : (
            <div className="tenant-analytics-projects">
              {model.projects.map((project) => (
                <article key={project.name}>
                  <div>
                    <strong>{project.name}</strong>
                    <span>
                      {project.storageLabel ??
                        t('tenantAnalytics.unavailable')}
                    </span>
                  </div>
                  <div className="tenant-analytics-meter">
                    <span
                      style={{
                        width: `${((project.storageBytes ?? 0) / maxStorage) * 100}%`,
                      }}
                    />
                  </div>
                  {project.reasonCode ? <code>{project.reasonCode}</code> : null}
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
    </section>
  );
}

function UnavailableProjection({
  reasonCode,
}: Readonly<{ reasonCode: string | null }>) {
  const { t } = useI18n();
  return (
    <div className="tenant-analytics-projection-unavailable">
      <ExclamationTriangleIcon />
      <span>{t('tenantAnalytics.unavailable')}</span>
      {reasonCode ? <code>{reasonCode}</code> : null}
    </div>
  );
}

function TenantAnalyticsState({
  model,
  onRetry,
}: Readonly<{
  model: TenantAnalyticsPresentationModel;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  const busy = model.state === 'loading' || model.state === 'scope_switch';
  const Icon = model.state === 'forbidden' ? LockClosedIcon : ReloadIcon;
  return (
    <section
      className="tenant-analytics-page tenant-analytics-state"
      data-state={model.state}
      aria-busy={busy || undefined}
    >
      <Icon />
      <h1>{t(`tenantAnalytics.state.${model.state}.title`)}</h1>
      <p>{t(`tenantAnalytics.state.${model.state}.description`)}</p>
      <code>{model.reasonCode ?? model.scope.tenantId}</code>
      {model.retryVisible ? (
        <Button color="gray" variant="surface" onClick={onRetry}>
          <ReloadIcon />
          {t('common.retry')}
        </Button>
      ) : null}
    </section>
  );
}
