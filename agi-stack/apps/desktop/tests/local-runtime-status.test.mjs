import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  DEFAULT_CONFIG,
  LOCAL_DEV_SERVER_PRESETS,
  mergeLocalRuntimeStatus,
  runtimeProviderForTenant,
} = require('/tmp/agistack-desktop-test-dist/src/types.js');
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const typesSource = readFileSync(new URL('../src/types.ts', import.meta.url), 'utf8');
const providerSettingsQaSource = readFileSync(
  new URL('../src/qa/ProviderSettingsQa.tsx', import.meta.url),
  'utf8',
);

test('Rust desktop backend is the default server preset with Python retained as fallback', () => {
  assert.deepEqual(LOCAL_DEV_SERVER_PRESETS[0], {
    id: 'agistack-rust',
    label: 'agi-stack desktop :8088',
    apiBaseUrl: 'http://127.0.0.1:8088',
    mode: 'local',
  });
  assert.deepEqual(LOCAL_DEV_SERVER_PRESETS[1], {
    id: 'memstack-python',
    label: 'MemStack reference :8000',
    apiBaseUrl: 'http://127.0.0.1:8000',
    mode: 'cloud',
  });
  assert.equal(DEFAULT_CONFIG.apiBaseUrl, 'http://127.0.0.1:8088');
});

test('local runtime status replaces transport authority without carrying an LLM tuple or secret', () => {
  const merged = mergeLocalRuntimeStatus(
    {
      ...DEFAULT_CONFIG,
      apiKey: 'stale-cloud-token',
      localApiToken: 'stale-local-capability',
    },
    {
      running: true,
      api_base_url: 'http://127.0.0.1:54321',
      api_token: 'fresh-local-capability',
      workspace_root: '/tmp/workspace',
      tool_count: 1,
      tools: ['bash'],
      config: { workspace_root: '/tmp/workspace' },
      runtime_providers: [
        {
          tenant_id: 'local',
          provider_id: 'provider-local',
          provider_type: 'mock',
          model: 'mock-v1',
          credential_configured: true,
        },
      ],
    }
  );

  assert.equal(merged.apiBaseUrl, 'http://127.0.0.1:54321');
  assert.equal(merged.apiKey, 'stale-cloud-token');
  assert.equal(merged.localApiToken, 'fresh-local-capability');
  for (const removedField of ['llmProvider', 'llmBaseUrl', 'llmModel', 'llmApiKey']) {
    assert.equal(removedField in DEFAULT_CONFIG, false);
    assert.equal(removedField in merged, false);
  }
});

test('runtime provider projection resolves only one exact tenant match', () => {
  const status = {
    running: true,
    api_base_url: 'http://127.0.0.1:54321',
    api_token: 'fresh-local-capability',
    workspace_root: '/tmp/workspace',
    tool_count: 0,
    tools: [],
    config: { workspace_root: '/tmp/workspace' },
    runtime_providers: [
      {
        tenant_id: 'tenant-a',
        provider_id: 'provider-a',
        provider_type: 'openai',
        model: 'gpt-authoritative',
        credential_configured: true,
      },
      {
        tenant_id: 'tenant-b',
        provider_id: 'provider-b',
        provider_type: 'anthropic',
        model: 'claude-authoritative',
        credential_configured: true,
      },
    ],
  };

  assert.equal(runtimeProviderForTenant(status, 'tenant-a')?.provider_id, 'provider-a');
  assert.equal(runtimeProviderForTenant(status, 'missing'), null);
  assert.equal(
    runtimeProviderForTenant(
      { ...status, runtime_providers: [...status.runtime_providers, status.runtime_providers[0]] },
      'tenant-a',
    ),
    null,
  );
});

test('Desktop runtime configuration and Tauri configure payload contain no LLM authority', () => {
  const configType =
    typesSource.match(/export type DesktopRuntimeConfig = \{[\s\S]*?\n\};/)?.[0] ?? '';
  const defaultConfig =
    typesSource.match(/export const DEFAULT_CONFIG: DesktopRuntimeConfig = \{[\s\S]*?\n\};/)?.[0] ?? '';
  const tauriConfig =
    appSource.match(/function localRuntimeTauriConfig\([\s\S]*?\n\}/)?.[0] ?? '';
  const logout = appSource.match(/const logout = async \(\) => \{[\s\S]*?\n  \};/)?.[0] ?? '';
  const forbidden = /llmProvider|llmBaseUrl|llmModel|llmApiKey|api_key|base_url|provider:|model:/;

  assert.doesNotMatch(configType, forbidden);
  assert.doesNotMatch(defaultConfig, forbidden);
  assert.match(tauriConfig, /workspace_root: config\.workspaceRoot/);
  assert.doesNotMatch(tauriConfig, forbidden);
  assert.doesNotMatch(logout, /llmProvider|llmBaseUrl|llmModel|llmApiKey/);
  assert.doesNotMatch(providerSettingsQaSource, /llmProvider|llmBaseUrl|llmModel|llmApiKey/);
  assert.match(
    appSource,
    /runtimeProviderForTenant\(localRuntimeStatus, config\.tenantId\)/,
  );
  assert.match(
    appSource,
    /value: config\.mode === 'local' \? localRuntimeProviderLabel : config\.mode/,
  );
  assert.match(
    appSource,
    /value: config\.mode === 'local' \? localRuntimeModelLabel : 'server managed'/,
  );
  assert.match(
    appSource,
    /modelLabel=\{config\.mode === 'local' \? localRuntimeModelLabel : undefined\}/,
  );
});
