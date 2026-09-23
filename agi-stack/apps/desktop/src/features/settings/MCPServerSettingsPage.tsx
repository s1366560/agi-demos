import { useState } from 'react';
import { ComponentInstanceIcon, MagnifyingGlassIcon, ReloadIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import { SettingsPage } from './SettingsCorePages';
import { SettingsState } from './ManagedResourceViews';
import type { useMCPServerManagement } from './useMCPServerManagement';
import './MCPServerSettingsPage.css';

export function MCPServerSettingsPage({
  management,
  canManage,
}: {
  management: ReturnType<typeof useMCPServerManagement>;
  canManage: boolean;
}) {
  const { t } = useI18n();
  const [query, setQuery] = useState('');
  const servers = management.servers.filter((server) =>
    `${server.name} ${server.project_id} ${server.server_type}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
  );
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
      <label className="mcp-server-search">
        <MagnifyingGlassIcon aria-hidden="true" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t('settings.searchResources', { resource: t('settings.mcp') })}
          aria-label={t('settings.searchResources', { resource: t('settings.mcp') })}
        />
      </label>
      {management.loading ? (
        <SettingsState text={t('settings.mcpServers.loading')} />
      ) : management.error ? (
        <SettingsState error text={management.error} />
      ) : management.servers.length === 0 ? (
        <SettingsState text={t('settings.mcpServers.empty')} />
      ) : (
        <section className="settings-panel settings-rows mcp-server-list">
          {management.actionMessage ? (
            <div className="settings-state">
              {management.actionMessage.startsWith('settings.mcpServers.testSucceeded:')
                ? t('settings.mcpServers.testSucceeded', {
                    count: management.actionMessage.split(':')[1],
                  })
                : t(management.actionMessage)}
            </div>
          ) : null}
          {servers.length === 0 ? <SettingsState text={t('settings.noMatches')} /> : null}
          {servers.map((server) => (
            <article className="settings-row mcp-server-row" key={server.id}>
              <div>
                <strong>{server.name}</strong>
                <small>
                  {t(`settings.mcpServers.transports.${server.server_type}`)} · {server.project_id}
                </small>
              </div>
              <div className="mcp-server-status">
                <strong>{t('settings.mcpServers.status')}</strong>
                <small>{t(`settings.mcpServers.runtime.${!server.enabled ? 'disabled' : server.runtime_status === 'healthy' ? 'connected' : server.runtime_status === 'starting' ? 'connecting' : server.runtime_status === 'stopped' ? 'disconnected' : ['connected', 'connecting', 'disconnected', 'disabled', 'error'].includes(server.runtime_status) ? server.runtime_status : 'unknown'}`)}</small>
                {server.runtime_metadata?.reason_code ? (
                  <details><summary>{t('settings.mcpServers.diagnostics')}</summary><code>{server.runtime_metadata.reason_code}</code></details>
                ) : null}
              </div>
              <div className="mcp-server-actions">
                <button
                  type="button"
                  className="secondary"
                  disabled={!canManage || management.actionBusyId !== null}
                  onClick={() => management.openEdit(server)}
                >
                  {t('common.edit')}
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={!canManage || management.actionBusyId !== null}
                  onClick={() => void management.toggleServer(server)}
                >
                  {management.actionBusyId === server.id ? (
                    <ReloadIcon className="managed-resource-spin" />
                  ) : null}
                  {t(server.enabled ? 'settings.disable' : 'settings.enable')}
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={!canManage || !server.enabled || management.actionBusyId !== null}
                  onClick={() => void management.testServer(server.id)}
                >
                  {management.actionBusyId === server.id ? (
                    <ReloadIcon className="managed-resource-spin" />
                  ) : null}
                  {t(
                    server.runtime_status === 'error'
                      ? 'settings.mcpServers.retry'
                      : 'settings.mcpServers.test',
                  )}
                </button>
              </div>
            </article>
          ))}
        </section>
      )}
    </SettingsPage>
  );
}
