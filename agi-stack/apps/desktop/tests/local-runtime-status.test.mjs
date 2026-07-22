import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  DEFAULT_CONFIG,
  LOCAL_DEV_SERVER_PRESETS,
  mergeLocalRuntimeStatus,
} = require('/tmp/agistack-desktop-test-dist/src/types.js');
const {
  conversationRuntimeModelSelection,
  latestConversationRuntimeModelEvent,
  workspaceRuntimeModelOptions,
  workspaceRuntimeModelSelectionValue,
  workspaceRuntimeProviderFromAuthority,
  workspaceRuntimeRoutingMutation,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/settings/workspaceRuntimeProviderModel.js'
);
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

test('workspace runtime projection follows only the selected workspace default route', () => {
  const config = {
    ...DEFAULT_CONFIG,
    tenantId: 'tenant-a',
    projectId: 'project-a',
    workspaceId: 'workspace-a',
  };
  const policy = {
    tenant_id: 'tenant-a',
    project_id: 'project-a',
    workspace_id: 'workspace-a',
    revision: 3,
    roles: {
      default: { provider_id: 'provider-a', model_id: 'gpt-authoritative' },
      fast: null,
      coding: null,
      vision: null,
    },
    fallbacks: [],
    updated_at: '2026-07-19T00:00:00Z',
  };
  const providers = [
    {
      id: 'provider-a',
      name: 'OpenAI production',
      provider_type: 'openai',
      auth_method: 'api_key',
      credential_configured: true,
    },
    {
      id: 'provider-b',
      name: 'Anthropic production',
      provider_type: 'anthropic',
      auth_method: 'api_key',
      credential_configured: true,
    },
  ];

  assert.deepEqual(workspaceRuntimeProviderFromAuthority(config, policy, providers), {
    tenant_id: 'tenant-a',
    project_id: 'project-a',
    workspace_id: 'workspace-a',
    provider_id: 'provider-a',
    provider_type: 'openai',
    model: 'gpt-authoritative',
    credential_configured: true,
  });
  assert.equal(
    workspaceRuntimeProviderFromAuthority(
      { ...config, workspaceId: 'workspace-b' },
      policy,
      providers,
    ),
    null,
  );
  assert.equal(workspaceRuntimeProviderFromAuthority(config, policy, providers.slice(1)), null);
});

test('workspace model selector exposes only routable enabled models and marks the default route', () => {
  const config = {
    ...DEFAULT_CONFIG,
    tenantId: 'tenant-a',
    projectId: 'project-a',
    workspaceId: 'workspace-a',
  };
  const policy = {
    tenant_id: 'tenant-a',
    project_id: 'project-a',
    workspace_id: 'workspace-a',
    revision: 3,
    roles: {
      default: { provider_id: 'provider-a', model_id: 'gpt-primary' },
      fast: null,
      coding: null,
      vision: null,
    },
    fallbacks: [],
    updated_at: '2026-07-19T00:00:00Z',
  };
  const providers = [
    {
      id: 'provider-a',
      name: 'OpenAI production',
      provider_type: 'openai_compatible',
      operation_type: 'llm',
      auth_method: 'api_key',
      credential_configured: true,
      is_active: true,
      is_enabled: true,
      base_url: 'https://api.example.test/v1',
      llm_model: 'gpt-primary',
      allowed_models: ['gpt-primary', 'gpt-fast', 'gpt-fast'],
      health_status: 'healthy',
    },
    {
      id: 'provider-b',
      name: 'OpenAI staging',
      provider_type: 'openai_compatible',
      operation_type: 'llm',
      auth_method: 'api_key',
      credential_configured: false,
      is_active: true,
      base_url: 'https://staging.example.test/v1',
      llm_model: 'staging-only',
      allowed_models: ['staging-only'],
      health_status: 'healthy',
    },
  ];

  assert.deepEqual(workspaceRuntimeModelOptions(policy, providers), [
    {
      value: workspaceRuntimeModelSelectionValue('provider-a', 'gpt-primary'),
      providerId: 'provider-a',
      providerLabel: 'OpenAI production',
      modelId: 'gpt-primary',
      selected: true,
      roles: ['default'],
      description: 'OpenAI production · openai_compatible',
      contextWindow: null,
    },
    {
      value: workspaceRuntimeModelSelectionValue('provider-a', 'gpt-fast'),
      providerId: 'provider-a',
      providerLabel: 'OpenAI production',
      modelId: 'gpt-fast',
      selected: false,
      roles: [],
      description: 'OpenAI production · openai_compatible',
      contextWindow: null,
    },
  ]);

  const codingPolicy = {
    ...policy,
    roles: {
      ...policy.roles,
      coding: { provider_id: 'provider-a', model_id: 'gpt-fast' },
    },
  };
  assert.deepEqual(
    workspaceRuntimeModelOptions(codingPolicy, providers, 'coding')
      .filter((option) => option.selected)
      .map((option) => option.modelId),
    ['gpt-fast'],
  );
  assert.equal(
    workspaceRuntimeProviderFromAuthority(config, codingPolicy, providers, 'coding')?.model,
    'gpt-fast',
  );
});

test('active conversations restore a persisted model override without changing workspace routing', () => {
  const options = [
    {
      value: workspaceRuntimeModelSelectionValue('provider-a', 'gpt-primary'),
      providerId: 'provider-a',
      providerLabel: 'OpenAI production',
      modelId: 'gpt-primary',
      selected: true,
    },
    {
      value: workspaceRuntimeModelSelectionValue('provider-a', 'gpt-reasoning'),
      providerId: 'provider-a',
      providerLabel: 'OpenAI production',
      modelId: 'gpt-reasoning',
      selected: false,
    },
  ];

  assert.deepEqual(
    conversationRuntimeModelSelection(
      { llm_model_override: ' gpt-reasoning ' },
      options,
      options[0].value,
      'gpt-primary',
    ),
    {
      overrideModel: 'gpt-reasoning',
      selectedValue: options[1].value,
      displayLabel: 'gpt-reasoning',
      canReset: true,
    },
  );
  assert.deepEqual(
    conversationRuntimeModelSelection(null, options, options[0].value, 'gpt-primary'),
    {
      overrideModel: null,
      selectedValue: options[0].value,
      displayLabel: 'gpt-primary',
      canReset: false,
    },
  );
  assert.deepEqual(
    conversationRuntimeModelSelection(
      { llm_model_override: 'unavailable-model' },
      options,
      options[0].value,
      'gpt-primary',
    ),
    {
      overrideModel: 'unavailable-model',
      selectedValue: null,
      displayLabel: 'unavailable-model',
      canReset: true,
    },
  );
});

test('conversation model selection fails closed when a model id is ambiguous', () => {
  const options = [
    {
      value: workspaceRuntimeModelSelectionValue('provider-a', 'shared-model'),
      providerId: 'provider-a',
      providerLabel: 'Provider A',
      modelId: 'shared-model',
      selected: true,
    },
    {
      value: workspaceRuntimeModelSelectionValue('provider-b', 'shared-model'),
      providerId: 'provider-b',
      providerLabel: 'Provider B',
      modelId: 'shared-model',
      selected: false,
    },
  ];
  assert.deepEqual(
    conversationRuntimeModelSelection(
      { llm_model_override: 'shared-model' },
      options,
      options[0].value,
      'shared-model',
    ),
    {
      overrideModel: 'shared-model',
      selectedValue: null,
      displayLabel: 'shared-model',
      canReset: true,
    },
  );
});

test('latest conversation model events override or clear persisted selector state', () => {
  assert.deepEqual(
    latestConversationRuntimeModelEvent([
      {
        type: 'model_switch_requested',
        payload: { model: 'gpt-reasoning' },
        eventTimeUs: 1,
        eventCounter: 1,
      },
    ]),
    { overrideModel: 'gpt-reasoning', revision: 'model_switch_requested::1:1' },
  );
  assert.deepEqual(
    latestConversationRuntimeModelEvent([
      {
        type: 'model_switch_requested',
        payload: { model: 'gpt-reasoning' },
        eventTimeUs: 1,
        eventCounter: 1,
      },
      {
        type: 'model_override_rejected',
        payload: { model: 'gpt-reasoning', current_model: 'gpt-primary' },
        eventTimeUs: 2,
        eventCounter: 2,
      },
    ]),
    { overrideModel: null, revision: 'model_override_rejected::2:2' },
  );
  assert.equal(latestConversationRuntimeModelEvent([{ type: 'context_status' }]), null);
});

test('workspace model switch replaces only the default route and keeps policy concurrency', () => {
  const config = {
    ...DEFAULT_CONFIG,
    tenantId: 'tenant-a',
    projectId: 'project-a',
    workspaceId: 'workspace-a',
  };
  const policy = {
    tenant_id: 'tenant-a',
    project_id: 'project-a',
    workspace_id: 'workspace-a',
    revision: 7,
    roles: {
      default: { provider_id: 'provider-a', model_id: 'gpt-primary' },
      fast: { provider_id: 'provider-a', model_id: 'gpt-fast' },
      coding: null,
      vision: null,
    },
    fallbacks: [{ provider_id: 'provider-b', model_id: 'fallback-model' }],
    updated_at: '2026-07-19T00:00:00Z',
  };
  const option = {
    value: workspaceRuntimeModelSelectionValue('provider-b', 'next-model'),
    providerId: 'provider-b',
    providerLabel: 'Provider B',
    modelId: 'next-model',
    selected: false,
  };

  assert.deepEqual(workspaceRuntimeRoutingMutation(config, policy, option), {
    projectId: 'project-a',
    workspaceId: 'workspace-a',
    expectedRevision: 7,
    roles: {
      default: { provider_id: 'provider-b', model_id: 'next-model' },
      fast: { provider_id: 'provider-a', model_id: 'gpt-fast' },
      coding: null,
      vision: null,
    },
    fallbacks: [{ provider_id: 'provider-b', model_id: 'fallback-model' }],
  });
  assert.equal(
    workspaceRuntimeRoutingMutation({ ...config, workspaceId: 'workspace-b' }, policy, option),
    null,
  );
});

test('code-session model switch writes the coding route and repairs an empty default route', () => {
  const config = {
    ...DEFAULT_CONFIG,
    tenantId: 'tenant-a',
    projectId: 'project-a',
    workspaceId: 'workspace-a',
  };
  const policy = {
    tenant_id: 'tenant-a',
    project_id: 'project-a',
    workspace_id: 'workspace-a',
    revision: 0,
    roles: { default: null, fast: null, coding: null, vision: null },
    fallbacks: [],
    updated_at: '2026-07-20T00:00:00Z',
  };
  const option = {
    value: workspaceRuntimeModelSelectionValue('glm-provider', 'glm-5.2'),
    providerId: 'glm-provider',
    providerLabel: 'OpenAI-compatible',
    modelId: 'glm-5.2',
    selected: false,
  };

  assert.deepEqual(workspaceRuntimeRoutingMutation(config, policy, option, 'coding'), {
    projectId: 'project-a',
    workspaceId: 'workspace-a',
    expectedRevision: 0,
    roles: {
      default: { provider_id: 'glm-provider', model_id: 'glm-5.2' },
      fast: null,
      coding: { provider_id: 'glm-provider', model_id: 'glm-5.2' },
      vision: null,
    },
    fallbacks: [],
  });
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
  assert.doesNotMatch(appSource, /runtimeProviderForTenant/);
  assert.match(appSource, /useWorkspaceRuntimeProvider\(/);
  assert.match(
    appSource,
    /value: config\.mode === 'local' \? localRuntimeProviderLabel : config\.mode/,
  );
  assert.match(
    appSource,
    /value: config\.mode === 'local' \? localRuntimeModelLabel : 'server managed'/,
  );
  assert.match(appSource, /modelLabel=\{chatRuntimeModelSelection\.displayLabel\}/);
  assert.match(appSource, /onModelChange=\{selectChatRuntimeModel\}/);
  assert.match(appSource, /onModelReset=\{[\s\S]{0,180}resetChatRuntimeModel/);
});
