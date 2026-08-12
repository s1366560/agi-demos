import { useI18n } from '../../i18n';
import type { TenantAdminViewState } from './tenantAdminController';

export function TenantAdminRouteState({
  state,
  reasonCode,
  retryVisible,
  onRetry,
}: Readonly<{
  state: TenantAdminViewState;
  reasonCode: string | null;
  retryVisible: boolean;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  const normalizedState = state === 'ready' || state === 'degraded' ? 'loading' : state;
  const role = ['forbidden', 'conflict', 'unavailable', 'error'].includes(state)
    ? 'alert'
    : 'status';
  return (
    <section data-tenant-admin-state={state} data-state={state} role={role}>
      <h1>{t(`tenantAdmin.state.${normalizedState}.title`)}</h1>
      <p>{t(`tenantAdmin.state.${normalizedState}.description`)}</p>
      {reasonCode ? <code>{reasonCode}</code> : null}
      {retryVisible ? (
        <button type="button" onClick={onRetry}>
          {t('common.retry')}
        </button>
      ) : null}
    </section>
  );
}

export function TenantAdminDegradedNotice({ reasonCode }: Readonly<{ reasonCode: string | null }>) {
  const { t } = useI18n();
  if (!reasonCode) return null;
  return (
    <aside role="status">
      <span>{t('tenantAdmin.degraded')}</span> <code>{reasonCode}</code>
    </aside>
  );
}
