import {
  BarChartIcon,
  ExclamationTriangleIcon,
  LockClosedIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';
import { Button } from '@radix-ui/themes';

import { useI18n } from '../../i18n';
import type { TenantOverviewPresentationModel } from './tenantOverviewPresentationModel';
import './TenantOverviewPage.css';

export function TenantOverviewPage({
  model,
  onRetry,
}: Readonly<{
  model: TenantOverviewPresentationModel;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  if (model.state !== 'ready' && model.state !== 'degraded') {
    return <TenantOverviewState model={model} onRetry={onRetry} />;
  }
  return (
    <section className="tenant-overview-page" data-state={model.state}>
      <header className="tenant-overview-header">
        <div>
          <span>{t('tenantOverview.eyebrow')}</span>
          <h1>{model.tenant?.organizationId}</h1>
          <p>{t('tenantOverview.plan', { plan: model.tenant?.plan ?? '' })}</p>
        </div>
        <code>{model.scope.tenantId}</code>
      </header>
      {model.state === 'degraded' ? (
        <div className="tenant-overview-notice" role="status">
          <ExclamationTriangleIcon />
          <span>{t('tenantOverview.degraded')}</span>
          <code>{model.reasonCode}</code>
        </div>
      ) : null}
      <div className="tenant-overview-summary">
        {model.summary.map((item) => (
          <article key={item.id} data-availability={item.availability}>
            <span>{t(`tenantOverview.summary.${item.id}`)}</span>
            <strong>{item.value ?? t('tenantOverview.unavailable')}</strong>
            {item.reasonCode ? <code>{item.reasonCode}</code> : null}
          </article>
        ))}
      </div>
      <section className="tenant-overview-projects">
        <div>
          <BarChartIcon />
          <h2>{t('tenantOverview.projects')}</h2>
        </div>
        {model.projects.length === 0 ? (
          <p role="status" data-state="empty">
            {t('tenantOverview.projects.empty')}
          </p>
        ) : (
          <div className="tenant-overview-project-list">
            {model.projects.map((project) => (
              <article key={project.id}>
                <div>
                  <strong>{project.name}</strong>
                  <span>{project.status}</span>
                </div>
                <span>{project.owner ?? t('tenantOverview.unavailable')}</span>
                <span>{project.memoryConsumed ?? t('tenantOverview.unavailable')}</span>
              </article>
            ))}
          </div>
        )}
      </section>
    </section>
  );
}

function TenantOverviewState({
  model,
  onRetry,
}: Readonly<{
  model: TenantOverviewPresentationModel;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  const busy = model.state === 'loading' || model.state === 'scope_switch';
  const Icon = model.state === 'forbidden' ? LockClosedIcon : ReloadIcon;
  return (
    <section
      className="tenant-overview-page tenant-overview-state"
      data-state={model.state}
      aria-busy={busy || undefined}
      role={busy ? 'status' : 'alert'}
    >
      <Icon />
      <h1>{t(`tenantOverview.state.${model.state}.title`)}</h1>
      <p>{t(`tenantOverview.state.${model.state}.description`)}</p>
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
