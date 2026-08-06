import { useI18n } from '../../i18n';
import type { TenantPatternsController } from './tenantPatternsController';
import type { TenantPatternsViewModel } from './tenantPatternsPresentationModel';
import { TenantAdminDegradedNotice, TenantAdminRouteState } from './TenantAdminRouteState';

export function TenantPatternsPage({
  model,
  controller,
  onRetry,
}: Readonly<{
  model: TenantPatternsViewModel;
  controller: TenantPatternsController | null;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  if (!['ready', 'degraded', 'empty', 'stale'].includes(model.state)) {
    return (
      <TenantAdminRouteState
        state={model.state}
        reasonCode={model.reasonCode}
        retryVisible={model.retryVisible}
        onRetry={onRetry}
      />
    );
  }
  return (
    <section data-tenant-management-route="patterns" data-state={model.state}>
      <header>
        <h1>{t('tenantAdmin.patterns.title')}</h1>
        <p>{t('tenantAdmin.patterns.subtitle')}</p>
        <code>{model.scope.tenantId}</code>
      </header>
      <TenantAdminDegradedNotice reasonCode={model.reasonCode} />
      <button type="button" onClick={onRetry} disabled={Boolean(model.busyAction)}>
        {t('common.refresh')}
      </button>
      <p>{t('tenantAdmin.total', { count: model.total })}</p>
      <ul>
        {model.patterns.map((pattern) => (
          <li key={pattern.id}>
            <strong>{pattern.name}</strong>
            <span>{pattern.description}</span>
            <span>{pattern.successRate}</span>
            {controller && model.allowedActions.includes('delete') ? (
              <button
                type="button"
                disabled={Boolean(model.busyAction)}
                onClick={() => {
                  void controller.deletePattern(pattern.id).catch(() => undefined);
                }}
              >
                {t('common.delete')}
              </button>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
