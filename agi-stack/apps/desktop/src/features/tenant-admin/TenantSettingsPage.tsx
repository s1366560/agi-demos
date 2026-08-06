import { useEffect, useState } from 'react';

import { useI18n } from '../../i18n';
import type { TenantSettingsController } from './tenantSettingsController';
import type { TenantSettingsViewModel } from './tenantSettingsPresentationModel';
import { TenantAdminDegradedNotice, TenantAdminRouteState } from './TenantAdminRouteState';

export function TenantSettingsPage({
  model,
  controller,
  onRetry,
}: Readonly<{
  model: TenantSettingsViewModel;
  controller: TenantSettingsController | null;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);
  useEffect(() => {
    setName(model.tenant?.name ?? '');
    setDescription(model.tenant?.description ?? '');
  }, [model.tenant?.id, model.tenant?.name, model.tenant?.description]);
  if (!['ready', 'degraded', 'empty', 'stale'].includes(model.state)) {
    return <TenantAdminRouteState state={model.state} reasonCode={model.reasonCode} retryVisible={model.retryVisible} onRetry={onRetry} />;
  }
  return (
    <section data-tenant-management-route="settings" data-state={model.state}>
      <header><h1>{t('tenantAdmin.settings.title')}</h1><p>{t('tenantAdmin.settings.subtitle')}</p></header>
      <TenantAdminDegradedNotice reasonCode={model.reasonCode} />
      <button type="button" onClick={onRetry}>{t('common.refresh')}</button>
      {controller && model.allowedActions.includes('update') ? <form onSubmit={(event) => {
        event.preventDefault();
        void controller.updateTenant({ name: name.trim(), description: description.trim() || null }).catch(() => undefined);
      }}>
        <label><span>{t('tenantAdmin.settings.name')}</span><input value={name} onChange={(event) => setName(event.target.value)} /></label>
        <label><span>{t('tenantAdmin.settings.description')}</span><textarea value={description} onChange={(event) => setDescription(event.target.value)} /></label>
        <button type="submit" disabled={!name.trim() || Boolean(model.busyAction)}>{t('common.save')}</button>
      </form> : null}
      <pre>{JSON.stringify(model.stats, null, 2)}</pre>
      {controller && model.allowedActions.includes('delete') ? confirmDelete ? <span>
        <button type="button" onClick={() => void controller.deleteTenant().catch(() => undefined)}>{t('common.delete')}</button>
        <button type="button" onClick={() => setConfirmDelete(false)}>{t('common.cancel')}</button>
      </span> : <button type="button" onClick={() => setConfirmDelete(true)}>{t('tenantAdmin.settings.deleteTenant')}</button> : null}
    </section>
  );
}
