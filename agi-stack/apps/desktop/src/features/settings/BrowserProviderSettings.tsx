import { useState } from 'react';
import { Button } from '@radix-ui/themes';
import { useI18n } from '../../i18n';
import type {
  BrowserBridgeConfig,
  BrowserBridgeStatus,
  BrowserProviderConfiguration,
} from '../../types';
import { browserProviderOptions, removeBrowserEndpoint } from './browserProviderSettingsModel';

export function BrowserProviderSettings({
  config = {},
  status,
  busy,
  error,
  save,
}: {
  config?: Partial<BrowserBridgeConfig>;
  status: BrowserBridgeStatus | null;
  busy: boolean;
  error: string | null;
  save: (providers: BrowserProviderConfiguration) => Promise<boolean>;
}) {
  const { t } = useI18n();
  const [name, setName] = useState('');
  const [endpoint, setEndpoint] = useState('');
  const providers = {
    cdp_endpoints: config.cdp_endpoints ?? [],
    default_browser_id: config.default_browser_id ?? 'iab',
  };
  const options = browserProviderOptions(config, status?.browserInstances ?? []);
  return (
    <section
      className="settings-panel settings-browser-providers-panel"
      aria-label={t('settings.browserProviders')}
    >
      <header>
        <span>
          <strong>{t('settings.browserProviders')}</strong>
          <small>{t('settings.browserProvidersDescription')}</small>
        </span>
      </header>
      <label className="settings-browser-default">
        <span>{t('settings.browserDefault')}</span>
        <select
          value={providers.default_browser_id}
          disabled={busy}
          onChange={(event) => {
            void save({
              ...providers,
              default_browser_id: event.currentTarget.value,
            });
          }}
        >
          {options.map((option) => (
            <option key={option.id} value={option.id}>
              {option.id === 'iab' ? t('settings.browserIab') : option.name}
              {option.online ? '' : ` (${t('settings.browserProviderOffline')})`}
            </option>
          ))}
        </select>
      </label>
      <div className="settings-rows">
        {providers.cdp_endpoints.map((item) => {
          const connection = status?.cdpEndpoints?.find((row) => row.id === item.id);
          const state = item.enabled ? (connection?.status ?? 'disconnected') : 'disabled';
          return (
            <div className="settings-row" key={item.id}>
              <span>
                <strong>{item.name}</strong>
                <small>{item.endpoint}</small>
                <small role="status">{t(`settings.browserProviderState.${state}`)}</small>
                {connection?.error ? <small role="alert">{connection.error}</small> : null}
              </span>
              <div className="settings-browser-actions">
                <button
                  type="button"
                  role="switch"
                  aria-label={`${t('settings.browserProviderEnable')}: ${item.name}`}
                  aria-checked={item.enabled}
                  disabled={busy}
                  onClick={() =>
                    void save({
                      ...providers,
                      cdp_endpoints: providers.cdp_endpoints.map((row) =>
                        row.id === item.id ? { ...row, enabled: !row.enabled } : row,
                      ),
                    })
                  }
                >
                  {t(item.enabled ? 'settings.preferenceOn' : 'settings.preferenceOff')}
                </button>
                <Button
                  type="button"
                  variant="soft"
                  color="red"
                  disabled={busy}
                  aria-label={`${t('settings.browserProviderRemove')}: ${item.name}`}
                  onClick={() => void save(removeBrowserEndpoint(providers, item.id))}
                >
                  {t('settings.browserProviderRemove')}
                </Button>
              </div>
            </div>
          );
        })}
      </div>
      <form
        className="settings-browser-credential-form"
        onSubmit={async (event) => {
          event.preventDefault();
          if (!name.trim() || !endpoint.trim() || busy) return;
          const added = {
            id: crypto.randomUUID(),
            name: name.trim(),
            endpoint: endpoint.trim(),
            enabled: true,
          };
          if (
            await save({
              ...providers,
              cdp_endpoints: [...providers.cdp_endpoints, added],
            })
          ) {
            setName('');
            setEndpoint('');
          }
        }}
      >
        <label>
          <span>{t('settings.browserProviderName')}</span>
          <input
            value={name}
            maxLength={128}
            disabled={busy}
            onChange={(event) => setName(event.currentTarget.value)}
          />
        </label>
        <label>
          <span>{t('settings.browserProviderEndpoint')}</span>
          <input
            value={endpoint}
            maxLength={4096}
            disabled={busy}
            placeholder="http://127.0.0.1:9222"
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => setEndpoint(event.currentTarget.value)}
          />
        </label>
        <Button type="submit" variant="soft" disabled={busy || !name.trim() || !endpoint.trim()}>
          {t('settings.browserProviderAdd')}
        </Button>
      </form>
      {error ? (
        <p className="settings-browser-error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}
