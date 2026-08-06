import { useState } from 'react';

import { useI18n } from '../../i18n';
import type { TenantOrganizationSettingsController } from './tenantOrganizationSettingsController';
import type { TenantOrganizationSettingsViewModel } from './tenantOrganizationSettingsPresentationModel';
import { TenantAdminDegradedNotice, TenantAdminRouteState } from './TenantAdminRouteState';

export function TenantOrganizationSettingsPage({
  model,
  controller,
  onRetry,
}: Readonly<{
  model: TenantOrganizationSettingsViewModel;
  controller: TenantOrganizationSettingsController | null;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  const [registryName, setRegistryName] = useState('');
  const [registryType, setRegistryType] = useState('docker');
  const [registryUrl, setRegistryUrl] = useState('');
  const [smtpHost, setSmtpHost] = useState('');
  const [smtpUsername, setSmtpUsername] = useState('');
  const [smtpPassword, setSmtpPassword] = useState('');
  const [fromEmail, setFromEmail] = useState('');
  const [recipientEmail, setRecipientEmail] = useState('');
  const [policyKey, setPolicyKey] = useState('');
  const [policyJson, setPolicyJson] = useState('{}');
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
    <section data-tenant-management-route="organization-settings" data-state={model.state}>
      <header>
        <h1>{t('tenantAdmin.organization.title')}</h1>
        <p>{t('tenantAdmin.organization.subtitle')}</p>
        <strong>{model.tenant?.name}</strong>
      </header>
      <TenantAdminDegradedNotice reasonCode={model.reasonCode} />
      <button type="button" onClick={onRetry}>{t('common.refresh')}</button>
      <pre>{JSON.stringify(model.stats, null, 2)}</pre>

      <section>
        <h2>{t('tenantAdmin.organization.registries')}</h2>
        {controller && model.allowedActions.includes('manage-registries') ? (
          <form onSubmit={(event) => {
            event.preventDefault();
            if (!registryName.trim() || !registryType.trim() || !registryUrl.trim()) return;
            void controller.saveRegistry({
              name: registryName.trim(),
              registryType: registryType.trim(),
              url: registryUrl.trim(),
            }).catch(() => undefined);
          }}>
            <input aria-label={t('tenantAdmin.organization.registryName')} value={registryName} onChange={(event) => setRegistryName(event.target.value)} />
            <input aria-label={t('tenantAdmin.organization.registryType')} value={registryType} onChange={(event) => setRegistryType(event.target.value)} />
            <input aria-label={t('tenantAdmin.organization.registryUrl')} value={registryUrl} onChange={(event) => setRegistryUrl(event.target.value)} />
            <button type="submit">{t('common.create')}</button>
          </form>
        ) : null}
        <ul>{model.registries.map((registry) => <li key={registry.id}>
          <strong>{registry.name}</strong> <code>{registry.url}</code>
          {controller && model.allowedActions.includes('manage-registries') ? <span>
            <button type="button" onClick={() => void controller.saveRegistry({
              id: registry.id,
              name: registry.name,
              registryType: registry.type,
              url: registry.url,
              username: registry.username,
              isDefault: registry.isDefault,
            }).catch(() => undefined)}>{t('common.edit')}</button>
            <button type="button" onClick={() => void controller.testRegistry(registry.id).catch(() => undefined)}>{t('tenantAdmin.organization.test')}</button>
            <button type="button" onClick={() => void controller.deleteRegistry(registry.id).catch(() => undefined)}>{t('common.delete')}</button>
          </span> : null}
        </li>)}</ul>
      </section>

      <section>
        <h2>{t('tenantAdmin.organization.smtp')}</h2>
        {controller && model.allowedActions.includes('update-smtp') ? <form onSubmit={(event) => {
          event.preventDefault();
          if (!smtpHost.trim() || !smtpUsername.trim() || !smtpPassword || !fromEmail.trim()) return;
          void controller.saveSmtp({
            smtpHost: smtpHost.trim(),
            smtpPort: 587,
            smtpUsername: smtpUsername.trim(),
            smtpPassword,
            fromEmail: fromEmail.trim(),
            useTls: true,
          }).then(() => setSmtpPassword('')).catch(() => undefined);
        }}>
          <input aria-label={t('tenantAdmin.organization.smtpHost')} value={smtpHost} onChange={(event) => setSmtpHost(event.target.value)} />
          <input aria-label={t('tenantAdmin.organization.smtpUsername')} value={smtpUsername} onChange={(event) => setSmtpUsername(event.target.value)} />
          <input aria-label={t('tenantAdmin.organization.smtpPassword')} type="password" value={smtpPassword} onChange={(event) => setSmtpPassword(event.target.value)} />
          <input aria-label={t('tenantAdmin.organization.fromEmail')} value={fromEmail} onChange={(event) => setFromEmail(event.target.value)} />
          <button type="submit">{t('common.save')}</button>
        </form> : null}
        {model.smtp ? <p><code>{model.smtp.smtpHost}</code> {model.smtp.smtpPasswordMasked}</p> : null}
        {controller && model.allowedActions.includes('test-smtp') ? <span>
          <input aria-label={t('tenantAdmin.organization.recipientEmail')} value={recipientEmail} onChange={(event) => setRecipientEmail(event.target.value)} />
          <button type="button" onClick={() => void controller.testSmtp(recipientEmail.trim()).catch(() => undefined)}>{t('tenantAdmin.organization.test')}</button>
        </span> : null}
        {controller && model.allowedActions.includes('delete-smtp') && model.smtp ? <button type="button" onClick={() => void controller.deleteSmtp().catch(() => undefined)}>{t('common.delete')}</button> : null}
      </section>

      <section>
        <h2>{t('tenantAdmin.organization.genePolicies')}</h2>
        {controller && model.allowedActions.includes('manage-gene-policies') ? <form onSubmit={(event) => {
          event.preventDefault();
          try {
            const value = JSON.parse(policyJson) as unknown;
            if (!value || typeof value !== 'object' || Array.isArray(value)) return;
            void controller.saveGenePolicy({ policyKey: policyKey.trim(), policyValue: value as Record<string, unknown> }).catch(() => undefined);
          } catch {
            return;
          }
        }}>
          <input aria-label={t('tenantAdmin.organization.policyKey')} value={policyKey} onChange={(event) => setPolicyKey(event.target.value)} />
          <textarea aria-label={t('tenantAdmin.organization.policyValue')} value={policyJson} onChange={(event) => setPolicyJson(event.target.value)} />
          <button type="submit">{t('common.save')}</button>
        </form> : null}
        <ul>{model.genePolicies.map((policy) => <li key={policy.id}>
          <strong>{policy.policyKey}</strong><pre>{JSON.stringify(policy.policyValue, null, 2)}</pre>
          {controller && model.allowedActions.includes('manage-gene-policies') ? <button type="button" onClick={() => void controller.deleteGenePolicy(policy.policyKey).catch(() => undefined)}>{t('common.delete')}</button> : null}
        </li>)}</ul>
      </section>
    </section>
  );
}
