import { useEffect, useRef } from 'react';
import { Badge, Button, Flex, Grid, Select, Text, TextField } from '@radix-ui/themes';

import { LOCAL_DEV_SERVER_PRESETS } from '../../types';
import type { ConnectionState, DesktopRuntimeConfig, RuntimeMode } from '../../types';

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
          CONNECTION
        </Text>
        <Badge color={connectionColor(connection)} variant="soft">
          {connection}
        </Badge>
      </Flex>

      <Grid columns="1" gap="2">
        <label className="field-label">
          <span>Server URL</span>
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
        <label className="field-label">
          <span>API key</span>
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
          <span>Tenant ID</span>
          <TextField.Root
            aria-label="Tenant ID"
            value={config.tenantId}
            onChange={(event) => update('tenantId', event.target.value)}
            placeholder="tenant id"
          />
        </label>
        <label className="field-label">
          <span>Project ID</span>
          <TextField.Root
            aria-label="Project ID"
            value={config.projectId}
            onChange={(event) => update('projectId', event.target.value)}
            placeholder="choose or paste project id"
          />
        </label>
        <label className="field-label">
          <span>Workspace ID</span>
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
          Connect
        </Button>
      </Flex>
      {disabledReason ? (
        <Text size="1" color="gray" className="action-hint">
          {disabledReason}
        </Text>
      ) : null}

      <Flex align="center" justify="between">
        <Text size="1" color="gray">
          Live updates
        </Text>
        <Badge color={wsConnected ? 'green' : wsError ? 'red' : 'gray'} variant="soft">
          {wsConnected ? 'connected' : wsError ? 'error' : 'idle'}
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
