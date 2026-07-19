import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { DesktopApiClient } = require('/tmp/agistack-desktop-test-dist/src/api/client.js');
const {
  filterProviders,
  providerConnectionStatus,
  providerConfigurationValidationOutcome,
  providerCreateInputFromDraft,
  providerDraftFromProvider,
  providerAuthMethodSupported,
  providerManagementAllowed,
  providerEnabledModelIds,
  localRuntimeRoutingModelIds,
  providerModelCanBeDisabled,
  providerModelsFromProvider,
  providerMutationForEnabledModels,
  providerMutationFromDraft,
  providerProbeInputFromDraft,
  providerProbeInputIsValid,
  providerRoutingOverview,
  providerTypeDisplayName,
  routingFallbackCanAdd,
  providerValidationAccepted,
  providerValidationSignal,
  providerValidationSucceeded,
} = require('/tmp/agistack-desktop-test-dist/src/features/settings/providerManagementModel.js');
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');
const addProviderDialogSource = readFileSync(
  new URL('../src/features/settings/AddProviderDialog.tsx', import.meta.url),
  'utf8',
);
const providerConnectionPanelSource = readFileSync(
  new URL('../src/features/settings/ProviderConnectionPanel.tsx', import.meta.url),
  'utf8',
);
const providerStatusBadgeSource = readFileSync(
  new URL('../src/features/settings/ProviderStatusBadge.tsx', import.meta.url),
  'utf8',
);
const providerModelsPanelSource = readFileSync(
  new URL('../src/features/settings/ProviderModelsPanel.tsx', import.meta.url),
  'utf8',
);
const providerOverviewPanelsSource = readFileSync(
  new URL('../src/features/settings/ProviderOverviewPanels.tsx', import.meta.url),
  'utf8',
);
const modelProviderWorkspaceSource = readFileSync(
  new URL('../src/features/settings/ModelProviderWorkspace.tsx', import.meta.url),
  'utf8',
);
const modelProviderWorkspaceCss = readFileSync(
  new URL('../src/features/settings/ModelProviderWorkspace.css', import.meta.url),
  'utf8',
);
const settingsWindowSource = readFileSync(
  new URL('../src/features/settings/SettingsWindow.tsx', import.meta.url),
  'utf8',
);
const providerSettingsQaSource = readFileSync(
  new URL('../src/qa/ProviderSettingsQa.tsx', import.meta.url),
  'utf8',
);
const i18nSource = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');
const apiClientSource = readFileSync(new URL('../src/api/client.ts', import.meta.url), 'utf8');

test('provider management permissions keep local owner and cloud admin boundaries explicit', () => {
  assert.equal(providerManagementAllowed('local', ['owner']), true);
  assert.equal(providerManagementAllowed('local', ['member']), false);
  assert.equal(providerManagementAllowed('cloud', ['admin']), true);
  assert.equal(providerManagementAllowed('cloud', ['owner']), false);
});

test('provider type labels preserve public brand spelling', () => {
  assert.equal(providerTypeDisplayName('openai'), 'OpenAI');
  assert.equal(providerTypeDisplayName('azure_openai'), 'Azure OpenAI');
  assert.equal(providerTypeDisplayName('openai_compatible'), 'OpenAI-compatible');
  assert.equal(providerTypeDisplayName('lmstudio'), 'LM Studio');
  assert.equal(providerTypeDisplayName('custom_gateway'), 'Custom Gateway');
});

test('Settings model navigation copy matches the approved provider-first source', () => {
  assert.match(i18nSource, /'settings\.modelsDescription': 'Providers, routing, and budgets'/);
  assert.match(i18nSource, /'settings\.modelsDescription': '供应商、路由与预算'/);
  assert.match(i18nSource, /'settings\.accountContext': '账号与上下文'/);
  assert.match(i18nSource, /'settings\.account': '账号'/);
  assert.doesNotMatch(i18nSource, /Provider、模型与健康状态|你的账户/);
});

test('provider setup fails closed when the server does not declare an auth capability', () => {
  const legacyDescriptor = {
    providerType: 'legacy',
    authMethods: [],
    unavailableAuthMethods: [],
    operationType: 'llm',
    probeSupported: true,
    source: 'cloud_api',
  };
  const apiKeyDescriptor = {
    providerType: 'openai',
    authMethods: ['api_key'],
    unavailableAuthMethods: [],
    operationType: 'llm',
    probeSupported: true,
    source: 'cloud_api',
  };
  const oauthDescriptor = {
    providerType: 'anthropic',
    authMethods: ['oauth', 'api_key'],
    unavailableAuthMethods: ['oauth'],
    operationType: 'llm',
    probeSupported: true,
    source: 'cloud_api',
  };

  assert.equal(providerAuthMethodSupported(legacyDescriptor, 'api_key'), false);
  assert.equal(providerAuthMethodSupported(apiKeyDescriptor, 'api_key'), true);
  assert.equal(providerAuthMethodSupported(apiKeyDescriptor, 'none'), false);
  assert.equal(providerAuthMethodSupported(oauthDescriptor, 'oauth'), false);
  assert.equal(providerAuthMethodSupported(oauthDescriptor, 'api_key'), true);
});

test('provider drafts produce trimmed mutations without retaining an empty secret', () => {
  const draft = providerDraftFromProvider({
    id: 'local-runtime',
    name: 'Local runtime',
    provider_type: 'openai_compatible',
    auth_method: 'api_key',
    base_url: 'http://127.0.0.1:11434/v1',
    llm_model: 'qwen3-coder',
    allowed_models: ['qwen3-coder'],
    is_active: true,
    api_key_masked: 'sk-...redacted',
    revision: 7,
  });
  assert.equal(draft.apiKey, '');
  draft.name = '  Local gateway  ';
  draft.allowedModels = 'qwen3-coder\n qwen3-small, qwen3-coder ';
  draft.apiKey = '   ';

  assert.deepEqual(providerMutationFromDraft(draft), {
    name: 'Local gateway',
    providerType: 'openai_compatible',
    authMethod: 'api_key',
    baseUrl: 'http://127.0.0.1:11434/v1',
    primaryModel: 'qwen3-coder',
    allowedModels: ['qwen3-coder', 'qwen3-small'],
    active: true,
    expectedRevision: 7,
  });
  assert.deepEqual(providerCreateInputFromDraft(draft), {
    name: 'Local gateway',
    providerType: 'openai_compatible',
    authMethod: 'api_key',
    baseUrl: 'http://127.0.0.1:11434/v1',
    primaryModel: 'qwen3-coder',
    allowedModels: ['qwen3-coder', 'qwen3-small'],
    active: true,
  });
  assert.deepEqual(providerProbeInputFromDraft(draft), {
    name: 'Local gateway',
    providerType: 'openai_compatible',
    authMethod: 'api_key',
    baseUrl: 'http://127.0.0.1:11434/v1',
    active: true,
  });
  assert.equal(providerProbeInputIsValid(providerProbeInputFromDraft(draft)), false);
  assert.equal(providerProbeInputIsValid(providerProbeInputFromDraft(draft), true), true);
});

test('environment drafts retain only the variable reference and OAuth stays unavailable', () => {
  const environmentDraft = providerDraftFromProvider({
    id: 'environment-openai',
    name: 'Environment OpenAI',
    provider_type: 'openai',
    auth_method: 'environment',
    environment_variable: 'OPENAI_API_KEY',
    base_url: 'https://api.openai.com/v1/',
    llm_model: 'gpt-test',
    allowed_models: ['gpt-test'],
    is_active: true,
    revision: 3,
  });
  environmentDraft.apiKey = 'must-not-be-serialized';

  assert.equal(environmentDraft.authMethod, 'environment');
  assert.equal(environmentDraft.environmentVariable, 'OPENAI_API_KEY');
  assert.deepEqual(providerMutationFromDraft(environmentDraft), {
    name: 'Environment OpenAI',
    providerType: 'openai',
    authMethod: 'environment',
    baseUrl: 'https://api.openai.com/v1',
    primaryModel: 'gpt-test',
    allowedModels: ['gpt-test'],
    active: true,
    expectedRevision: 3,
    environmentVariable: 'OPENAI_API_KEY',
  });
  assert.deepEqual(providerProbeInputFromDraft(environmentDraft), {
    name: 'Environment OpenAI',
    providerType: 'openai',
    authMethod: 'environment',
    baseUrl: 'https://api.openai.com/v1',
    active: true,
    environmentVariable: 'OPENAI_API_KEY',
  });
  assert.equal(providerProbeInputIsValid(providerProbeInputFromDraft(environmentDraft)), true);

  const oauthDraft = providerDraftFromProvider({
    id: 'oauth-anthropic',
    name: 'OAuth Anthropic',
    provider_type: 'anthropic',
    auth_method: 'oauth',
    base_url: 'https://api.anthropic.com',
  });
  assert.equal(oauthDraft.authMethod, 'oauth');
  assert.equal(providerProbeInputIsValid(providerProbeInputFromDraft(oauthDraft), true), false);
});

test('provider model selection always retains the current default model', () => {
  const provider = {
    id: 'production',
    name: 'Production',
    provider_type: 'openai',
    auth_method: 'api_key',
    base_url: 'https://api.openai.com/v1',
    llm_model: 'gpt-5',
    allowed_models: ['gpt-5-mini', ' gpt-5-mini '],
    is_active: true,
    revision: 4,
  };

  assert.deepEqual(providerEnabledModelIds(provider), ['gpt-5-mini', 'gpt-5']);
  assert.equal(providerModelCanBeDisabled(provider, 'gpt-5'), false);
  assert.equal(providerModelCanBeDisabled(provider, 'gpt-5-mini'), true);

  const mutation = providerMutationForEnabledModels(provider, ['gpt-5-mini']);
  assert.equal(mutation.primaryModel, 'gpt-5');
  assert.deepEqual(mutation.allowedModels, ['gpt-5-mini', 'gpt-5']);
});

test('provider model selection promotes the first enabled model when no default exists', () => {
  const provider = {
    id: 'local-runtime',
    name: 'Local runtime',
    provider_type: 'openai_compatible',
    auth_method: 'none',
    base_url: 'http://127.0.0.1:11434/v1',
    llm_model: '',
    allowed_models: [],
    is_active: true,
    revision: 2,
  };

  const mutation = providerMutationForEnabledModels(provider, ['qwen3-coder', 'qwen3-coder']);
  assert.equal(mutation.primaryModel, 'qwen3-coder');
  assert.deepEqual(mutation.allowedModels, ['qwen3-coder']);
});

test('provider workspace helpers search structured fields and map attention states', () => {
  const providers = [
    {
      id: 'openai',
      name: 'OpenAI Production',
      provider_type: 'openai',
      operation_type: 'llm',
      allowed_models: ['gpt-5', ' gpt-5-mini ', 'gpt-5'],
      is_active: true,
      credential_configured: true,
      health_status: 'healthy',
    },
    {
      id: 'anthropic',
      name: 'Research',
      provider_type: 'anthropic',
      operation_type: 'llm',
      allowed_models: ['claude-sonnet-4'],
      is_active: true,
      credential_configured: false,
      health_status: 'needs_credentials',
    },
    {
      id: 'embedding',
      name: 'Vector API',
      provider_type: 'openai_embedding',
      operation_type: 'embedding',
      allowed_models: ['text-embedding-3-large'],
      is_active: false,
    },
  ];

  assert.equal(providerConnectionStatus(providers[0]), 'connected');
  assert.equal(providerConnectionStatus(providers[1]), 'attention');
  assert.equal(providerConnectionStatus(providers[2]), 'attention');
  assert.equal(
    providerConnectionStatus({
      id: 'never-checked',
      name: 'Never checked',
      provider_type: 'openai',
      is_active: true,
      credential_configured: true,
    }),
    'attention',
  );
  assert.equal(
    providerConnectionStatus({
      id: 'rate-limited',
      name: 'Rate-limited provider',
      provider_type: 'openrouter',
      is_active: true,
      credential_configured: true,
      health_status: 'rate_limited',
    }),
    'attention',
  );
  assert.equal(
    providerConnectionStatus({
      id: 'local-no-auth',
      name: 'Local no-auth runtime',
      provider_type: 'openai_compatible',
      auth_method: 'none',
      is_active: true,
      credential_configured: false,
      health_status: 'configuration_valid',
      llm_model: 'local-model',
      allowed_models: ['local-model'],
    }),
    'connected',
  );
  assert.equal(
    providerConnectionStatus(
      {
        id: 'azure-configured',
        name: 'Azure configured',
        provider_type: 'azure_openai',
        auth_method: 'api_key',
        is_active: true,
        credential_configured: true,
        llm_model: 'deployment-name',
        allowed_models: ['deployment-name'],
      },
      false,
    ),
    'connected',
  );
  assert.deepEqual(
    filterProviders(providers, '  ANTHRO ', 'all').map((provider) => provider.id),
    ['anthropic'],
  );
  assert.deepEqual(
    filterProviders(providers, 'open', 'connected').map((provider) => provider.id),
    ['openai'],
  );
  assert.deepEqual(
    filterProviders(providers, '', 'attention').map((provider) => provider.id),
    ['anthropic', 'embedding'],
  );
  assert.deepEqual(providerModelsFromProvider(providers[0]), [
    { id: 'gpt-5', capability: 'chat' },
    { id: 'gpt-5-mini', capability: 'chat' },
  ]);
  assert.deepEqual(providerModelsFromProvider(providers[2]), [
    { id: 'text-embedding-3-large', capability: 'embedding' },
  ]);
});

test('authoritative routing nulls do not fall back to provider defaults', () => {
  const provider = {
    id: 'provider-openai',
    name: 'OpenAI',
    provider_type: 'openai',
    llm_model: 'provider-default',
    llm_small_model: 'provider-fast',
    secondary_models: ['provider-fallback'],
  };
  const authoritative = providerRoutingOverview(provider, {
    tenant_id: 'tenant-a',
    revision: 3,
    roles: { default: null, fast: null, coding: null, vision: null },
    fallbacks: [],
    updated_at: '2026-07-18T00:00:00.000Z',
  });
  assert.deepEqual(authoritative.roles, {
    default: null,
    fast: null,
    coding: null,
    vision: null,
  });
  assert.deepEqual(authoritative.fallbacks, []);

  const projected = providerRoutingOverview(provider, null);
  assert.deepEqual(projected.roles.default, {
    provider_id: 'provider-openai',
    model_id: 'provider-default',
  });
  assert.deepEqual(projected.roles.fast, {
    provider_id: 'provider-openai',
    model_id: 'provider-fast',
  });
  assert.deepEqual(projected.fallbacks, [
    { provider_id: 'provider-openai', model_id: 'provider-fallback' },
  ]);
});

test('local routing candidates fail closed to runtime-supported ready providers', () => {
  const provider = {
    id: 'provider-openai',
    name: 'OpenAI',
    provider_type: 'openai',
    operation_type: 'llm',
    auth_method: 'api_key',
    is_active: true,
    is_enabled: true,
    base_url: 'https://api.openai.com/v1',
    llm_model: 'gpt-main',
    allowed_models: ['gpt-main', 'gpt-fast', 'gpt-fast'],
    credential_configured: true,
    health_status: 'configuration_valid',
  };
  assert.deepEqual(localRuntimeRoutingModelIds(provider), ['gpt-main', 'gpt-fast']);
  assert.deepEqual(localRuntimeRoutingModelIds({ ...provider, health_status: 'healthy' }), [
    'gpt-main',
    'gpt-fast',
  ]);
  assert.deepEqual(
    localRuntimeRoutingModelIds({
      ...provider,
      provider_type: 'openai_compatible',
      auth_method: 'none',
      credential_configured: false,
    }),
    ['gpt-main', 'gpt-fast'],
  );

  for (const unusable of [
    { ...provider, provider_type: 'gemini' },
    { ...provider, is_active: false },
    { ...provider, is_enabled: false },
    { ...provider, base_url: '' },
    { ...provider, llm_model: null },
    { ...provider, credential_configured: false },
    { ...provider, health_status: 'not_configured' },
  ]) {
    assert.deepEqual(localRuntimeRoutingModelIds(unusable), []);
  }
});

test('fallback availability ignores stale targets when a valid candidate remains', () => {
  const stale = { provider_id: 'provider-stale', model_id: 'removed-model' };
  const activeA = { provider_id: 'provider-openai', model_id: 'gpt-main' };
  const activeB = {
    provider_id: 'provider-anthropic',
    model_id: 'claude-main',
  };
  assert.equal(routingFallbackCanAdd([stale, activeA], [activeA, activeB], 8), true);
  assert.equal(routingFallbackCanAdd([stale, activeA, activeB], [activeA, activeB], 8), false);
  assert.equal(routingFallbackCanAdd([stale, activeA], [activeA, activeB], 2), false);
});

test('provider validation distinguishes configuration-only results from real probes', () => {
  assert.deepEqual(
    providerConfigurationValidationOutcome({
      id: 'azure-provider',
      name: 'Azure OpenAI',
      provider_type: 'azure_openai',
      health_status: null,
    }),
    {
      provider: null,
      status: 'configuration_valid',
      probed: false,
      detail: null,
      catalog: null,
    },
  );
  assert.deepEqual(
    providerValidationSignal({
      provider: null,
      status: 'configuration_valid',
      probed: false,
      detail: 'No external request was sent',
    }),
    { kind: 'configuration_only', status: 'configuration_valid' },
  );
  assert.deepEqual(
    providerValidationSignal({
      provider: null,
      status: 'healthy',
      probed: true,
      detail: null,
    }),
    { kind: 'external_probe', status: 'healthy' },
  );
  assert.equal(
    providerValidationSucceeded({
      provider: null,
      status: 'configuration_valid',
      probed: false,
      detail: 'No external request was sent',
    }),
    false,
  );
  assert.equal(
    providerValidationSucceeded({
      provider: null,
      status: 'healthy',
      probed: true,
      detail: null,
    }),
    true,
  );
  assert.equal(
    providerValidationAccepted(
      {
        provider: null,
        status: 'configuration_valid',
        probed: false,
        detail: 'No external request was sent',
      },
      false,
    ),
    true,
  );
  assert.equal(
    providerValidationAccepted(
      {
        provider: null,
        status: 'configuration_valid',
        probed: false,
        detail: 'No external request was sent',
      },
      true,
    ),
    false,
  );
  assert.equal(
    providerValidationAccepted(
      {
        provider: null,
        status: 'healthy',
        probed: true,
        detail: null,
      },
      true,
    ),
    true,
  );
});

test('provider wizard creates only active providers with an enabled model', () => {
  assert.match(addProviderDialogSource, /active: true/);
  assert.doesNotMatch(addProviderDialogSource, /active: false/);
  assert.match(addProviderDialogSource, /step === 3 && selectedModels\.size === 0/);
  assert.match(
    addProviderDialogSource,
    /nextTypes\.filter\([\s\S]{0,120}descriptor\.operationType === 'llm'/,
  );
  assert.doesNotMatch(
    addProviderDialogSource,
    /descriptor\.operationType === 'llm' && descriptor\.probeSupported/,
  );
  assert.match(addProviderDialogSource, /providerValidationAccepted\(validation, probeSupported\)/);
  assert.match(addProviderDialogSource, /setCatalog\(outcome\.catalog\)/);
  assert.match(addProviderDialogSource, /setSelectedModels\(new Set\(\)\)/);
  assert.doesNotMatch(
    addProviderDialogSource,
    /setSelectedModels\(new Set\([\s\S]{0,120}outcome\.catalog/,
  );
  assert.doesNotMatch(addProviderDialogSource, /providers\.testModelId/);
  assert.doesNotMatch(addProviderDialogSource, /onLoadCatalog/);
  assert.match(addProviderDialogSource, /if \(modelId === primaryModel\) return/);
  assert.match(addProviderDialogSource, /disabled=\{model\.id === primaryModel\}/);
  assert.match(addProviderDialogSource, /descriptor\.authMethods\.includes\('none'\)/);
  assert.match(
    addProviderDialogSource,
    /ollama:[\s\S]{0,100}baseUrl: 'http:\/\/127\.0\.0\.1:11434'/,
  );
  assert.match(
    addProviderDialogSource,
    /anthropic:[\s\S]{0,100}baseUrl: 'https:\/\/api\.anthropic\.com'/,
  );
  assert.doesNotMatch(
    addProviderDialogSource,
    /anthropic:[\s\S]{0,100}baseUrl: 'https:\/\/api\.anthropic\.com\/v1'/,
  );
});

test('provider authentication UI exposes truthful OAuth and environment-secret states', () => {
  assert.match(
    providerConnectionPanelSource,
    /const AUTH_METHOD_ORDER[\s\S]{0,180}'oauth'[\s\S]{0,180}'api_key'[\s\S]{0,180}'environment'[\s\S]{0,180}'none'/,
  );
  assert.match(
    providerConnectionPanelSource,
    /providerTypeDescriptor\?\.unavailableAuthMethods[\s\S]{0,260}authMethodUnavailable/,
  );
  assert.match(
    providerConnectionPanelSource,
    /provider-auth-option-unavailable[\s\S]{0,500}providers\.authUnavailable/,
  );
  assert.match(providerConnectionPanelSource, /aria-pressed=\{draft\.authMethod === authMethod\}/);
  assert.match(
    providerConnectionPanelSource,
    /selectAuthMethod[\s\S]{0,500}apiKey: ''[\s\S]{0,240}environmentVariable: ''[\s\S]{0,260}setValidation\(null\)/,
  );
  assert.match(providerConnectionPanelSource, /draft\.authMethod === 'environment'/);
  assert.match(providerConnectionPanelSource, /value=\{draft\.environmentVariable\}/);
  assert.match(providerConnectionPanelSource, /providers\.environmentSecretDescription/);
  assert.match(providerConnectionPanelSource, /providers\.oauthUnavailableDescription/);
  assert.match(
    providerConnectionPanelSource,
    /environmentSecretStatus =\s*validation\?\.probed === true[\s\S]{0,260}validation\?\.probed === false/,
  );
  assert.doesNotMatch(
    providerConnectionPanelSource,
    /environmentSecretStatus = validationAccepted|environmentSecretStatus = [\s\S]{0,100}validation \|\| error/,
  );
  assert.doesNotMatch(providerConnectionPanelSource, /window\.open|oauth\/authorize|startOAuth/);

  assert.match(addProviderDialogSource, /useState<LlmProviderAuthMethod>/);
  assert.match(addProviderDialogSource, /selectedDescriptor\?\.unavailableAuthMethods/);
  assert.match(addProviderDialogSource, /disabled=\{authMethodUnavailable\(method\)\}/);
  assert.match(
    addProviderDialogSource,
    /selectAuthMethod[\s\S]{0,500}setApiKey\(''\)[\s\S]{0,240}setEnvironmentVariable\(''\)[\s\S]{0,260}invalidateValidation\(\)/,
  );
  assert.match(addProviderDialogSource, /authMethod === 'environment'/);
  assert.match(addProviderDialogSource, /value=\{environmentVariable\}/);
  assert.match(addProviderDialogSource, /providers\.environmentSecretDescription/);
  assert.match(
    addProviderDialogSource,
    /environmentSecretStatus =\s*validation\?\.probed === true[\s\S]{0,260}validation\?\.probed === false/,
  );
  assert.doesNotMatch(
    addProviderDialogSource,
    /environmentSecretStatus = validationAccepted|environmentSecretStatus = [\s\S]{0,100}validation \|\| error/,
  );
  assert.doesNotMatch(addProviderDialogSource, /window\.open|oauth\/authorize|startOAuth/);

  assert.match(i18nSource, /'providers\.auth\.oauth': 'OAuth'/);
  assert.match(i18nSource, /'providers\.auth\.environment': 'Environment secret'/);
  assert.match(i18nSource, /'providers\.authUnavailable': 'Backend not configured'/);
  assert.match(i18nSource, /'providers\.auth\.oauth': 'OAuth'/);
  assert.match(i18nSource, /'providers\.auth\.environment': '环境密钥'/);
  assert.match(i18nSource, /'providers\.authUnavailable': '后端未配置'/);
});

test('provider editing preserves stored credentials only for the unchanged endpoint', () => {
  assert.match(
    providerConnectionPanelSource,
    /credentialRequiredForDraft[\s\S]{0,200}draft\.authMethod === 'api_key'[\s\S]{0,200}endpointChanged[\s\S]{0,100}!probeInput\.apiKey/,
  );
  assert.match(
    providerConnectionPanelSource,
    /validateDraft[\s\S]{0,160}editing && !\(draft\.authMethod === 'api_key' && !draftProbeInput\.apiKey\)/,
  );
  assert.match(providerConnectionPanelSource, /secretRequiredForEndpointChange/);
  assert.match(
    providerConnectionPanelSource,
    /probeSupported = providerTypeDescriptor\?\.probeSupported !== false/,
  );
  assert.match(providerConnectionPanelSource, /validationAvailable = authCapabilityAvailable/);
  assert.match(
    providerConnectionPanelSource,
    /providerValidationAccepted\(validation, probeSupported\)/,
  );
  assert.match(
    providerConnectionPanelSource,
    /currentProviderVerified[\s\S]{0,220}providerHealth === 'healthy'[\s\S]{0,160}providerHealth === 'connected'[\s\S]{0,160}providerHealth === 'ready'/,
  );
  assert.match(
    providerConnectionPanelSource,
    /currentProviderConfigured[\s\S]{0,220}!probeSupported[\s\S]{0,220}configuration_valid/,
  );
  assert.match(
    providerConnectionPanelSource,
    /!editing && !probeSupported[\s\S]{0,180}providerConfigurationValidationOutcome\(provider\)[\s\S]{0,220}onValidate\(/,
  );
  assert.match(providerConnectionPanelSource, /providers\.connectionPreviouslyVerified/);
  assert.match(
    i18nSource,
    /'providers\.connectionPreviouslyVerified':\s*'Authentication works and the provider responded\.'/,
  );
  assert.match(i18nSource, /'providers\.connectionPreviouslyVerified': '认证正常，供应商已响应。'/);
  assert.doesNotMatch(providerConnectionPanelSource, /disabled=\{!probeSupported \|\| !verified/);
  assert.match(
    providerConnectionPanelSource,
    /provider\.credential_configured === true[\s\S]{0,100}provider\.api_key_masked/,
  );
  assert.match(
    providerConnectionPanelSource,
    /provider\.credential_configured === false[\s\S]{0,120}providers\.credentialMissing[\s\S]{0,120}providers\.credentialUnknown/,
  );
  assert.match(
    providerStatusBadgeSource,
    /provider\.credential_configured === false && provider\.auth_method !== 'none'/,
  );
  assert.match(
    providerStatusBadgeSource,
    /provider\.credential_configured === undefined[\s\S]{0,100}providers\.status\.credentialUnknown/,
  );
  assert.match(
    providerStatusBadgeSource,
    /probeSupported[\s\S]{0,220}providers\.status\.configured/,
  );
  assert.match(
    providerOverviewPanelsSource,
    /provider\.auth_method === 'none' \|\| provider\.credential_configured === true/,
  );
  assert.match(
    providerOverviewPanelsSource,
    /provider\.credential_configured === false[\s\S]{0,100}providers\.credentialMissing[\s\S]{0,100}providers\.credentialUnknown/,
  );
  assert.doesNotMatch(
    providerOverviewPanelsSource,
    /provider\.credential_configured\s*\|\|\s*provider\.api_key_masked/,
  );
  assert.match(
    i18nSource,
    /Secrets stay in this device's system vault and are never returned by the API/,
  );
  assert.match(
    i18nSource,
    /Secrets are encrypted and stored by the service; the API never returns plaintext credentials/,
  );
  assert.match(i18nSource, /Save a credential securely for the current tenant/);
  assert.match(i18nSource, /密钥保存在本机系统凭据库中，API 永不回传密钥/);
  assert.match(i18nSource, /密钥由服务端加密保存，API 永不回传明文凭据/);
  assert.match(modelProviderWorkspaceSource, /mode=\{config\.mode\}/);
});

test('provider routing is policy-backed, cross-provider, and context safe', () => {
  assert.match(
    modelProviderWorkspaceCss,
    /\.model-provider-workspace\s*\{[\s\S]*line-height:\s*normal/,
  );
  assert.match(
    modelProviderWorkspaceSource,
    /routingScope\s*\?\s*t\('providers\.workspaceScope'\)/,
  );
  assert.match(providerOverviewPanelsSource, /const controller = new AbortController\(\)/);
  assert.match(providerOverviewPanelsSource, /onLoadUsage\(provider\.id, controller\.signal\)/);
  assert.match(providerOverviewPanelsSource, /return \(\) => controller\.abort\(\)/);
  assert.match(
    providerOverviewPanelsSource,
    /const ROUTING_ROLES: LlmRoutingRole\[\] = \['default', 'fast', 'coding', 'vision'\]/,
  );
  assert.doesNotMatch(providerOverviewPanelsSource, /CONFIGURABLE_LOCAL_ROUTING_ROLES/);
  assert.doesNotMatch(providerOverviewPanelsSource, /roleRuntimeUnavailable/);
  assert.doesNotMatch(providerOverviewPanelsSource, /fast: null, vision: null/);
  assert.match(
    providerOverviewPanelsSource,
    /mode === 'local'[\s\S]{0,100}localRuntimeRoutingModelIds\(item\)[\s\S]{0,100}providerEnabledModelIds\(item\)/,
  );
  assert.match(
    providerOverviewPanelsSource,
    /for \(const target of referencedTargets\)[\s\S]{0,600}available: false/,
  );
  assert.doesNotMatch(providerOverviewPanelsSource, /draft && enabledOptions\.length > 0/);
  assert.match(providerOverviewPanelsSource, /effectivePolicy && draft \? \(/);
  assert.match(providerOverviewPanelsSource, /providerRoutingOverview\(provider, policy\)/);
  assert.match(providerOverviewPanelsSource, /expectedRevision: policy\.revision/);
  assert.doesNotMatch(providerOverviewPanelsSource, /const moveFallback|\bmoveFallback\(index/);
  assert.doesNotMatch(providerOverviewPanelsSource, /provider-fallback-actions/);
  assert.match(providerOverviewPanelsSource, /removeFallback\(index\)/);
  assert.match(
    modelProviderWorkspaceCss,
    /provider-fallback-editor > div \{[^}]*grid-template-columns: 22px minmax\(0, 1fr\) 58px/,
  );
  assert.match(providerOverviewPanelsSource, /const MAX_ROUTING_FALLBACKS = 8/);
  assert.match(providerOverviewPanelsSource, /const MAX_ROUTING_FALLBACKS = 8/);
  assert.match(providerOverviewPanelsSource, /routingFallbackCanAdd\(/);
  assert.match(providerOverviewPanelsSource, /const saveRequestRef = useRef\(0\)/);
  assert.doesNotMatch(
    providerOverviewPanelsSource,
    /providerDraftFromProvider|providerMutationFromDraft|onRuntimeSelected/,
  );
  assert.doesNotMatch(modelProviderWorkspaceSource, /runtimeProvider|runtime_selected/);
  assert.doesNotMatch(providerOverviewPanelsSource, /runtimeSelected|localRuntimeSelected/);
  assert.match(modelProviderWorkspaceSource, /<ProviderUsagePanel[\s\S]{0,160}onLoadUsage=/);
  assert.doesNotMatch(modelProviderWorkspaceSource, /canReadUsage=\{canManage\}/);
  assert.match(
    modelProviderWorkspaceSource,
    /const configurationOnlyValidated =\s*!draftValidation\.probed && draftValidation\.status === 'configuration_valid'/,
  );
  assert.match(
    modelProviderWorkspaceSource,
    /if \(configurationOnlyValidated\)[\s\S]{0,700}else \{[\s\S]{0,240}checkLlmProvider/,
  );
  assert.match(
    modelProviderWorkspaceSource,
    /validationState === 'configured'[\s\S]{0,120}'providers\.providerConfigured'/,
  );
  assert.match(
    i18nSource,
    /'providers\.providerConfigured': '\{provider\} configuration validated'/,
  );
  assert.match(i18nSource, /'providers\.status\.configured': 'Configuration validated'/);
  assert.match(i18nSource, /'providers\.configurationValidated': 'Configuration validated'/);
  assert.match(i18nSource, /'providers\.providerConfigured': '\{provider\} 配置已校验'/);
  assert.match(i18nSource, /'providers\.status\.configured': '配置已校验'/);
  assert.match(i18nSource, /'providers\.configurationValidated': '配置已校验'/);
  assert.match(
    i18nSource,
    /'providers\.identityDescription':[\s\S]{0,120}'Provider credentials, endpoint health, available models, and workspace routing are managed independently\.'/,
  );
  assert.match(
    i18nSource,
    /'providers\.routingDescription':[\s\S]{0,120}'Routing is separate from provider credentials and can be changed without reconnecting\.'/,
  );
  assert.match(
    i18nSource,
    /'providers\.fastModelDescription': 'Titles, summaries, and lightweight transforms'/,
  );
  assert.match(
    i18nSource,
    /'providers\.visionModelDescription': 'Screenshots, diagrams, and visual QA'/,
  );
  assert.doesNotMatch(
    modelProviderWorkspaceSource,
    /llmProvider|llmBaseUrl|llmModel|llmApiKey|onConfigChange/,
  );
  assert.match(
    modelProviderWorkspaceSource,
    /getLlmProviderRoutingPolicy\([\s\S]{0,120}routingScope\.projectId,[\s\S]{0,80}routingScope\.workspaceId,[\s\S]{0,80}signal/,
  );
  assert.match(
    modelProviderWorkspaceSource,
    /config\.tenantId\.trim\(\)[\s\S]{0,220}config\.projectId\.trim\(\)[\s\S]{0,220}config\.workspaceId\.trim\(\)/,
  );
  assert.match(modelProviderWorkspaceSource, /providers\.routingScopeRequired/);
  assert.match(modelProviderWorkspaceSource, /Promise\.all\(\[/);
  assert.match(
    modelProviderWorkspaceSource,
    /requestClient\.updateLlmProviderRoutingPolicy\([\s\S]{0,180}projectId:\s*routingScope\.projectId[\s\S]{0,100}workspaceId:\s*routingScope\.workspaceId/,
  );
  assert.match(modelProviderWorkspaceSource, /setRoutingPolicy\(updated\)/);
  const updateProvider =
    modelProviderWorkspaceSource.match(
      /const updateProvider = useCallback\([\s\S]*?\n  \);\n\n  const saveProvider/,
    )?.[0] ?? '';
  const ordinarySave =
    modelProviderWorkspaceSource.match(
      /const saveProvider = useCallback\([\s\S]*?\n  \);\n\n  const saveRoutingPolicy/,
    )?.[0] ?? '';
  assert.match(updateProvider, /requestClient\.updateLlmProvider/);
  assert.doesNotMatch(updateProvider, /selectLlmRuntimeProvider|refreshRuntimeProjection/);
  assert.match(ordinarySave, /updateProvider/);
  assert.match(ordinarySave, /await refreshRuntimeProjection\(requestScope, requestClient\)/);
  assert.doesNotMatch(ordinarySave, /selectLlmRuntimeProvider/);
  assert.match(modelProviderWorkspaceSource, /onSave=\{saveRoutingPolicy\}/);
  assert.match(
    modelProviderWorkspaceSource,
    /const refreshRuntimeProjection = useCallback\([\s\S]{0,260}clientRef\.current !== requestClient[\s\S]{0,180}await onRuntimeStatusRefresh\(\)/,
  );
  assert.match(
    modelProviderWorkspaceSource,
    /catch \{[\s\S]{0,180}showToast\(t\('providers\.runtimeRefreshFailed'\)\)/,
  );
  const routingSave =
    modelProviderWorkspaceSource.match(
      /const saveRoutingPolicy = useCallback\([\s\S]*?\n  \);\n\n  const validateProvider/,
    )?.[0] ?? '';
  assert.doesNotMatch(routingSave, /\.updateLlmProvider\(|selectLlmRuntimeProvider/);
  assert.match(routingSave, /scopeKeyRef\.current !== requestScope/);
  assert.match(
    routingSave,
    /caught instanceof DesktopApiError[\s\S]{0,100}caught\.status !== 409[\s\S]{0,260}getLlmProviderRoutingPolicy\([\s\S]{0,160}routingScope\.workspaceId/,
  );
  assert.match(
    routingSave,
    /Promise\.all\(\[[\s\S]{0,180}listLlmProviders\(\)[\s\S]{0,260}getLlmProviderRoutingPolicy\([\s\S]{0,160}routingScope\.workspaceId/,
  );
  assert.match(routingSave, /setProviders\(modelProviders\)/);
  assert.match(routingSave, /await refreshRuntimeProjection\(requestScope, requestClient\)/);
  assert.match(
    settingsWindowSource,
    /key=\{`\$\{config\.mode\}\|\$\{config\.apiBaseUrl\}\|\$\{config\.tenantId\}\|\$\{config\.projectId\}\|\$\{config\.workspaceId\}`\}/,
  );
  assert.match(
    modelProviderWorkspaceSource,
    /!mountedRef\.current[\s\S]{0,100}scopeKeyRef\.current !== requestScope/,
  );
  assert.match(modelProviderWorkspaceSource, /const clientRef = useRef\(client\)/);
  assert.equal(
    (modelProviderWorkspaceSource.match(/const requestClient = client/g) ?? []).length >= 5,
    true,
  );
  assert.match(modelProviderWorkspaceSource, /clientRef\.current !== requestClient/);
  const scopeKeyDeclaration = modelProviderWorkspaceSource.match(/const scopeKey = .*;/)?.[0] ?? '';
  assert.doesNotMatch(scopeKeyDeclaration, /apiKey|localApiToken/);
  assert.match(scopeKeyDeclaration, /config\.projectId/);
  assert.match(scopeKeyDeclaration, /config\.workspaceId/);
  assert.match(
    modelProviderWorkspaceSource,
    /items\.filter\([\s\S]{0,120}!item\.operation_type \|\| item\.operation_type === 'llm'/,
  );
});

test('provider settings QA records preserve the authoritative LLM operation contract', () => {
  assert.doesNotMatch(providerSettingsQaSource, /operation_type:\s*'chat'/);
  assert.equal(
    [...providerSettingsQaSource.matchAll(/operation_type:\s*'llm'/g)].length >= 6,
    true,
  );
  assert.match(
    providerSettingsQaSource,
    /provider_type:\s*'openai'[\s\S]{0,220}auth_methods:\s*\['api_key', 'environment'\][\s\S]{0,160}unavailable_auth_methods:\s*\['oauth'\][\s\S]{0,120}probe_supported:\s*true/,
  );
  assert.match(
    providerSettingsQaSource,
    /provider_type:\s*'openai_compatible'[\s\S]{0,220}auth_methods:\s*\['api_key', 'environment', 'none'\]/,
  );
  assert.match(providerSettingsQaSource, /environment_variable:\s*'ANTHROPIC_API_KEY'/);
  assert.match(providerSettingsQaSource, /provider_type:\s*'openai_compatible'/);
  assert.doesNotMatch(providerSettingsQaSource, /provider_type:\s*'(?:gemini|openrouter|ollama)'/);
  assert.doesNotMatch(providerSettingsQaSource, /llmProvider|llmBaseUrl|llmModel|llmApiKey/);
  assert.match(providerSettingsQaSource, /mode: 'local'/);
  assert.match(providerSettingsQaSource, /path === '\/api\/v1\/llm-providers\/routing-policy'/);
  assert.match(providerSettingsQaSource, /draft\.expected_revision !== routingPolicy\.revision/);
  assert.doesNotMatch(providerSettingsQaSource, /draft\.roles\.fast !== null/);
  assert.doesNotMatch(providerSettingsQaSource, /draft\.roles\.vision !== null/);
  assert.match(providerSettingsQaSource, /url\.searchParams\.get\('project_id'\)/);
  assert.match(providerSettingsQaSource, /url\.searchParams\.get\('workspace_id'\)/);
  assert.match(providerSettingsQaSource, /draft\.project_id !== QA_PROJECT_ID/);
  assert.match(providerSettingsQaSource, /draft\.workspace_id !== QA_WORKSPACE_ID/);
  assert.match(providerSettingsQaSource, /status: configured \? 'healthy'/);
  assert.match(providerSettingsQaSource, /probed: true/);
  assert.match(providerSettingsQaSource, /models\\\/discover/);
});

test('routing policy client normalizes targets and sends optimistic revisions', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    const revision = init?.method === 'PUT' ? 8 : 7;
    return new Response(
      JSON.stringify({
        tenant_id: ' tenant-a ',
        project_id: ' project-a ',
        workspace_id: ' workspace-a ',
        revision,
        roles: {
          default: { provider_id: ' provider-openai ', model_id: ' gpt-5 ' },
          fast: { provider_id: 'provider-openai', model_id: 'gpt-5-mini' },
          coding: {
            provider_id: 'provider-anthropic',
            model_id: 'claude-code',
          },
          vision: { provider_id: 'provider-google', model_id: 'gemini-vision' },
        },
        fallbacks: [{ provider_id: ' provider-anthropic ', model_id: ' claude-fast ' }],
        updated_at: '2026-07-18T00:00:00.000Z',
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };

  try {
    const local = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      mode: 'local',
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'local-user-session',
    });
    const policy = await local.getLlmProviderRoutingPolicy('project-a', 'workspace-a');
    assert.deepEqual(policy, {
      tenant_id: 'tenant-a',
      project_id: 'project-a',
      workspace_id: 'workspace-a',
      revision: 7,
      roles: {
        default: { provider_id: 'provider-openai', model_id: 'gpt-5' },
        fast: { provider_id: 'provider-openai', model_id: 'gpt-5-mini' },
        coding: { provider_id: 'provider-anthropic', model_id: 'claude-code' },
        vision: { provider_id: 'provider-google', model_id: 'gemini-vision' },
      },
      fallbacks: [{ provider_id: 'provider-anthropic', model_id: 'claude-fast' }],
      updated_at: '2026-07-18T00:00:00.000Z',
    });
    const updated = await local.updateLlmProviderRoutingPolicy({
      projectId: 'project-a',
      workspaceId: 'workspace-a',
      roles: policy.roles,
      fallbacks: policy.fallbacks,
      expectedRevision: policy.revision,
    });
    assert.equal(updated.revision, 8);
    assert.equal(
      calls[0]?.input,
      'http://127.0.0.1:8088/api/v1/llm-providers/routing-policy?project_id=project-a&workspace_id=workspace-a',
    );
    assert.equal(calls[1]?.init?.method, 'PUT');
    assert.deepEqual(JSON.parse(String(calls[1]?.init?.body)), {
      project_id: 'project-a',
      workspace_id: 'workspace-a',
      roles: policy.roles,
      fallbacks: policy.fallbacks,
      expected_revision: 7,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Desktop client exposes workspace routing without a second runtime-selection mutation', () => {
  const local = new DesktopApiClient({
    ...DEFAULT_CONFIG,
    mode: 'local',
    apiBaseUrl: 'http://127.0.0.1:8088',
    apiKey: 'local-user-session',
    localApiToken: 'launch-capability',
  });

  assert.equal(typeof local.getLlmProviderRoutingPolicy, 'function');
  assert.equal(typeof local.updateLlmProviderRoutingPolicy, 'function');
  assert.equal(typeof local.selectLlmRuntimeProvider, 'undefined');
  assert.doesNotMatch(apiClientSource, /runtime-selection/);
  assert.doesNotMatch(apiClientSource, /runtime_selected|runtimeSelected/);
});

test('provider adapters use PUT, Rust revision guards, and canonical health checks', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    const url = String(input);
    if (url.endsWith('/health-check')) {
      return new Response(
        JSON.stringify({
          provider_id: url.includes('local-runtime')
            ? 'local-runtime'
            : '11111111-2222-4333-8444-555555555555',
          status: 'healthy',
          probed: true,
          last_check: '2026-07-13T10:00:00Z',
          response_time_ms: 42,
          error_message: null,
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    return new Response(
      JSON.stringify({
        id: url.includes('local-runtime')
          ? 'local-runtime'
          : '11111111-2222-4333-8444-555555555555',
        name: 'Provider',
        provider_type: 'openai',
        ...(url.includes('local-runtime')
          ? {
              authMethod: 'api_key',
              credentialConfigured: true,
              version: 8,
            }
          : {
              auth_method: 'api_key',
              credential_configured: true,
              revision: 8,
            }),
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };

  try {
    const local = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      mode: 'local',
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'local-user-session',
      localApiToken: 'launch-capability',
    });
    const cloud = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      mode: 'cloud',
      apiBaseUrl: 'https://api.example.test',
      apiKey: 'cloud-user-session',
    });
    const mutation = {
      name: 'Provider',
      providerType: 'openai',
      authMethod: 'api_key',
      environmentVariable: 'MUST_NOT_BE_SENT',
      baseUrl: 'https://llm.example.test/v1',
      primaryModel: 'gpt-test',
      allowedModels: ['gpt-test'],
      active: true,
      expectedRevision: 7,
    };

    const localUpdated = await local.updateLlmProvider('local-runtime', mutation);
    const localValidation = await local.checkLlmProvider('local-runtime', 8);
    await cloud.updateLlmProvider('11111111-2222-4333-8444-555555555555', mutation);
    const cloudValidation = await cloud.checkLlmProvider('11111111-2222-4333-8444-555555555555', 8);

    assert.equal(calls[0]?.init?.method, 'PUT');
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      name: 'Provider',
      provider_type: 'openai',
      auth_method: 'api_key',
      base_url: 'https://llm.example.test/v1',
      llm_model: 'gpt-test',
      allowed_models: ['gpt-test'],
      is_active: true,
      expected_revision: 7,
    });
    assert.deepEqual(
      {
        authMethod: localUpdated.auth_method,
        credentialConfigured: localUpdated.credential_configured,
        revision: localUpdated.revision,
      },
      {
        authMethod: 'api_key',
        credentialConfigured: true,
        revision: 8,
      },
    );
    assert.equal(String(calls[1]?.input).endsWith('/local-runtime/health-check'), true);
    assert.deepEqual(JSON.parse(String(calls[1]?.init?.body)), {
      expected_revision: 8,
    });
    assert.equal(localValidation.probed, true);
    assert.equal(localValidation.status, 'healthy');
    assert.equal(calls[2]?.init?.method, 'PUT');
    assert.deepEqual(JSON.parse(String(calls[2]?.init?.body)), {
      name: 'Provider',
      provider_type: 'openai',
      auth_method: 'api_key',
      base_url: 'https://llm.example.test/v1',
      llm_model: 'gpt-test',
      allowed_models: ['gpt-test'],
      is_active: true,
      expected_revision: 7,
    });
    assert.equal(cloudValidation.probed, true);
    assert.equal(cloudValidation.status, 'healthy');
    assert.deepEqual(JSON.parse(String(calls[3]?.init?.body)), {});
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('provider create adapters send auth method and omit mismatched credentials', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        id: calls.length === 1 ? 'provider-local' : 'provider-cloud',
        name: 'New provider',
        provider_type: 'openai_compatible',
      }),
      { status: 201, headers: { 'content-type': 'application/json' } },
    );
  };

  try {
    const local = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      mode: 'local',
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'local-user-session',
      localApiToken: 'launch-capability',
    });
    const cloud = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      mode: 'cloud',
      apiBaseUrl: 'https://api.example.test',
      apiKey: 'cloud-user-session',
    });
    const input = {
      name: 'New provider',
      providerType: 'openai_compatible',
      authMethod: 'none',
      baseUrl: 'http://127.0.0.1:11434/v1',
      primaryModel: 'qwen3-coder',
      allowedModels: ['qwen3-coder'],
      active: true,
      apiKey: 'runtime-only-secret',
      environmentVariable: 'MUST_NOT_BE_SENT',
      oauthToken: 'oauth-token-must-not-be-sent',
    };

    await local.createLlmProvider(input);
    await cloud.createLlmProvider(input);

    assert.equal(String(calls[0]?.input), 'http://127.0.0.1:8088/api/v1/llm-providers/');
    assert.equal(calls[0]?.init?.method, 'POST');
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      name: 'New provider',
      provider_type: 'openai_compatible',
      base_url: 'http://127.0.0.1:11434/v1',
      llm_model: 'qwen3-coder',
      allowed_models: ['qwen3-coder'],
      is_active: true,
      auth_method: 'none',
    });
    assert.equal(String(calls[1]?.input), 'https://api.example.test/api/v1/llm-providers/');
    assert.equal(calls[1]?.init?.method, 'POST');
    assert.deepEqual(JSON.parse(String(calls[1]?.init?.body)), {
      name: 'New provider',
      provider_type: 'openai_compatible',
      base_url: 'http://127.0.0.1:11434/v1',
      llm_model: 'qwen3-coder',
      allowed_models: ['qwen3-coder'],
      is_active: true,
      auth_method: 'none',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('environment provider requests send only variable references in local and cloud modes', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    if (String(input).endsWith('/test-connection')) {
      return new Response(JSON.stringify({ status: 'healthy', probed: true }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    return new Response(
      JSON.stringify({
        id: `provider-${calls.length}`,
        name: 'Environment provider',
        provider_type: 'openai',
        auth_method: 'environment',
        environment_variable: 'OPENAI_API_KEY',
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };

  try {
    const clients = [
      new DesktopApiClient({
        ...DEFAULT_CONFIG,
        mode: 'local',
        apiBaseUrl: 'http://127.0.0.1:8088',
        apiKey: 'local-user-session',
        localApiToken: 'launch-capability',
      }),
      new DesktopApiClient({
        ...DEFAULT_CONFIG,
        mode: 'cloud',
        apiBaseUrl: 'https://api.example.test',
        apiKey: 'cloud-user-session',
      }),
    ];
    const credentialInput = {
      authMethod: 'environment',
      environmentVariable: '  OPENAI_API_KEY  ',
      apiKey: 'api-key-must-not-be-sent',
      environmentValue: 'environment-value-must-not-be-sent',
      oauthToken: 'oauth-token-must-not-be-sent',
    };

    for (const client of clients) {
      await client.createLlmProvider({
        ...credentialInput,
        name: 'Environment provider',
        providerType: 'openai',
        baseUrl: 'https://api.openai.com/v1',
        primaryModel: 'gpt-test',
        allowedModels: ['gpt-test'],
        active: true,
      });
      await client.updateLlmProvider('environment-provider', {
        ...credentialInput,
        name: 'Environment provider',
        providerType: 'openai',
        baseUrl: 'https://api.openai.com/v1',
        primaryModel: 'gpt-test',
        allowedModels: ['gpt-test'],
        active: true,
        expectedRevision: 4,
      });
      await client.testLlmProviderDraft({
        ...credentialInput,
        name: 'Environment provider',
        providerType: 'openai',
        baseUrl: 'https://api.openai.com/v1',
        active: true,
      });
    }

    assert.equal(calls.length, 6);
    for (const call of calls) {
      const body = JSON.parse(String(call.init?.body));
      assert.equal(body.auth_method, 'environment');
      assert.equal(body.environment_variable, 'OPENAI_API_KEY');
      for (const forbiddenKey of ['api_key', 'environment_value', 'oauth_token']) {
        assert.equal(Object.hasOwn(body, forbiddenKey), false);
      }
      assert.equal(JSON.stringify(body).includes('must-not-be-sent'), false);
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('OAuth provider mutations fail closed before making a request', async () => {
  let requestCount = 0;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    requestCount += 1;
    return new Response('{}', {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const clients = [
      new DesktopApiClient({
        ...DEFAULT_CONFIG,
        mode: 'local',
        apiBaseUrl: 'http://127.0.0.1:8088',
        apiKey: 'local-user-session',
        localApiToken: 'launch-capability',
      }),
      new DesktopApiClient({
        ...DEFAULT_CONFIG,
        mode: 'cloud',
        apiBaseUrl: 'https://api.example.test',
        apiKey: 'cloud-user-session',
      }),
    ];
    const oauthCredential = {
      authMethod: 'oauth',
      apiKey: 'api-key-must-not-be-sent',
      environmentVariable: 'MUST_NOT_BE_SENT',
      oauthToken: 'oauth-token-must-not-be-sent',
    };

    for (const client of clients) {
      await assert.rejects(
        client.createLlmProvider({
          ...oauthCredential,
          name: 'OAuth provider',
          providerType: 'anthropic',
          baseUrl: 'https://api.anthropic.com',
          primaryModel: 'claude-test',
          allowedModels: ['claude-test'],
          active: true,
        }),
        /OAuth provider authentication is not available/,
      );
      await assert.rejects(
        client.updateLlmProvider('oauth-provider', {
          ...oauthCredential,
          name: 'OAuth provider',
          providerType: 'anthropic',
          baseUrl: 'https://api.anthropic.com',
          primaryModel: 'claude-test',
          allowedModels: ['claude-test'],
          active: true,
          expectedRevision: 2,
        }),
        /OAuth provider authentication is not available/,
      );
      await assert.rejects(
        client.testLlmProviderDraft({
          ...oauthCredential,
          name: 'OAuth provider',
          providerType: 'anthropic',
          baseUrl: 'https://api.anthropic.com',
          active: true,
        }),
        /OAuth provider authentication is not available/,
      );
    }
    assert.equal(requestCount, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('provider responses normalize compatibility fields explicitly', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify([
        {
          id: 'local-ollama',
          name: 'Local Ollama',
          providerType: 'ollama',
          authMethod: 'none',
          credentialConfigured: false,
          runtimeSelected: true,
          version: 12,
        },
        {
          id: 'legacy-openai',
          name: 'Legacy OpenAI',
          provider_type: 'openai',
          credential_configured: false,
          api_key_masked: 'sk-sensitive-mask-source',
          api_key: 'response-secret-must-be-dropped',
          api_key_encrypted: 'response-ciphertext-must-be-dropped',
          credential: 'response-credential-must-be-dropped',
          secret: 'response-secret-field-must-be-dropped',
        },
        {
          id: 'persisted-openai',
          name: 'Persisted OpenAI',
          provider_type: 'openai',
          auth_method: 'api_key',
          credential_configured: true,
          api_key_masked: 'sk-server-value-must-not-be-retained',
          credential_source: 'system_vault',
          health_status: 'configuration_valid',
          revision: 4,
        },
        {
          id: 'unknown-openai',
          name: 'Unknown OpenAI',
          provider_type: 'openai',
          auth_method: 'api_key',
          api_key_masked: 'sk-untrusted-legacy-mask',
        },
        {
          id: 'environment-openai',
          name: 'Environment OpenAI',
          provider_type: 'openai',
          auth_method: 'environment',
          environment_variable: 'OPENAI_API_KEY',
          credential_configured: true,
          environment_value: 'environment-value-must-not-be-retained',
        },
        {
          id: 'oauth-anthropic',
          name: 'OAuth Anthropic',
          provider_type: 'anthropic',
          auth_method: 'oauth',
          credential_configured: true,
          oauth_token: 'oauth-token-must-not-be-retained',
        },
      ]),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );

  try {
    const local = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      mode: 'local',
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'local-user-session',
      localApiToken: 'launch-capability',
    });
    const providers = await local.listLlmProviders();
    assert.deepEqual(
      providers.map((provider) => ({
        id: provider.id,
        providerType: provider.provider_type,
        authMethod: provider.auth_method,
        credentialConfigured: provider.credential_configured,
        revision: provider.revision,
      })),
      [
        {
          id: 'local-ollama',
          providerType: 'ollama',
          authMethod: 'none',
          credentialConfigured: false,
          revision: 12,
        },
        {
          id: 'legacy-openai',
          providerType: 'openai',
          authMethod: undefined,
          credentialConfigured: false,
          revision: 0,
        },
        {
          id: 'persisted-openai',
          providerType: 'openai',
          authMethod: 'api_key',
          credentialConfigured: true,
          revision: 4,
        },
        {
          id: 'unknown-openai',
          providerType: 'openai',
          authMethod: 'api_key',
          credentialConfigured: undefined,
          revision: 0,
        },
        {
          id: 'environment-openai',
          providerType: 'openai',
          authMethod: 'environment',
          credentialConfigured: true,
          revision: 0,
        },
        {
          id: 'oauth-anthropic',
          providerType: 'anthropic',
          authMethod: 'oauth',
          credentialConfigured: true,
          revision: 0,
        },
      ],
    );
    assert.equal(Object.hasOwn(providers[0], 'runtime_selected'), false);
    const legacy = providers[1];
    assert.equal(legacy.api_key_masked, null);
    for (const forbiddenKey of ['api_key', 'api_key_encrypted', 'credential', 'secret']) {
      assert.equal(Object.hasOwn(legacy, forbiddenKey), false);
    }
    assert.equal(JSON.stringify(providers).includes('response-secret-must-be-dropped'), false);
    const persisted = providers[2];
    assert.equal(persisted.api_key_masked, '••••••••••••');
    assert.equal(persisted.credential_source, 'system_vault');
    assert.equal(providerDraftFromProvider(persisted).apiKey, '');
    const unknown = providers[3];
    assert.equal(unknown.credential_configured, undefined);
    assert.equal(unknown.api_key_masked, null);
    const environment = providers[4];
    assert.equal(environment.environment_variable, 'OPENAI_API_KEY');
    assert.equal(providerDraftFromProvider(environment).environmentVariable, 'OPENAI_API_KEY');
    const oauth = providers[5];
    assert.equal(oauth.auth_method, 'oauth');
    assert.equal(providerDraftFromProvider(oauth).authMethod, 'oauth');
    assert.equal(JSON.stringify(providers).includes('must-not-be-retained'), false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('provider discovery and usage use the same local and cloud contracts', async () => {
  const calls = [];
  const requestBodies = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push(String(input));
    if (init?.body) requestBodies.push(JSON.parse(String(init.body)));
    const url = String(input);
    if (url.endsWith('/types')) {
      const types = url.startsWith('http://127.0.0.1:8088')
        ? [
            {
              provider_type: 'openai',
              operation_type: 'llm',
              probe_supported: true,
              auth_methods: ['api_key'],
            },
            {
              provider_type: 'anthropic',
              operation_type: 'llm',
              probe_supported: true,
              auth_methods: ['oauth', 'api_key', 'oauth', 'unsupported'],
            },
            {
              provider_type: 'azure_openai',
              operation_type: 'llm',
              probe_supported: false,
              auth_methods: ['api_key'],
            },
            {
              provider_type: 'ollama',
              operation_type: 'llm',
              probe_supported: true,
              auth_methods: ['none'],
            },
            {
              provider_type: 'dashscope_embedding',
              operation_type: 'embedding',
              probe_supported: true,
              auth_methods: ['api_key'],
            },
          ]
        : [
            {
              provider_type: 'openai',
              auth_methods: ['environment', 'api_key'],
            },
            { provider_type: 'ollama', auth_methods: ['none'] },
            {
              provider_type: 'anthropic',
              auth_methods: ['api_key', 'environment'],
              unavailable_auth_methods: ['oauth'],
            },
          ];
      return new Response(JSON.stringify(types), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    if (url.endsWith('/provider-local/models/discover')) {
      return new Response(
        JSON.stringify({
          provider_type: 'openai',
          provider_id: 'provider-local',
          availability: 'available',
          source: 'provider-api',
          discovered_at: '2026-07-14T00:00:00Z',
          detail: null,
          models: {
            chat: ['gpt-local'],
            embedding: [],
            rerank: [],
          },
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    if (url.endsWith('/models/openai')) {
      return new Response(
        JSON.stringify({
          provider_type: 'openai',
          source: 'models.dev',
          models: {
            chat: ['gpt-local'],
            embedding: [],
            rerank: [],
          },
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    if (url.endsWith('/models/anthropic')) {
      return new Response(
        JSON.stringify({
          provider_type: 'anthropic',
          source: 'models.dev',
          models: {
            chat: ['claude-sonnet-4'],
            embedding: [],
            rerank: ['rerank-test'],
          },
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    if (url.endsWith('/provider-cloud/usage')) {
      return new Response(
        JSON.stringify({
          provider_id: 'provider-cloud',
          tenant_id: null,
          statistics: [
            {
              provider_id: 'provider-cloud',
              tenant_id: null,
              operation_type: 'llm',
              total_requests: 12,
              total_prompt_tokens: 100,
              total_completion_tokens: 25,
              total_tokens: 125,
              total_cost_usd: 0.5,
              avg_response_time_ms: 42,
              first_request_at: '2026-07-01T00:00:00Z',
              last_request_at: '2026-07-14T00:00:00Z',
            },
          ],
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    if (url.endsWith('/provider-local/usage')) {
      return new Response(
        JSON.stringify({
          provider_id: 'provider-local',
          tenant_id: null,
          statistics: [
            {
              provider_id: 'provider-local',
              tenant_id: null,
              operation_type: 'llm',
              total_requests: 2,
              total_prompt_tokens: 10,
              total_completion_tokens: 4,
              total_tokens: 14,
              total_cost_usd: null,
              avg_response_time_ms: 21,
              first_request_at: '2026-07-14T00:00:00Z',
              last_request_at: '2026-07-14T00:01:00Z',
            },
          ],
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    return new Response('Not Found', { status: 404 });
  };

  try {
    const local = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      mode: 'local',
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'local-user-session',
      localApiToken: 'launch-capability',
    });
    const cloud = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      mode: 'cloud',
      apiBaseUrl: 'https://api.example.test',
      apiKey: 'cloud-user-session',
    });

    assert.deepEqual(await local.listLlmProviderTypes(), [
      {
        providerType: 'openai',
        authMethods: ['api_key'],
        unavailableAuthMethods: [],
        operationType: 'llm',
        probeSupported: true,
        source: 'local_runtime',
      },
      {
        providerType: 'anthropic',
        authMethods: ['oauth', 'api_key'],
        unavailableAuthMethods: ['oauth'],
        operationType: 'llm',
        probeSupported: true,
        source: 'local_runtime',
      },
      {
        providerType: 'azure_openai',
        authMethods: ['api_key'],
        unavailableAuthMethods: [],
        operationType: 'llm',
        probeSupported: false,
        source: 'local_runtime',
      },
      {
        providerType: 'ollama',
        authMethods: ['none'],
        unavailableAuthMethods: [],
        operationType: 'llm',
        probeSupported: true,
        source: 'local_runtime',
      },
      {
        providerType: 'dashscope_embedding',
        authMethods: ['api_key'],
        unavailableAuthMethods: [],
        operationType: 'embedding',
        probeSupported: true,
        source: 'local_runtime',
      },
    ]);
    assert.deepEqual(await local.discoverLlmProviderModels('provider-local', 7), {
      providerType: 'openai',
      providerId: 'provider-local',
      availability: 'available',
      source: 'provider-api',
      discoveredAt: '2026-07-14T00:00:00Z',
      detail: null,
      models: [{ id: 'gpt-local', capability: 'chat' }],
    });
    assert.deepEqual(await local.getLlmProviderUsage('provider-local'), {
      provider_id: 'provider-local',
      tenant_id: null,
      availability: 'available',
      statistics: [
        {
          provider_id: 'provider-local',
          tenant_id: null,
          operation_type: 'llm',
          total_requests: 2,
          total_prompt_tokens: 10,
          total_completion_tokens: 4,
          total_tokens: 14,
          total_cost_usd: null,
          avg_response_time_ms: 21,
          first_request_at: '2026-07-14T00:00:00Z',
          last_request_at: '2026-07-14T00:01:00Z',
        },
      ],
    });
    assert.deepEqual(calls, [
      'http://127.0.0.1:8088/api/v1/llm-providers/types',
      'http://127.0.0.1:8088/api/v1/llm-providers/provider-local/models/discover',
      'http://127.0.0.1:8088/api/v1/llm-providers/provider-local/usage',
    ]);
    assert.deepEqual(requestBodies, [{ expected_revision: 7 }]);

    assert.deepEqual(await cloud.listLlmProviderTypes(), [
      {
        providerType: 'openai',
        authMethods: ['environment', 'api_key'],
        unavailableAuthMethods: [],
        operationType: 'llm',
        probeSupported: true,
        source: 'cloud_api',
      },
      {
        providerType: 'ollama',
        authMethods: ['none'],
        unavailableAuthMethods: [],
        operationType: 'llm',
        probeSupported: true,
        source: 'cloud_api',
      },
      {
        providerType: 'anthropic',
        authMethods: ['api_key', 'environment'],
        unavailableAuthMethods: ['oauth'],
        operationType: 'llm',
        probeSupported: true,
        source: 'cloud_api',
      },
    ]);
    assert.deepEqual(await cloud.listLlmProviderModels('anthropic'), {
      providerType: 'anthropic',
      providerId: null,
      availability: 'available',
      source: 'models.dev',
      discoveredAt: null,
      detail: null,
      models: [
        { id: 'claude-sonnet-4', capability: 'chat' },
        { id: 'rerank-test', capability: 'rerank' },
      ],
    });
    assert.deepEqual(await cloud.getLlmProviderUsage('provider-cloud'), {
      provider_id: 'provider-cloud',
      tenant_id: null,
      availability: 'available',
      statistics: [
        {
          provider_id: 'provider-cloud',
          tenant_id: null,
          operation_type: 'llm',
          total_requests: 12,
          total_prompt_tokens: 100,
          total_completion_tokens: 25,
          total_tokens: 125,
          total_cost_usd: 0.5,
          avg_response_time_ms: 42,
          first_request_at: '2026-07-01T00:00:00Z',
          last_request_at: '2026-07-14T00:00:00Z',
        },
      ],
    });
    assert.deepEqual(calls, [
      'http://127.0.0.1:8088/api/v1/llm-providers/types',
      'http://127.0.0.1:8088/api/v1/llm-providers/provider-local/models/discover',
      'http://127.0.0.1:8088/api/v1/llm-providers/provider-local/usage',
      'https://api.example.test/api/v1/llm-providers/types',
      'https://api.example.test/api/v1/llm-providers/models/anthropic',
      'https://api.example.test/api/v1/llm-providers/provider-cloud/usage',
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('provider usage preserves an authoritative unavailable state instead of inventing zero usage', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        provider_id: 'provider-local',
        tenant_id: 'tenant-a',
        availability: 'unavailable',
        statistics: [],
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );

  try {
    const local = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      mode: 'local',
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'local-user-session',
      localApiToken: 'launch-capability',
    });
    assert.deepEqual(await local.getLlmProviderUsage('provider-local'), {
      provider_id: 'provider-local',
      tenant_id: 'tenant-a',
      availability: 'unavailable',
      statistics: [],
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('provider catalogs preserve static fallback provenance and reject empty unscoped catalogs', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input) => {
    const url = String(input);
    if (url.endsWith('/models/openai')) {
      return new Response(
        JSON.stringify({
          provider_type: 'openai',
          source: 'static-fallback',
          models: {
            chat: ['gpt-4o-mini'],
            embedding: [],
            rerank: [],
          },
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    return new Response(
      JSON.stringify({
        provider_type: 'custom-cloud',
        source: null,
        models: {
          chat: [],
          embedding: [],
          rerank: [],
        },
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      mode: 'cloud',
      apiBaseUrl: 'https://api.example.test',
      apiKey: 'cloud-user-session',
    });

    assert.deepEqual(await client.listLlmProviderModels('openai'), {
      providerType: 'openai',
      providerId: null,
      availability: 'available',
      source: 'static-fallback',
      discoveredAt: null,
      detail: null,
      models: [{ id: 'gpt-4o-mini', capability: 'chat' }],
    });
    assert.deepEqual(await client.listLlmProviderModels('custom-cloud'), {
      providerType: 'custom-cloud',
      providerId: null,
      availability: 'unavailable',
      source: null,
      discoveredAt: null,
      detail: null,
      models: [],
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('provider catalog UIs identify static fallback models as built-in suggestions', () => {
  assert.match(providerModelsPanelSource, /catalog\?\.source === 'static-fallback'/);
  assert.match(
    providerModelsPanelSource,
    /catalogIsStaticFallback \? 'staticFallback' : 'catalog'/,
  );
  assert.match(
    providerModelsPanelSource,
    /catalogIsStaticFallback[\s\S]{0,160}'providers\.staticModelCounts'/,
  );
  assert.match(addProviderDialogSource, /catalog\?\.source === 'static-fallback'/);
  assert.match(
    addProviderDialogSource,
    /catalogIsStaticFallback[\s\S]{0,160}'providers\.enableSuggestedModels'/,
  );
  assert.doesNotMatch(addProviderDialogSource, /toggleDiscoveredModel/);

  assert.match(
    i18nSource,
    /'providers\.staticCatalogDescription':\s*'Models from the built-in static catalog are suggestions, not live discovery\.'/,
  );
  assert.match(
    i18nSource,
    /'providers\.staticCatalogDescription': '模型来自内置静态目录，仅作为建议，并非实时发现。'/,
  );
  assert.match(i18nSource, /'providers\.source\.staticFallback': 'Built-in static catalog'/);
  assert.match(i18nSource, /'providers\.source\.staticFallback': '内置静态目录'/);
});

test('live provider discovery remains scoped to the saved connection', () => {
  assert.match(
    modelProviderWorkspaceSource,
    /config\.mode === 'local'[\s\S]{0,180}discoverLlmProviderModels\(targetProvider\.id, targetProvider\.revision \?\? 0\)[\s\S]{0,180}listLlmProviderModels\(targetProvider\.provider_type\)/,
  );
  assert.match(providerModelsPanelSource, /onLoadCatalogRef\.current\(provider\)/);
  assert.doesNotMatch(providerModelsPanelSource, /setEnabled\([\s\S]{0,180}nextCatalog\.models/);
  assert.match(i18nSource, /Checks authentication, endpoint connectivity, and model discovery\./);
  assert.match(i18nSource, /检查认证、端点连通性与模型发现。/);
});

test('draft validation requires explicit probe evidence and can return a discovered catalog', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    const local = String(input).startsWith('http://127.0.0.1:8088');
    return new Response(
      JSON.stringify({
        provider_id: 'temporary-probe',
        status: local ? 'healthy' : 'unhealthy',
        probed: true,
        detail: local ? 'Authentication and endpoint connectivity verified.' : null,
        last_check: '2026-07-14T10:00:00Z',
        response_time_ms: local ? 31 : 37,
        error_message: local ? null : 'model was not available',
        catalog: local
          ? {
              provider_type: 'custom_gateway',
              provider_id: null,
              availability: 'available',
              source: 'provider-api',
              discovered_at: '2026-07-14T10:00:00Z',
              detail: null,
              models: { chat: ['gateway-model'], embedding: [], rerank: [] },
            }
          : null,
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };

  try {
    const local = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      mode: 'local',
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'local-user-session',
      localApiToken: 'launch-capability',
    });
    const cloud = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      mode: 'cloud',
      apiBaseUrl: 'https://api.example.test',
      apiKey: 'cloud-user-session',
    });
    const input = {
      name: 'Draft provider',
      providerType: 'custom_gateway',
      authMethod: 'api_key',
      baseUrl: 'https://gateway.example.test/v1',
      active: true,
      apiKey: 'draft-secret',
      environmentVariable: 'MUST_NOT_BE_SENT',
      oauthToken: 'oauth-token-must-not-be-sent',
    };

    assert.deepEqual(await local.testLlmProviderDraft(input), {
      provider: null,
      status: 'healthy',
      probed: true,
      detail: 'Authentication and endpoint connectivity verified.',
      lastChecked: '2026-07-14T10:00:00Z',
      responseTimeMs: 31,
      errorMessage: null,
      catalog: {
        providerType: 'custom_gateway',
        providerId: null,
        availability: 'available',
        source: 'provider-api',
        discoveredAt: '2026-07-14T10:00:00Z',
        detail: null,
        models: [{ id: 'gateway-model', capability: 'chat' }],
      },
    });
    assert.deepEqual(await cloud.testLlmProviderDraft(input), {
      provider: null,
      status: 'unhealthy',
      probed: true,
      detail: null,
      lastChecked: '2026-07-14T10:00:00Z',
      responseTimeMs: 37,
      errorMessage: 'model was not available',
      catalog: null,
    });
    assert.equal(calls[0]?.input, 'http://127.0.0.1:8088/api/v1/llm-providers/test-connection');
    assert.equal(calls[0]?.init?.method, 'POST');
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      name: 'Draft provider',
      provider_type: 'custom_gateway',
      base_url: 'https://gateway.example.test/v1',
      is_active: true,
      auth_method: 'api_key',
      api_key: 'draft-secret',
    });
    assert.equal(calls[1]?.input, 'https://api.example.test/api/v1/llm-providers/test-connection');
    assert.equal(calls[1]?.init?.method, 'POST');
    assert.deepEqual(JSON.parse(String(calls[1]?.init?.body)), {
      name: 'Draft provider',
      provider_type: 'custom_gateway',
      base_url: 'https://gateway.example.test/v1',
      is_active: true,
      auth_method: 'api_key',
      api_key: 'draft-secret',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('provider validation rejects responses without explicit probe evidence', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ status: 'healthy', detail: 'ambiguous response' }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });

  try {
    const clients = [
      new DesktopApiClient({
        ...DEFAULT_CONFIG,
        mode: 'local',
        apiBaseUrl: 'http://127.0.0.1:8088',
        apiKey: 'local-user-session',
        localApiToken: 'launch-capability',
      }),
      new DesktopApiClient({
        ...DEFAULT_CONFIG,
        mode: 'cloud',
        apiBaseUrl: 'https://api.example.test',
        apiKey: 'cloud-user-session',
      }),
    ];

    for (const client of clients) {
      await assert.rejects(
        client.testLlmProviderDraft({
          name: 'Draft provider',
          providerType: 'openai',
          authMethod: 'none',
          baseUrl: 'http://127.0.0.1:11434/v1',
          active: true,
        }),
        /Invalid provider validation response/,
      );
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});
