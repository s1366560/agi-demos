import { useState } from 'react';

import { useI18n } from '../../i18n';
import type { TenantAcpController } from './tenantAcpController';
import type { TenantAcpTransport } from './tenantAcpClient';
import type { TenantAcpViewModel } from './tenantAcpPresentationModel';
import { TenantAdminDegradedNotice, TenantAdminRouteState } from './TenantAdminRouteState';

export function TenantAcpPage({
  model,
  controller,
  onRetry,
}: Readonly<{
  model: TenantAcpViewModel;
  controller: TenantAcpController | null;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  const [agentKey, setAgentKey] = useState('');
  const [name, setName] = useState('');
  const [transport, setTransport] = useState<TenantAcpTransport>('stdio');
  const [endpoint, setEndpoint] = useState('');
  const [testCwd, setTestCwd] = useState('');
  const [testPrompt, setTestPrompt] = useState('');
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
  const input = {
    name: name.trim(),
    transport,
    command: transport === 'stdio' ? endpoint.trim() || null : null,
    url: transport === 'websocket' ? endpoint.trim() || null : null,
  } as const;
  return (
    <section data-tenant-management-route="acp" data-state={model.state}>
      <header>
        <h1>{t('tenantAdmin.acp.title')}</h1>
        <p>{t('tenantAdmin.acp.subtitle')}</p>
        <code>{model.scope.tenantId}</code>
      </header>
      <TenantAdminDegradedNotice reasonCode={model.reasonCode} />
      <button type="button" onClick={onRetry}>{t('common.refresh')}</button>
      {controller && model.allowedActions.includes('create-agent') ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!agentKey.trim() || !name.trim()) return;
            const createAgent = controller.createAgent;
            void createAgent({ ...input, agentKey: agentKey.trim() }).catch(() => undefined);
          }}
        >
          <input
            aria-label={t('tenantAdmin.acp.agentKey')}
            value={agentKey}
            onChange={(event) => setAgentKey(event.target.value)}
          />
          <input
            aria-label={t('tenantAdmin.acp.name')}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <select
            aria-label={t('tenantAdmin.acp.transport')}
            className="tenant-acp-transport"
            value={transport}
            onChange={(event) => setTransport(event.target.value as TenantAcpTransport)}
          >
            <option value="stdio">{t('tenantAdmin.acp.transportStdio')}</option>
            <option value="websocket">{t('tenantAdmin.acp.transportWebsocket')}</option>
          </select>
          <input
            aria-label={t('tenantAdmin.acp.endpoint')}
            value={endpoint}
            onChange={(event) => setEndpoint(event.target.value)}
          />
          <button type="submit" disabled={Boolean(model.busyAction)}>{t('common.create')}</button>
        </form>
      ) : null}
      {controller && model.allowedActions.includes('test-agent') ? (
        <fieldset>
          <legend>{t('tenantAdmin.acp.test')}</legend>
          <input
            aria-label={t('tenantAdmin.acp.testCwd')}
            value={testCwd}
            onChange={(event) => setTestCwd(event.target.value)}
          />
          <input
            aria-label={t('tenantAdmin.acp.testPrompt')}
            value={testPrompt}
            onChange={(event) => setTestPrompt(event.target.value)}
          />
        </fieldset>
      ) : null}
      <ul>
        {model.agents.map((agent) => (
          <li key={agent.id}>
            <strong>{agent.name}</strong> <code>{agent.agentKey}</code>
            {controller && model.allowedActions.includes('update-agent') ? (
              <button type="button" onClick={() => void controller.updateAgent(agent.agentKey, {
                name: agent.name,
                transport: agent.transport,
                command: agent.command,
                url: agent.url,
                enabled: !agent.enabled,
              }).catch(() => undefined)}>{t('common.edit')}</button>
            ) : null}
            {controller && model.allowedActions.includes('test-agent') ? (
              <button type="button" onClick={() => void controller.testAgent(agent.agentKey, {
                cwd: testCwd,
                prompt: testPrompt,
                timeoutSeconds: 30,
              }).catch(() => undefined)} disabled={!testCwd.trim() || !testPrompt.trim()}>
                {t('tenantAdmin.acp.test')}
              </button>
            ) : null}
            {controller && model.allowedActions.includes('delete-agent') ? (
              <button
                type="button"
                onClick={() =>
                  void controller.deleteAgent(agent.agentKey).catch(() => undefined)
                }
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
