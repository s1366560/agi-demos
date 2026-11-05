import { AudioSessionsPanel } from './AudioSessionsPanel';
import { useI18n } from '../../i18n';
import { useComputerUseDevice } from './ComputerUseDeviceProvider';
import './ComputerUseSettingsPage.css';
import { ComputerUseTargetPreview } from './ComputerUseTargetPreview';
import { ComputerUseRecordings } from './ComputerUseRecordings';
import { ComputerUseInputModeControl } from './ComputerUseInputModeControl';
import { ComputerUseLockedUse } from './ComputerUseLockedUse';

export function ComputerUseSettingsPage() {
  const { t } = useI18n();
  const { snapshot, manage, error, busy, stopping, mode, client, audioClient } = useComputerUseDevice();
  const [provider, setProvider] = useState<'google' | 'microsoft365'>('google');
  const [clientId, setClientId] = useState('');
  if (!snapshot)
    return (
      <section className="settings-panel computer-use-settings">
        <h3>{t('cua.title')}</h3>
        <p role={error ? 'alert' : 'status'}>{t(error ? 'cua.unavailable' : 'cua.loading')}</p>
      </section>
    );
  const instance = snapshot.instance;
  const revision = instance.revision;
  return (
    <section className="settings-panel computer-use-settings">
      <h3>
        {t('cua.title')} <code>memstack-computer-use</code>
      </h3>
      <p role="status">
        {t(
          !instance.installed
            ? 'cua.instance.uninstalled'
            : instance.enabled
              ? 'cua.instance.enabled'
              : 'cua.instance.disabled'
        )}
      </p>
      <p>{t('cua.description')}</p>
      <AudioSessionsPanel client={audioClient} />
      <ComputerUseInputModeControl snapshot={snapshot} busy={busy} manage={manage} />
      <ComputerUseRecordings recordings={snapshot.recordings ?? []} client={client}
        manage={manage} stopping={stopping} />
      {snapshot.recent_presentation ? (
        <ComputerUseTargetPreview
          presentation={snapshot.recent_presentation}
          client={client}
          recent
        />
      ) : null}
      {mode === 'cloud' && snapshot.execution?.cloud === false ? (
        <p role="status">{t('cua.cloudExecutionUnavailable')}</p>
      ) : null}
      {error ? (
        <p role="alert">
          {t('cua.error')} <code>{error}</code>
        </p>
      ) : null}
      {!snapshot.helper_available ? <p role="status">{t('cua.unavailable')}</p> : null}
      <div className="computer-use-actions">
        {instance.installed ? (
          <>
            <button
              type="button"
              disabled={busy || (!instance.enabled && !snapshot.helper_available)}
              onClick={() =>
                void manage({
                  action: instance.enabled ? 'disable' : 'enable',
                  expected_revision: revision,
                })
              }
            >
              {t(instance.enabled ? 'cua.disable' : 'cua.enable')}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                void manage({
                  action: 'uninstall',
                  expected_revision: revision,
                })
              }
            >
              {t('cua.uninstall')}
            </button>
          </>
        ) : (
          <button
            type="button"
            disabled={busy}
            onClick={() => void manage({ action: 'install', expected_revision: revision })}
          >
            {t('cua.install')}
          </button>
        )}
        <button
          type="button"
          disabled={stopping || !snapshot.sessions.length}
          onClick={() => void manage({ action: 'stop_all' })}
        >
          {t('cua.stop')}
        </button>
      </div>
      <fieldset disabled={busy || !instance.installed}>
        <legend>{t('cua.separatePermissions')}</legend>
        {(['microphone', 'system_audio', 'locked_use'] as const).map((capability) => (
          <label key={capability}>
            <input
              type="checkbox"
              checked={instance[capability]}
              onChange={(event) =>
                void manage({
                  action: 'configure',
                  expected_revision: revision,
                  capability,
                  enabled: event.target.checked,
                })
              }
            />
            {t(`cua.capability.${capability}`)}
          </label>
        ))}
      </fieldset>
      <p>{t('cua.permissionDescription')}</p>
      <ComputerUseLockedUse snapshot={snapshot} busy={busy} manage={manage} />
      <h4>{t('cua.systemPermissions')}</h4>
      <button
        type="button"
        disabled={busy || !snapshot.helper_available}
        onClick={() => void manage({ action: 'permissions_status' })}
      >
        {t('cua.checkPermissions')}
      </button>
      {snapshot.permissions ? (
        <ul>
          {(
            [
              'accessibility',
              'input_monitoring',
              'screen_capture',
              'microphone',
              'system_audio',
              'calendar',
              'contacts',
              'messages',
              'locked_use',
            ] as const
          ).map((capability) => {
            const permission = snapshot.permissions?.[capability];
            return permission ? (
              <li key={capability}>
                <span>
                  {t(`cua.capability.${capability}`)} · {t(`cua.permission.${permission.state}`)}
                </span>
                {capability !== 'locked_use' &&
                permission.state !== 'granted' &&
                permission.state !== 'unavailable' ? (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void manage({ action: 'permission_request', capability })}
                  >
                    {t('cua.requestPermission')}
                  </button>
                ) : null}
              </li>
            ) : null;
          })}
        </ul>
      ) : null}
      <h4>{t('cua.grants')}</h4>
      {!snapshot.grants.length ? (
        <p>{t('cua.noGrants')}</p>
      ) : (
        <ul>
          {snapshot.grants.map((grant) => (
            <li key={grant.id}>
              <span>
                {grant.app} · {t(`cua.capability.${grant.capability}`)} ·{' '}
                {t(`cua.scope.${grant.scope}`)}
              </span>
              <button
                type="button"
                disabled={busy}
                onClick={() => void manage({ action: 'revoke', grant_id: grant.id })}
              >
                {t('cua.revoke')}
              </button>
            </li>
          ))}
        </ul>
      )}
      <h4>{t('cua.connectors')}</h4>
      <fieldset disabled={busy || !instance.installed}>
        <label>
          {t('cua.accountProvider')}
          <select
            value={provider}
            onChange={(event) => setProvider(event.target.value as 'google' | 'microsoft365')}
          >
            <option value="google">Google</option>
            <option value="microsoft365">Microsoft 365</option>
          </select>
        </label>
        <label>
          {t('cua.clientId')}
          <input
            value={clientId}
            onChange={(event) => setClientId(event.target.value)}
            autoComplete="off"
          />
        </label>
        <p>{t('cua.clientIdDescription')}</p>
        <button
          type="button"
          disabled={!clientId.trim()}
          onClick={() =>
            void manage({
              action: 'connector_connect',
              provider,
              client_id: clientId.trim(),
            })
          }
        >
          {t('cua.addAccount')}
        </button>
      </fieldset>
      {snapshot.accounts?.map((account) => (
        <div className="computer-use-account" key={account.account_id}>
          <span>
            {account.provider} · {account.account_id} · {t(`cua.oauth.${account.status}`)}
          </span>
          {account.reason ? <code>{account.reason}</code> : null}
          {account.status === 'authorizing' ? (
            <>
              {account.authorization_url ? (
                <button
                  type="button"
                  onClick={() => {
                    const target = new URL(account.authorization_url!);
                    if (
                      target.protocol === 'https:' &&
                      ['accounts.google.com', 'login.microsoftonline.com'].includes(
                        target.hostname
                      ) &&
                      !target.username &&
                      !target.password
                    )
                      window.open(target.href, '_blank', 'noopener,noreferrer');
                  }}
                >
                  {t('cua.oauthOpen')}
                </button>
              ) : null}
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  void manage({
                    action: 'connector_cancel',
                    account_id: account.account_id,
                  })
                }
              >
                {t('cua.decline')}
              </button>
            </>
          ) : (
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                void manage({
                  action:
                    account.status === 'connected' ? 'connector_disconnect' : 'connector_start',
                  account_id: account.account_id,
                })
              }
            >
              {t(account.status === 'connected' ? 'cua.disconnectAccount' : 'cua.addAccount')}
            </button>
          )}
        </div>
      ))}
      {snapshot.connectors?.length ? (
        <ul>
          {snapshot.connectors.map((connector) => (
            <li key={`${connector.account_id}:${connector.capability}`}>
              <span>
                {connector.provider} · {connector.account_id} ·{' '}
                {t(`cua.connector.${connector.capability}`)}
              </span>
              <span>{t(connector.available ? 'cua.connected' : 'cua.unavailable')}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p>{t('cua.noConnectors')}</p>
      )}
    </section>
  );
}
import { useState } from 'react';
