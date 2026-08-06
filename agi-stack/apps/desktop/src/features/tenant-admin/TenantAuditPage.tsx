import { useEffect, useState } from 'react';

import { useI18n } from '../../i18n';
import type { TenantAuditController } from './tenantAuditController';
import type { TenantAuditViewModel } from './tenantAuditPresentationModel';
import { TenantAdminDegradedNotice, TenantAdminRouteState } from './TenantAdminRouteState';

export function TenantAuditPage({
  model,
  controller,
  onRetry,
}: Readonly<{
  model: TenantAuditViewModel;
  controller: TenantAuditController | null;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  const [action, setAction] = useState(model.query.action ?? '');
  const [resourceType, setResourceType] = useState(model.query.resourceType ?? '');
  const [actor, setActor] = useState(model.query.actor ?? '');
  useEffect(() => {
    setAction(model.query.action ?? '');
    setResourceType(model.query.resourceType ?? '');
    setActor(model.query.actor ?? '');
  }, [model.query.action, model.query.actor, model.query.resourceType]);
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
    <section data-tenant-admin-route="audit" data-state={model.state}>
      <header>
        <h1>{t('tenantAdmin.audit.title')}</h1>
        <p>{t('tenantAdmin.audit.subtitle')}</p>
      </header>
      <TenantAdminDegradedNotice reasonCode={model.reasonCode} />
      {controller ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void controller
              .setQuery({
                action: action.trim(),
                resourceType: resourceType.trim(),
                actor: actor.trim(),
                limit: model.limit,
                offset: 0,
              })
              .catch(() => undefined);
          }}
        >
          <label>
            <span>{t('tenantAdmin.audit.action')}</span>
            <input value={action} onChange={(event) => setAction(event.target.value)} />
          </label>
          <label>
            <span>{t('tenantAdmin.audit.resourceType')}</span>
            <input value={resourceType} onChange={(event) => setResourceType(event.target.value)} />
          </label>
          <label>
            <span>{t('tenantAdmin.audit.actor')}</span>
            <input value={actor} onChange={(event) => setActor(event.target.value)} />
          </label>
          <button type="submit">{t('tenantAdmin.audit.applyFilters')}</button>
        </form>
      ) : null}
      <section>
        <h2>{t('tenantAdmin.audit.runtimeHooks')}</h2>
        <strong>{model.runtimeSummary?.total ?? 0}</strong>
      </section>
      <section>
        <h2>{t('tenantAdmin.audit.entries')}</h2>
        <table>
          <tbody>
            {model.entries.map((entry) => (
              <tr key={entry.id}>
                <td>{entry.timestamp}</td>
                <td>{entry.actorName ?? entry.actor}</td>
                <td>{entry.action}</td>
                <td>{entry.resourceType}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {controller ? (
          <nav>
            <button
              type="button"
              disabled={model.offset === 0}
              onClick={() =>
                void controller
                  .setQuery({
                    ...model.query,
                    offset: Math.max(0, model.offset - model.limit),
                  })
                  .catch(() => undefined)
              }
            >
              {t('tenantAdmin.audit.previous')}
            </button>
            <button
              type="button"
              disabled={model.offset + model.limit >= model.total}
              onClick={() =>
                void controller
                  .setQuery({
                    ...model.query,
                    offset: model.offset + model.limit,
                  })
                  .catch(() => undefined)
              }
            >
              {t('tenantAdmin.audit.next')}
            </button>
          </nav>
        ) : null}
      </section>
    </section>
  );
}
