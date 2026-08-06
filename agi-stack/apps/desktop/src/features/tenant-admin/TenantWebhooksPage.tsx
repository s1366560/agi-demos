import { useState } from 'react';

import { useI18n } from '../../i18n';
import type { TenantWebhooksController } from './tenantWebhooksController';
import type { TenantWebhooksViewModel } from './tenantWebhooksPresentationModel';
import { TenantAdminDegradedNotice, TenantAdminRouteState } from './TenantAdminRouteState';

export function TenantWebhooksPage({
  model,
  controller,
  onRetry,
}: Readonly<{
  model: TenantWebhooksViewModel;
  controller: TenantWebhooksController | null;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [eventType, setEventType] = useState('');
  const [createdSecret, setCreatedSecret] = useState<string | null>(null);
  if (!['ready', 'degraded', 'empty', 'stale'].includes(model.state)) {
    return <TenantAdminRouteState state={model.state} reasonCode={model.reasonCode} retryVisible={model.retryVisible} onRetry={onRetry} />;
  }
  return (
    <section data-tenant-management-route="webhooks" data-state={model.state}>
      <header><h1>{t('tenantAdmin.webhooks.title')}</h1><p>{t('tenantAdmin.webhooks.subtitle')}</p></header>
      <TenantAdminDegradedNotice reasonCode={model.reasonCode} />
      <button type="button" onClick={onRetry}>{t('common.refresh')}</button>
      {controller && model.allowedActions.includes('create') ? (
        <form onSubmit={(event) => {
          event.preventDefault();
          if (!name.trim() || !url.trim() || !eventType) return;
          void controller.createWebhook({ name: name.trim(), url: url.trim(), events: [eventType], isActive: true }).then((created) => setCreatedSecret(created.secret)).catch(() => undefined);
        }}>
          <input aria-label={t('tenantAdmin.webhooks.name')} value={name} onChange={(event) => setName(event.target.value)} />
          <input aria-label={t('tenantAdmin.webhooks.url')} value={url} onChange={(event) => setUrl(event.target.value)} />
          <select value={eventType} onChange={(event) => setEventType(event.target.value)}>
            <option value="">{t('tenantAdmin.webhooks.selectEvent')}</option>
            {model.eventTypes.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
          <button type="submit">{t('common.create')}</button>
        </form>
      ) : null}
      {createdSecret && controller && model.allowedActions.includes('copy-secret') ? (
        <button type="button" onClick={() => void controller.copySecret(createdSecret).catch(() => undefined)}>{t('tenantAdmin.webhooks.copySecret')}</button>
      ) : null}
      <ul>
        {model.webhooks.map((webhook) => <li key={webhook.id}>
          <strong>{webhook.name}</strong> <code>{webhook.url}</code>
          {controller && model.allowedActions.includes('update') ? <button type="button" onClick={() => void controller.updateWebhook(webhook.id, { name: webhook.name, url: webhook.url, events: webhook.events, isActive: !webhook.isActive }).catch(() => undefined)}>{t('common.edit')}</button> : null}
          {controller && model.allowedActions.includes('delete') ? <button type="button" onClick={() => void controller.deleteWebhook(webhook.id).catch(() => undefined)}>{t('common.delete')}</button> : null}
        </li>)}
      </ul>
    </section>
  );
}
