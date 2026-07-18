import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { DesktopApiClient } = require('/tmp/agistack-desktop-test-dist/src/api/client.js');
const {
  filterProviders,
  providerConnectionStatus,
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
const settingsWindowSource = readFileSync(
  new URL('../src/features/settings/SettingsWindow.tsx', import.meta.url),
  'utf8',
);
const providerSettingsQaSource = readFileSync(
  new URL('../src/qa/ProviderSettingsQa.tsx', import.meta.url),
  'utf8',
);
const i18nSource = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');

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

test('provider setup fails closed when the server does not declare an auth capability', () => {
  const legacyDescriptor = {
    providerType: 'legacy',
    authMethods: [],
    operationType: 'llm',
    probeSupported: true,
    source: 'cloud_api',
  };
  const apiKeyDescriptor = {
    providerType: 'openai',
    authMethods: ['api_key'],
    operationType: 'llm',
    probeSupported: true,
    source: 'cloud_api',
  };

  assert.equal(providerAuthMethodSupported(legacyDescriptor, 'api_key'), false);
  assert.equal(providerAuthMethodSupported(apiKeyDescriptor, 'api_key'), true);
  assert.equal(providerAuthMethodSupported(apiKeyDescriptor, 'none'), false);
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
    }),
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
    { ...provider, health_status: 'healthy' },
  ]) {
    assert.deepEqual(localRuntimeRoutingModelIds(unusable), []);
  }
});

test('fallback availability ignores stale targets when a valid candidate remains', () => {
  const stale = { provider_id: 'provider-stale', model_id: 'removed-model' };
  const activeA = { provider_id: 'provider-openai', model_id: 'gpt-main' };
  const activeB = { provider_id: 'provider-anthropic', model_id: 'claude-main' };
  assert.equal(routingFallbackCanAdd([stale, activeA], [activeA, activeB], 8), true);
  assert.equal(routingFallbackCanAdd([stale, activeA, activeB], [activeA, activeB], 8), false);
  assert.equal(routingFallbackCanAdd([stale, activeA], [activeA, activeB], 2), false);
});

test('provider validation distinguishes configuration-only results from real probes', () => {
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
  assert.match(addProviderDialogSource, /if \(modelId === primaryModel\) return/);
  assert.match(addProviderDialogSource, /disabled=\{model\.id === primaryModel\}/);
  assert.match(addProviderDialogSource, /descriptor\.authMethods\.includes\('none'\)/);
  assert.match(
    addProviderDialogSource,
    /ollama:[\s\S]{0,100}baseUrl: 'http:\/\/127\.0\.0\.1:11434'/,
  );
});

test('provider editing preserves stored credentials only for the unchanged endpoint', () => {
  assert.match(
    providerConnectionPanelSource,
    /credentialRequiredForDraft[\s\S]{0,200}draft\.authMethod === 'api_key'[\s\S]{0,200}endpointChanged[\s\S]{0,100}!mutation\.apiKey/,
  );
  assert.match(
    providerConnectionPanelSource,
    /validateDraft[\s\S]{0,160}editing && !\(draft\.authMethod === 'api_key' && !draftMutation\.apiKey\)/,
  );
  assert.match(providerConnectionPanelSource, /secretRequiredForEndpointChange/);
  assert.match(
    providerConnectionPanelSource,
    /probeSupported = providerTypeDescriptor\?\.probeSupported === true/,
  );
  assert.match(
    providerConnectionPanelSource,
    /validationAvailable = authCapabilityAvailable/,
  );
  assert.match(
    providerConnectionPanelSource,
    /providerValidationAccepted\(validation, probeSupported\)/,
  );
  assert.doesNotMatch(
    providerConnectionPanelSource,
    /disabled=\{!probeSupported \|\| !verified/,
  );
});

test('provider routing is policy-backed, cross-provider, and context safe', () => {
  assert.match(providerOverviewPanelsSource, /const controller = new AbortController\(\)/);
  assert.match(providerOverviewPanelsSource, /onLoadUsage\(provider\.id, controller\.signal\)/);
  assert.match(providerOverviewPanelsSource, /return \(\) => controller\.abort\(\)/);
  assert.match(
    providerOverviewPanelsSource,
    /const ROUTING_ROLES: LlmRoutingRole\[\] = \['default', 'fast', 'coding', 'vision'\]/,
  );
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
  assert.match(
    providerOverviewPanelsSource,
    /expectedRevision: policy\.revision/,
  );
  assert.match(providerOverviewPanelsSource, /moveFallback\(index, -1\)/);
  assert.match(providerOverviewPanelsSource, /moveFallback\(index, 1\)/);
  assert.match(providerOverviewPanelsSource, /removeFallback\(index\)/);
  assert.match(providerOverviewPanelsSource, /const MAX_ROUTING_FALLBACKS = 8/);
  assert.match(providerOverviewPanelsSource, /const MAX_ROUTING_FALLBACKS = 8/);
  assert.match(providerOverviewPanelsSource, /routingFallbackCanAdd\(/);
  assert.match(providerOverviewPanelsSource, /const saveRequestRef = useRef\(0\)/);
  assert.doesNotMatch(
    providerOverviewPanelsSource,
    /providerDraftFromProvider|providerMutationFromDraft|onRuntimeSelected/,
  );
  assert.match(
    modelProviderWorkspaceSource,
    /config\.mode === 'local'[\s\S]{0,80}\? runtimeProvider\?\.provider_id === provider\.id[\s\S]{0,80}: provider\.runtime_selected === true/,
  );
  assert.match(modelProviderWorkspaceSource, /provider\.runtime_selected === true/);
  assert.match(
    modelProviderWorkspaceSource,
    /!outcome\.probed && outcome\.status === 'configuration_valid'[\s\S]{0,1200}'providers\.providerConfigured'/,
  );
  assert.match(i18nSource, /'providers\.providerConfigured': '\{provider\} configuration is ready'/);
  assert.doesNotMatch(
    modelProviderWorkspaceSource,
    /llmProvider|llmBaseUrl|llmModel|llmApiKey|onConfigChange/,
  );
  assert.match(modelProviderWorkspaceSource, /getLlmProviderRoutingPolicy\(signal\)/);
  assert.match(modelProviderWorkspaceSource, /Promise\.all\(\[/);
  assert.match(
    modelProviderWorkspaceSource,
    /requestClient\.updateLlmProviderRoutingPolicy\(mutation\)/,
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
  assert.match(
    ordinarySave,
    /await refreshRuntimeProjection\(requestScope, requestClient\)/,
  );
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
    /caught instanceof DesktopApiError[\s\S]{0,100}caught\.status !== 409[\s\S]{0,180}getLlmProviderRoutingPolicy\(\)/,
  );
  assert.match(
    routingSave,
    /Promise\.all\(\[[\s\S]{0,180}listLlmProviders\(\)[\s\S]{0,180}getLlmProviderRoutingPolicy\(\)/,
  );
  assert.match(routingSave, /setProviders\(modelProviders\)/);
  assert.match(
    routingSave,
    /await refreshRuntimeProjection\(requestScope, requestClient\)/,
  );
  assert.match(
    settingsWindowSource,
    /key=\{`\$\{config\.mode\}\|\$\{config\.apiBaseUrl\}\|\$\{config\.tenantId\}`\}/,
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
  const scopeKeyDeclaration =
    modelProviderWorkspaceSource.match(/const scopeKey = .*;/)?.[0] ?? '';
  assert.doesNotMatch(scopeKeyDeclaration, /apiKey|localApiToken/);
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
    /provider_type:\s*'openai'[\s\S]{0,160}auth_methods:\s*\['api_key', 'none'\][\s\S]{0,120}probe_supported:\s*false/,
  );
  assert.match(providerSettingsQaSource, /provider_type:\s*'openai_compatible'/);
  assert.doesNotMatch(
    providerSettingsQaSource,
    /provider_type:\s*'(?:gemini|openrouter|ollama)'/,
  );
  assert.doesNotMatch(providerSettingsQaSource, /llmProvider|llmBaseUrl|llmModel|llmApiKey/);
  assert.match(providerSettingsQaSource, /mode: 'local'/);
  assert.match(
    providerSettingsQaSource,
    /path === '\/api\/v1\/llm-providers\/routing-policy'/,
  );
  assert.match(providerSettingsQaSource, /draft\.expected_revision !== routingPolicy\.revision/);
  assert.match(providerSettingsQaSource, /draft\.roles\.fast !== null/);
  assert.match(providerSettingsQaSource, /draft\.roles\.vision !== null/);
  assert.match(providerSettingsQaSource, /status: configured \? 'configuration_valid'/);
  assert.match(providerSettingsQaSource, /probed: false/);
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
        revision,
        roles: {
          default: { provider_id: ' provider-openai ', model_id: ' gpt-5 ' },
          fast: null,
          coding: { provider_id: 'provider-anthropic', model_id: 'claude-code' },
          vision: null,
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
    const policy = await local.getLlmProviderRoutingPolicy();
    assert.deepEqual(policy, {
      tenant_id: 'tenant-a',
      revision: 7,
      roles: {
        default: { provider_id: 'provider-openai', model_id: 'gpt-5' },
        fast: null,
        coding: { provider_id: 'provider-anthropic', model_id: 'claude-code' },
        vision: null,
      },
      fallbacks: [{ provider_id: 'provider-anthropic', model_id: 'claude-fast' }],
      updated_at: '2026-07-18T00:00:00.000Z',
    });
    const updated = await local.updateLlmProviderRoutingPolicy({
      roles: policy.roles,
      fallbacks: policy.fallbacks,
      expectedRevision: policy.revision,
    });
    assert.equal(updated.revision, 8);
    assert.equal(calls[0]?.input, 'http://127.0.0.1:8088/api/v1/llm-providers/routing-policy');
    assert.equal(calls[1]?.init?.method, 'PUT');
    assert.deepEqual(JSON.parse(String(calls[1]?.init?.body)), {
      roles: policy.roles,
      fallbacks: policy.fallbacks,
      expected_revision: 7,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('runtime selection is guarded by both provider and routing-policy revisions', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    const selected = String(input).endsWith('/runtime-selection');
    return new Response(
      JSON.stringify({
        id: 'provider-local',
        name: 'Local provider',
        provider_type: 'openai',
        runtime_selected: selected,
        revision: selected ? 9 : 8,
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
    const mutation = {
      name: 'Local provider',
      providerType: 'openai',
      authMethod: 'api_key',
      baseUrl: 'https://llm.example.test/v1',
      primaryModel: 'gpt-test',
      allowedModels: ['gpt-test'],
      active: true,
      expectedRevision: 7,
    };

    const updated = await local.updateLlmProvider('provider-local', mutation);
    assert.equal(updated.runtime_selected, false);
    assert.equal(calls.length, 1);
    assert.equal(calls[0]?.input.endsWith('/provider-local'), true);

    const selected = await local.selectLlmRuntimeProvider(
      'provider-local',
      updated.revision ?? 0,
      0,
    );
    assert.equal(selected.runtime_selected, true);
    assert.equal(calls[1]?.input.endsWith('/provider-local/runtime-selection'), true);
    assert.equal(calls[1]?.init?.method, 'PUT');
    assert.deepEqual(JSON.parse(String(calls[1]?.init?.body)), {
      expected_revision: 8,
      expected_policy_revision: 0,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
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
              runtimeSelected: true,
              version: 8,
            }
          : {
              auth_method: 'api_key',
              credential_configured: true,
              runtime_selected: false,
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
      baseUrl: 'https://llm.example.test/v1',
      primaryModel: 'gpt-test',
      allowedModels: ['gpt-test'],
      active: true,
      expectedRevision: 7,
    };

    const localUpdated = await local.updateLlmProvider('local-runtime', mutation);
    const localValidation = await local.checkLlmProvider('local-runtime');
    await cloud.updateLlmProvider('11111111-2222-4333-8444-555555555555', mutation);
    const cloudValidation = await cloud.checkLlmProvider('11111111-2222-4333-8444-555555555555');

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
        runtimeSelected: localUpdated.runtime_selected,
      },
      {
        authMethod: 'api_key',
        credentialConfigured: true,
        revision: 8,
        runtimeSelected: true,
      },
    );
    assert.equal(String(calls[1]?.input).endsWith('/local-runtime/health-check'), true);
    assert.equal(localValidation.probed, true);
    assert.equal(localValidation.status, 'healthy');
    assert.equal(calls[2]?.init?.method, 'PUT');
    assert.deepEqual(JSON.parse(String(calls[2]?.init?.body)), {
      name: 'Provider',
      provider_type: 'openai',
      base_url: 'https://llm.example.test/v1',
      llm_model: 'gpt-test',
      allowed_models: ['gpt-test'],
      is_active: true,
      expected_revision: 7,
    });
    assert.equal(cloudValidation.probed, true);
    assert.equal(cloudValidation.status, 'healthy');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('provider create adapters keep local-only auth fields out of cloud requests', async () => {
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
      api_key: 'runtime-only-secret',
    });
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
          api_key_masked: 'sk-…last4',
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
        runtimeSelected: provider.runtime_selected,
        revision: provider.revision,
      })),
      [
        {
          id: 'local-ollama',
          providerType: 'ollama',
          authMethod: 'none',
          credentialConfigured: false,
          runtimeSelected: true,
          revision: 12,
        },
        {
          id: 'legacy-openai',
          providerType: 'openai',
          authMethod: undefined,
          credentialConfigured: true,
          runtimeSelected: false,
          revision: 0,
        },
      ],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('provider discovery and usage use the same local and cloud contracts', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input) => {
    calls.push(String(input));
    const url = String(input);
    if (url.endsWith('/types')) {
      const types = url.startsWith('http://127.0.0.1:8088')
        ? [
            {
              provider_type: 'openai',
              operation_type: 'llm',
              auth_methods: ['api_key'],
            },
            {
              provider_type: 'anthropic',
              operation_type: 'llm',
              auth_methods: ['api_key'],
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
              auth_methods: ['none'],
            },
            {
              provider_type: 'dashscope_embedding',
              operation_type: 'embedding',
              auth_methods: ['api_key'],
            },
          ]
        : [
            { provider_type: 'openai', auth_methods: ['api_key'] },
            { provider_type: 'ollama', auth_methods: ['none'] },
            'anthropic',
          ];
      return new Response(JSON.stringify(types), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
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
        operationType: 'llm',
        probeSupported: true,
        source: 'local_runtime',
      },
      {
        providerType: 'anthropic',
        authMethods: ['api_key'],
        operationType: 'llm',
        probeSupported: true,
        source: 'local_runtime',
      },
      {
        providerType: 'azure_openai',
        authMethods: ['api_key'],
        operationType: 'llm',
        probeSupported: false,
        source: 'local_runtime',
      },
      {
        providerType: 'ollama',
        authMethods: ['none'],
        operationType: 'llm',
        probeSupported: true,
        source: 'local_runtime',
      },
      {
        providerType: 'dashscope_embedding',
        authMethods: ['api_key'],
        operationType: 'embedding',
        probeSupported: true,
        source: 'local_runtime',
      },
    ]);
    assert.deepEqual(await local.listLlmProviderModels('openai'), {
      providerType: 'openai',
      availability: 'available',
      source: 'models.dev',
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
      'http://127.0.0.1:8088/api/v1/llm-providers/models/openai',
      'http://127.0.0.1:8088/api/v1/llm-providers/provider-local/usage',
    ]);

    assert.deepEqual(await cloud.listLlmProviderTypes(), [
      {
        providerType: 'openai',
        authMethods: ['api_key'],
        operationType: 'llm',
        probeSupported: true,
        source: 'cloud_api',
      },
      {
        providerType: 'ollama',
        authMethods: ['none'],
        operationType: 'llm',
        probeSupported: true,
        source: 'cloud_api',
      },
      {
        providerType: 'anthropic',
        authMethods: [],
        operationType: 'llm',
        probeSupported: true,
        source: 'cloud_api',
      },
    ]);
    assert.deepEqual(await cloud.listLlmProviderModels('anthropic'), {
      providerType: 'anthropic',
      availability: 'available',
      source: 'models.dev',
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
      'http://127.0.0.1:8088/api/v1/llm-providers/models/openai',
      'http://127.0.0.1:8088/api/v1/llm-providers/provider-local/usage',
      'https://api.example.test/api/v1/llm-providers/types',
      'https://api.example.test/api/v1/llm-providers/models/anthropic',
      'https://api.example.test/api/v1/llm-providers/provider-cloud/usage',
    ]);
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
      availability: 'available',
      source: 'static-fallback',
      models: [{ id: 'gpt-4o-mini', capability: 'chat' }],
    });
    assert.deepEqual(await client.listLlmProviderModels('custom-cloud'), {
      providerType: 'custom-cloud',
      availability: 'unavailable',
      source: null,
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

test('draft validation treats local checks as configuration-only and preserves cloud probes', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    const local = String(input).startsWith('http://127.0.0.1:8088');
    return new Response(
      JSON.stringify({
        provider_id: 'temporary-probe',
        status: local ? 'configuration_valid' : 'unhealthy',
        ...(!local ? { probed: true } : {}),
        detail: local ? 'configuration validated locally; no external request was sent' : null,
        last_check: local ? null : '2026-07-14T10:00:00Z',
        response_time_ms: local ? null : 37,
        error_message: local ? null : 'model was not available',
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
      primaryModel: 'gateway-model',
      allowedModels: ['gateway-model'],
      active: true,
      apiKey: 'draft-secret',
    };

    assert.deepEqual(await local.testLlmProviderDraft(input), {
      provider: null,
      status: 'configuration_valid',
      probed: false,
      detail: 'configuration validated locally; no external request was sent',
      lastChecked: null,
      responseTimeMs: null,
      errorMessage: null,
    });
    assert.deepEqual(await cloud.testLlmProviderDraft(input), {
      provider: null,
      status: 'unhealthy',
      probed: true,
      detail: null,
      lastChecked: '2026-07-14T10:00:00Z',
      responseTimeMs: 37,
      errorMessage: 'model was not available',
    });
    assert.equal(calls[0]?.input, 'http://127.0.0.1:8088/api/v1/llm-providers/test-connection');
    assert.equal(calls[0]?.init?.method, 'POST');
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      name: 'Draft provider',
      provider_type: 'custom_gateway',
      base_url: 'https://gateway.example.test/v1',
      llm_model: 'gateway-model',
      allowed_models: ['gateway-model'],
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
      llm_model: 'gateway-model',
      allowed_models: ['gateway-model'],
      is_active: true,
      api_key: 'draft-secret',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});
