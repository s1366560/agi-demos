import { useEffect, useRef } from 'react';
import { Badge, Button, Flex, Grid, Select, Text, TextField } from '@radix-ui/themes';

import { LOCAL_DEV_SERVER_PRESETS } from '../../types';
import type { ConnectionState, DesktopRuntimeConfig, RuntimeMode } from '../../types';
import { useI18n } from '../../i18n';
import {
  applyRuntimeServerPreset,
  updateRuntimeConnectionConfig,
  type RuntimeConnectionField,
} from './runtimeConfigModel';

type RuntimeConfigPanelProps = {
  config: DesktopRuntimeConfig;
  connection: ConnectionState;
  wsConnected: boolean;
  wsError: string | null;
  disabledReason: string | null;
  focusApiKeySignal?: number;
  onChange: (next: DesktopRuntimeConfig) => void;
  onRefresh: () => void;
};

export function RuntimeConfigPanel({
  config,
  connection,
  wsConnected,
  wsError,
  disabledReason,
  focusApiKeySignal = 0,
  onChange,
  onRefresh,
}: RuntimeConfigPanelProps) {
  const { t } = useI18n();
  const apiKeyInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (focusApiKeySignal <= 0) return;
    window.requestAnimationFrame(() => {
      apiKeyInputRef.current?.focus();
    });
  }, [focusApiKeySignal]);

  const update = <K extends RuntimeConnectionField>(
    key: K,
    value: DesktopRuntimeConfig[K],
  ) => {
    onChange(updateRuntimeConnectionConfig(config, key, value));
  };

  return (
    <section className="runtime-panel">
      <Flex align="center" justify="between">
        <Text size="1" weight="bold" color="gray">
          {t('runtime.connection')}
        </Text>
        <Badge
          color={connectionColor(connection)}
          variant="soft"
          role="status"
          aria-live="polite"
          aria-atomic="true"
        >
          {t(`runtime.status.${connection}`)}
        </Badge>
      </Flex>

      <Grid columns="1" gap="2">
        <label className="field-label">
          <span>{t('runtime.serverUrl')}</span>
          <TextField.Root
            aria-label={t('runtime.serverUrl')}
            value={config.apiBaseUrl}
            onChange={(event) => update('apiBaseUrl', event.target.value)}
            placeholder="http://127.0.0.1:8000"
          />
        </label>
        <div
          className="runtime-local-presets"
          aria-label={t('runtime.localDevelopmentPresets')}
        >
          {LOCAL_DEV_SERVER_PRESETS.map((preset) => (
            <Button
              key={preset.id}
              size="1"
              type="button"
              variant="surface"
              color="gray"
              aria-pressed={
                config.apiBaseUrl === preset.apiBaseUrl && config.mode === preset.mode
              }
              onClick={() => onChange(applyRuntimeServerPreset(config, preset))}
            >
              {preset.label}
            </Button>
          ))}
        </div>
        <label className="field-label">
          <span>{t('runtime.apiKey')}</span>
          <TextField.Root
            aria-label={t('runtime.apiKey')}
            ref={apiKeyInputRef}
            type="password"
            value={config.apiKey}
            onChange={(event) => update('apiKey', event.target.value)}
            placeholder={t('runtime.apiKeyPlaceholder')}
          />
        </label>
      </Grid>

      <Flex align="center" gap="2">
        <Select.Root
          value={config.mode}
          onValueChange={(value) => update('mode', value as RuntimeMode)}
        >
          <Select.Trigger aria-label={t('runtime.connectionMode')} />
          <Select.Content>
            <Select.Item value="local">{t('runtime.mode.local')}</Select.Item>
            <Select.Item value="cloud">{t('runtime.mode.cloud')}</Select.Item>
          </Select.Content>
        </Select.Root>
        <Button
          size="2"
          aria-label={t('runtime.connectRuntime')}
          onClick={onRefresh}
          loading={connection === 'loading'}
          disabled={Boolean(disabledReason)}
        >
          {t('runtime.connect')}
        </Button>
      </Flex>
      {disabledReason ? (
        <Text size="1" color="gray" className="action-hint">
          {disabledReason}
        </Text>
      ) : null}

      <Flex align="center" justify="between">
        <Text size="1" color="gray">
          {t('runtime.liveUpdates')}
        </Text>
        <Badge
          color={wsConnected ? 'green' : wsError ? 'red' : 'gray'}
          variant="soft"
          role="status"
          aria-live="polite"
          aria-atomic="true"
        >
          {wsConnected ? t('runtime.connected') : wsError ? t('runtime.error') : t('runtime.idle')}
        </Badge>
      </Flex>
      {wsError ? (
        <Text
          size="1"
          color="red"
          className="runtime-live-error"
          role="alert"
          aria-atomic="true"
        >
          {t('runtime.liveUpdatesError', { message: wsError })}
        </Text>
      ) : null}
    </section>
  );
}

function connectionColor(connection: ConnectionState): 'gray' | 'blue' | 'green' | 'red' {
  if (connection === 'loading') return 'blue';
  if (connection === 'ready') return 'green';
  if (connection === 'error') return 'red';
  return 'gray';
}
