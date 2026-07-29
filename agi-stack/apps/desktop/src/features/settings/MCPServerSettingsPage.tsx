import { ComponentInstanceIcon, ReloadIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import { SettingsPage } from './SettingsCorePages';
import { SettingsState } from './ManagedResourceViews';
import type { useMCPServerManagement } from './useMCPServerManagement';

export function MCPServerSettingsPage({
  management,
  canManage,
}: {
  management: ReturnType<typeof useMCPServerManagement>;
  canManage: boolean;
}) {
  const { t } = useI18n();
  return (
    <SettingsPage
      eyebrow={t('settings.aiResources')}
      title={t('settings.mcpServers.title')}
      description={t('settings.mcpServers.subtitle')}
      action={
        <>
          <button
            type="button"
            className="secondary"
            disabled={management.loading}
            onClick={() => void management.reload()}
          >
            {management.loading ? <ReloadIcon className="managed-resource-spin" /> : null}
            {t('settings.mcpServers.refresh')}
          </button>
          <button type="button" className="primary" disabled={!canManage} onClick={management.openCreate}>
            <ComponentInstanceIcon />
            {t('settings.mcpServers.create')}
          </button>
        </>
      }
    >
      {management.loading ? (
        <SettingsState text={t('settings.mcpServers.loading')} />
      ) : management.error ? (
        <SettingsState error text={management.error} />
      ) : management.servers.length === 0 ? (
        <SettingsState text={t('settings.mcpServers.empty')} />
      ) : (
        <section className="settings-panel settings-rows">
          {management.servers.map((server) => (
            <article className="settings-row" key={server.id}>
              <div>
                <strong>{server.name}</strong>
                <small>
                  {t(`settings.mcpServers.transports.${server.server_type}`)} · {server.project_id}
                </small>
              </div>
              <div>
                <strong>{t('settings.mcpServers.status')}</strong>
                <small>{server.enabled ? server.runtime_status : 'disabled'}</small>
              </div>
            </article>
          ))}
        </section>
      )}
    </SettingsPage>
  );
}
