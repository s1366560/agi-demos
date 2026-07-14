import { useEffect, useRef } from 'react';
import { Badge, Button, Flex, Grid, Select, Text, TextField } from '@radix-ui/themes';

import { LOCAL_DEV_SERVER_PRESETS } from '../../types';
import type { ConnectionState, DesktopRuntimeConfig, RuntimeMode } from '../../types';
import { useI18n } from '../../i18n';

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

  const update = <K extends keyof DesktopRuntimeConfig>(key: K, value: DesktopRuntimeConfig[K]) => {
    onChange({ ...config, [key]: value });
  };

  return (
    <section className="runtime-panel">
      <Flex align="center" justify="between">
        <Text size="1" weight="bold" color="gray">
          {t('runtime.connection')}
        </Text>
        <Badge color={connectionColor(connection)} variant="soft">
          {connection}
        </Badge>
      </Flex>

      <Grid columns="1" gap="2">
        <label className="field-label">
          <span>{t('runtime.serverUrl')}</span>
          <TextField.Root
            aria-label="Server URL"
            value={config.apiBaseUrl}
            onChange={(event) => update('apiBaseUrl', event.target.value)}
            placeholder="http://127.0.0.1:8000"
          />
        </label>
        <div className="runtime-local-presets" aria-label="Local development server presets">
          {LOCAL_DEV_SERVER_PRESETS.map((preset) => (
            <Button
              key={preset.id}
              size="1"
              type="button"
              variant="surface"
              color="gray"
              aria-pressed={config.apiBaseUrl === preset.apiBaseUrl}
              onClick={() => update('apiBaseUrl', preset.apiBaseUrl)}
            >
              {preset.label}
            </Button>
          ))}
        </div>
        {config.mode === 'local' ? (
          <>
            <label className="field-label">
              <span>{t('runtime.llmProvider')}</span>
              <Select.Root
                value={config.llmProvider}
                onValueChange={(value) => update('llmProvider', value)}
              >
                <Select.Trigger aria-label="Local LLM provider" />
                <Select.Content>
                  <Select.Item value="mock">mock</Select.Item>
                  <Select.Item value="openai">OpenAI-compatible</Select.Item>
                  <Select.Item value="anthropic">Anthropic-compatible</Select.Item>
                </Select.Content>
              </Select.Root>
            </label>
            <label className="field-label">
              <span>{t('runtime.llmBaseUrl')}</span>
              <TextField.Root
                aria-label="Local LLM base URL"
                value={config.llmBaseUrl}
                onChange={(event) => update('llmBaseUrl', event.target.value)}
                placeholder="http://127.0.0.1:11434/v1"
              />
            </label>
            <label className="field-label">
              <span>{t('runtime.llmModel')}</span>
              <TextField.Root
                aria-label="Local LLM model"
                value={config.llmModel}
                onChange={(event) => update('llmModel', event.target.value)}
                placeholder="leave empty for mock local agent"
              />
            </label>
            <label className="field-label">
              <span>{t('runtime.llmApiKey')}</span>
              <TextField.Root
                aria-label="Local LLM API key"
                type="password"
                value={config.llmApiKey}
                onChange={(event) => update('llmApiKey', event.target.value)}
                placeholder="optional for local gateways"
              />
            </label>
            <label className="field-label">
              <span>{t('runtime.workspaceRoot')}</span>
              <TextField.Root
                aria-label="Local workspace root"
                value={config.workspaceRoot}
                onChange={(event) => update('workspaceRoot', event.target.value)}
                placeholder="/path/to/workspace"
              />
            </label>
          </>
        ) : null}
        <label className="field-label">
          <span>{t('runtime.apiKey')}</span>
          <TextField.Root
            aria-label="API key"
            ref={apiKeyInputRef}
            type="password"
            value={config.apiKey}
            onChange={(event) => update('apiKey', event.target.value)}
            placeholder="session only, not saved"
          />
        </label>
        <label className="field-label">
          <span>{t('runtime.tenantId')}</span>
          <TextField.Root
            aria-label="Tenant ID"
            value={config.tenantId}
            onChange={(event) => update('tenantId', event.target.value)}
            placeholder="tenant id"
          />
        </label>
        <label className="field-label">
          <span>{t('runtime.projectId')}</span>
          <TextField.Root
            aria-label="Project ID"
            value={config.projectId}
            onChange={(event) => update('projectId', event.target.value)}
            placeholder="choose or paste project id"
          />
        </label>
        <label className="field-label">
          <span>{t('runtime.workspaceId')}</span>
          <TextField.Root
            aria-label="Workspace ID"
            value={config.workspaceId}
            onChange={(event) => update('workspaceId', event.target.value)}
            placeholder="auto from workspace list"
          />
        </label>
      </Grid>

      <Flex align="center" gap="2">
        <Select.Root
          value={config.mode}
          onValueChange={(value) => update('mode', value as RuntimeMode)}
        >
          <Select.Trigger aria-label="Connection mode" />
          <Select.Content>
            <Select.Item value="local">local</Select.Item>
            <Select.Item value="cloud">cloud</Select.Item>
          </Select.Content>
        </Select.Root>
        <Button
          size="2"
          aria-label="Connect runtime"
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
        <Badge color={wsConnected ? 'green' : wsError ? 'red' : 'gray'} variant="soft">
          {wsConnected ? t('runtime.connected') : wsError ? t('runtime.error') : t('runtime.idle')}
        </Badge>
      </Flex>
    </section>
  );
}

function connectionColor(connection: ConnectionState): 'gray' | 'blue' | 'green' | 'red' {
  if (connection === 'loading') return 'blue';
  if (connection === 'ready') return 'green';
  if (connection === 'error') return 'red';
  return 'gray';
}
