import { useState } from 'react';
import { useI18n } from '../../i18n';
import { LOCAL_DEV_SERVER_PRESETS } from '../../types';
import type {
  NativeKnowledgeCloudConnectionController,
  NativeKnowledgeCloudConnectionModel,
} from './nativeKnowledgeCloudConnectionController';
import './NativeKnowledgeCloudConnectionPanel.css';

export function NativeKnowledgeCloudConnectionPanel({
  model,
  controller,
  disabled = false,
}: Readonly<{
  model: NativeKnowledgeCloudConnectionModel;
  controller: NativeKnowledgeCloudConnectionController;
  disabled?: boolean;
}>) {
  const { t } = useI18n();
  const [apiBaseUrl, setApiBaseUrl] = useState<string>(LOCAL_DEV_SERVER_PRESETS[1].apiBaseUrl);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [trustedDevice, setTrustedDevice] = useState(false);
  const busy = ['loading', 'authenticating', 'disconnecting', 'enrolling', 'binding'].includes(
    model.phase,
  );
  const mustChangePassword = model.phase === 'password_change_required';
  const ready = model.phase === 'ready';
  const clearPasswords = () => {
    setPassword('');
    setCurrentPassword('');
    setNewPassword('');
  };

  return (
    <fieldset className="native-cloud-connection" disabled={disabled} aria-busy={busy}>
      <legend>{t('nativeCloud.title')}</legend>
      <p>{t('nativeCloud.help')}</p>
      {model.error ? <p role="alert">{t(`nativeCloud.${model.error}`)}</p> : null}
      {busy ? <p role="status">{t('nativeCloud.working')}</p> : null}
      {mustChangePassword ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const request = { currentPassword, newPassword };
            clearPasswords();
            void controller.changePassword(request);
          }}
        >
          <p role="status">{t('nativeCloud.passwordChangeRequired')}</p>
          <label>
            <span>{t('nativeCloud.currentPassword')}</span>
            <input
              type="password"
              autoComplete="current-password"
              required
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
            />
          </label>
          <label>
            <span>{t('nativeCloud.newPassword')}</span>
            <input
              type="password"
              autoComplete="new-password"
              required
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
            />
          </label>
          <button type="submit">{t('nativeCloud.changePassword')}</button>
        </form>
      ) : !model.connection ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const request = { apiBaseUrl, username, password, trustedDevice };
            clearPasswords();
            void controller.login(request);
          }}
        >
          <fieldset disabled={busy}>
            <label>
              <span>{t('nativeCloud.server')}</span>
              <input
                type="url"
                required
                value={apiBaseUrl}
                onChange={(event) => setApiBaseUrl(event.target.value)}
              />
            </label>
            <label>
              <span>{t('nativeCloud.username')}</span>
              <input
                type="email"
                autoComplete="username"
                required
                value={username}
                onChange={(event) => setUsername(event.target.value)}
              />
            </label>
            <label>
              <span>{t('nativeCloud.password')}</span>
              <input
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            <label className="native-cloud-connection-check">
              <input
                type="checkbox"
                checked={trustedDevice}
                onChange={(event) => setTrustedDevice(event.target.checked)}
              />
              <span>{t('nativeCloud.trustedDevice')}</span>
            </label>
            <button type="submit">{t('nativeCloud.login')}</button>
          </fieldset>
        </form>
      ) : (
        <>
          <dl>
            <dt>{t('nativeCloud.authority')}</dt>
            <dd>{model.connection.authority}</dd>
            <dt>{t('nativeCloud.actor')}</dt>
            <dd>{model.connection.actor_id}</dd>
          </dl>
          <label>
            <span>{t('nativeCloud.tenant')}</span>
            <select
              value={model.selectedTenantId ?? ''}
              disabled={!ready}
              onChange={(event) => {
                if (event.target.value) void controller.selectTenant(event.target.value);
              }}
            >
              <option value="" disabled>
                {t('nativeCloud.chooseTenant')}
              </option>
              {model.tenants.map((tenant) => (
                <option key={tenant.id} value={tenant.id}>
                  {tenant.name} ({tenant.id})
                </option>
              ))}
            </select>
          </label>
          {ready && model.tenants.length === 0 ? <p>{t('nativeCloud.noTenants')}</p> : null}
          <label>
            <span>{t('nativeCloud.project')}</span>
            <select
              value={model.selectedProjectId ?? ''}
              disabled={!ready || !model.selectedTenantId}
              onChange={(event) => {
                if (event.target.value) void controller.selectProject(event.target.value);
              }}
            >
              <option value="" disabled>
                {t('nativeCloud.chooseProject')}
              </option>
              {model.projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name} ({project.id})
                </option>
              ))}
            </select>
          </label>
          {ready && model.selectedTenantId && model.projects.length === 0 ? (
            <p>{t('nativeCloud.noProjects')}</p>
          ) : null}
          {model.bound ? (
            <p role="status">{t('nativeCloud.bound')}</p>
          ) : model.enrollment?.enabled ? (
            <button
              type="button"
              disabled={!ready || !model.selectedProjectId}
              onClick={() => void controller.bind()}
            >
              {t('nativeCloud.bind')}
            </button>
          ) : model.enrollment ? (
            <>
              <p>
                {t(
                  model.enrollment.can_enroll
                    ? 'nativeCloud.enrollHelp'
                    : 'nativeCloud.cannotEnroll',
                )}
              </p>
              {model.enrollment.can_enroll ? (
                <button
                  type="button"
                  disabled={!ready || !model.selectedProjectId}
                  onClick={() => void controller.enroll()}
                >
                  {t('nativeCloud.enroll')}
                </button>
              ) : null}
            </>
          ) : null}
        </>
      )}
      <div className="native-knowledge-actions">
        <button
          type="button"
          disabled={busy || mustChangePassword}
          onClick={() => void controller.refresh()}
        >
          {t('nativeCloud.refresh')}
        </button>
        <button
          type="button"
          disabled={model.phase === 'disconnecting'}
          onClick={() => {
            clearPasswords();
            void controller.disconnect();
          }}
        >
          {t('nativeCloud.disconnect')}
        </button>
      </div>
    </fieldset>
  );
}
