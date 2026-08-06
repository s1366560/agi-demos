import { useState } from 'react';

import { useI18n } from '../../i18n';
import type { TenantEventsController } from './tenantEventsController';
import type { TenantEventsViewModel } from './tenantEventsPresentationModel';
import { TenantAdminDegradedNotice, TenantAdminRouteState } from './TenantAdminRouteState';

export function TenantEventsPage({
  model,
  controller,
  onRetry,
}: Readonly<{
  model: TenantEventsViewModel;
  controller: TenantEventsController | null;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  const [eventType, setEventType] = useState('');
  if (!['ready', 'degraded', 'empty', 'stale'].includes(model.state)) {
    return <TenantAdminRouteState state={model.state} reasonCode={model.reasonCode} retryVisible={model.retryVisible} onRetry={onRetry} />;
  }
  return (
    <section data-tenant-management-route="events" data-state={model.state}>
      <header><h1>{t('tenantAdmin.events.title')}</h1><p>{t('tenantAdmin.events.subtitle')}</p></header>
      <TenantAdminDegradedNotice reasonCode={model.reasonCode} />
      <form onSubmit={(event) => {
        event.preventDefault();
        void controller?.setFilters({ eventType: eventType || undefined, page: 1, pageSize: model.pageSize }).catch(() => undefined);
      }}>
        <select value={eventType} onChange={(event) => setEventType(event.target.value)}>
          <option value="">{t('tenantAdmin.events.allTypes')}</option>
          {model.eventTypes.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <button type="submit">{t('tenantAdmin.audit.applyFilters')}</button>
      </form>
      <button type="button" onClick={onRetry}>{t('common.refresh')}</button>
      <ul>{model.events.map((event) => <li key={event.id}><strong>{event.eventType}</strong><span>{event.message}</span><time>{event.createdAt}</time></li>)}</ul>
      <nav>
        <button type="button" disabled={!controller || model.page <= 1} onClick={() => void controller?.setPage(model.page - 1).catch(() => undefined)}>{t('tenantAdmin.audit.previous')}</button>
        <button type="button" disabled={!controller || model.page * model.pageSize >= model.total} onClick={() => void controller?.setPage(model.page + 1).catch(() => undefined)}>{t('tenantAdmin.audit.next')}</button>
      </nav>
    </section>
  );
}
