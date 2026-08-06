import { useState } from 'react';

import { useI18n } from '../../i18n';
import type { TenantTrustController } from './tenantTrustController';
import type { TenantTrustGrantType } from './tenantTrustClient';
import type { TenantTrustViewModel } from './tenantTrustPresentationModel';
import { TenantAdminRouteState } from './TenantAdminRouteState';

export function TenantTrustPage({
  model,
  controller,
  onRetry,
}: Readonly<{
  model: TenantTrustViewModel;
  controller: TenantTrustController | null;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  const [agentInstanceId, setAgentInstanceId] = useState('');
  const [actionType, setActionType] = useState('');
  const [grantType, setGrantType] = useState<TenantTrustGrantType>('once');
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
    <section data-tenant-admin-route="trust" data-state={model.state}>
      <header>
        <h1>{t('tenantAdmin.trust.title')}</h1>
        <p>{t('tenantAdmin.trust.subtitle')}</p>
      </header>
      <dl>
        <dt>{t('tenantAdmin.trust.workspace')}</dt>
        <dd>
          <code>{model.scope.workspaceId}</code>
        </dd>
      </dl>
      {controller && model.allowedActions.includes('create') ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!agentInstanceId.trim() || !actionType.trim()) return;
            void controller
              .create({
                agentInstanceId: agentInstanceId.trim(),
                actionType: actionType.trim(),
                grantType,
              })
              .then(() => {
                setAgentInstanceId('');
                setActionType('');
              })
              .catch(() => undefined);
          }}
        >
          <label>
            <span>{t('tenantAdmin.trust.agent')}</span>
            <input
              value={agentInstanceId}
              onChange={(event) => setAgentInstanceId(event.target.value)}
            />
          </label>
          <label>
            <span>{t('tenantAdmin.trust.action')}</span>
            <input value={actionType} onChange={(event) => setActionType(event.target.value)} />
          </label>
          <label>
            <span>{t('tenantAdmin.trust.grant')}</span>
            <select
              value={grantType}
              onChange={(event) => setGrantType(event.target.value as TenantTrustGrantType)}
            >
              <option value="once">{t('tenantAdmin.grant.once')}</option>
              <option value="always">{t('tenantAdmin.grant.always')}</option>
            </select>
          </label>
          <button type="submit" disabled={Boolean(model.busyAction)}>
            {t('tenantAdmin.trust.create')}
          </button>
        </form>
      ) : null}
      <table>
        <tbody>
          {model.policies.map((policy) => (
            <tr key={policy.id}>
              <td>
                <code>{policy.actionType}</code>
              </td>
              <td>{policy.agentInstanceId}</td>
              <td>{t(`tenantAdmin.grant.${policy.grantType}`)}</td>
              <td>
                {controller && model.allowedActions.includes('revoke') ? (
                  <button
                    type="button"
                    onClick={() => void controller.revoke(policy.id).catch(() => undefined)}
                  >
                    {t('tenantAdmin.trust.revoke')}
                  </button>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
