import assert from 'node:assert/strict';
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
  providerModelCanBeDisabled,
  providerModelsFromProvider,
  providerMutationForEnabledModels,
  providerMutationFromDraft,
  providerTypeDisplayName,
  providerValidationSignal,
} = require('/tmp/agistack-desktop-test-dist/src/features/settings/providerManagementModel.js');
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

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
    source: 'cloud_api',
  };
  const apiKeyDescriptor = {
    providerType: 'openai',
    authMethods: ['api_key'],
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
    'attention'
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
    'attention'
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
    'connected'
  );
  assert.deepEqual(
    filterProviders(providers, '  ANTHRO ', 'all').map((provider) => provider.id),
    ['anthropic']
  );
  assert.deepEqual(
    filterProviders(providers, 'open', 'connected').map((provider) => provider.id),
    ['openai']
  );
  assert.deepEqual(
    filterProviders(providers, '', 'attention').map((provider) => provider.id),
    ['anthropic', 'embedding']
  );
  assert.deepEqual(providerModelsFromProvider(providers[0]), [
    { id: 'gpt-5', capability: 'chat' },
    { id: 'gpt-5-mini', capability: 'chat' },
  ]);
  assert.deepEqual(providerModelsFromProvider(providers[2]), [
    { id: 'text-embedding-3-large', capability: 'embedding' },
  ]);
});

test('provider validation distinguishes configuration-only results from real probes', () => {
  assert.deepEqual(
    providerValidationSignal({
      provider: null,
      status: 'configuration_valid',
      probed: false,
      detail: 'No external request was sent',
    }),
    { kind: 'configuration_only', status: 'configuration_valid' }
  );
  assert.deepEqual(
    providerValidationSignal({
      provider: null,
      status: 'healthy',
      probed: true,
      detail: null,
    }),
    { kind: 'external_probe', status: 'healthy' }
  );
});

test('provider API adapters preserve local revision and cloud health contracts', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    const url = String(input);
    if (url.endsWith('/test')) {
      return new Response(
        JSON.stringify({
          provider: { id: 'local-runtime', revision: 8 },
          status: 'configuration_valid',
          probed: false,
          detail: 'configuration validated locally; no external request was sent',
        }),
        { status: 200, headers: { 'content-type': 'application/json' } }
      );
    }
    if (url.endsWith('/health-check')) {
      return new Response(
        JSON.stringify({
          provider_id: '11111111-2222-4333-8444-555555555555',
          status: 'healthy',
          last_check: '2026-07-13T10:00:00Z',
          response_time_ms: 42,
          error_message: null,
        }),
        { status: 200, headers: { 'content-type': 'application/json' } }
      );
    }
    return new Response(
      JSON.stringify({
        id: url.includes('local-runtime')
          ? 'local-runtime'
          : '11111111-2222-4333-8444-555555555555',
        name: 'Provider',
        provider_type: 'openai',
        revision: 8,
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
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

    await local.updateLlmProvider('local-runtime', mutation);
    const localValidation = await local.checkLlmProvider('local-runtime');
    await cloud.updateLlmProvider('11111111-2222-4333-8444-555555555555', mutation);
    const cloudValidation = await cloud.checkLlmProvider(
      '11111111-2222-4333-8444-555555555555'
    );

    assert.equal(calls[0]?.init?.method, 'PATCH');
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
    assert.equal(localValidation.probed, false);
    assert.equal(calls[2]?.init?.method, 'PUT');
    assert.deepEqual(JSON.parse(String(calls[2]?.init?.body)), {
      name: 'Provider',
      provider_type: 'openai',
      base_url: 'https://llm.example.test/v1',
      llm_model: 'gpt-test',
      allowed_models: ['gpt-test'],
      is_active: true,
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
      { status: 201, headers: { 'content-type': 'application/json' } }
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

test('provider discovery and usage fail closed locally and normalize cloud payloads', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input) => {
    calls.push(String(input));
    const url = String(input);
    if (url.endsWith('/types')) {
      const types = url.startsWith('http://127.0.0.1:8088')
        ? [
            { provider_type: 'openai', auth_methods: ['api_key', 'none'] },
            { provider_type: 'anthropic', auth_methods: ['api_key', 'none'] },
            { provider_type: 'openai_compatible', auth_methods: ['api_key', 'none'] },
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
        { status: 200, headers: { 'content-type': 'application/json' } }
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
        { status: 200, headers: { 'content-type': 'application/json' } }
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
        authMethods: ['api_key', 'none'],
        source: 'local_runtime',
      },
      {
        providerType: 'anthropic',
        authMethods: ['api_key', 'none'],
        source: 'local_runtime',
      },
      {
        providerType: 'openai_compatible',
        authMethods: ['api_key', 'none'],
        source: 'local_runtime',
      },
    ]);
    assert.deepEqual(await local.listLlmProviderModels('openai'), {
      providerType: 'openai',
      availability: 'unavailable',
      source: null,
      models: [],
    });
    assert.deepEqual(await local.getLlmProviderUsage('provider-local'), {
      provider_id: 'provider-local',
      tenant_id: null,
      availability: 'unavailable',
      statistics: [],
    });
    assert.deepEqual(calls, ['http://127.0.0.1:8088/api/v1/llm-providers/types']);

    assert.deepEqual(await cloud.listLlmProviderTypes(), [
      { providerType: 'openai', authMethods: ['api_key'], source: 'cloud_api' },
      { providerType: 'ollama', authMethods: ['none'], source: 'cloud_api' },
      { providerType: 'anthropic', authMethods: [], source: 'cloud_api' },
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
      'https://api.example.test/api/v1/llm-providers/types',
      'https://api.example.test/api/v1/llm-providers/models/anthropic',
      'https://api.example.test/api/v1/llm-providers/provider-cloud/usage',
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('draft connection tests probe only cloud and report local structural validation honestly', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    return new Response(
      JSON.stringify({
        provider_id: 'temporary-probe',
        status: 'healthy',
        last_check: '2026-07-14T10:00:00Z',
        response_time_ms: 37,
        error_message: null,
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
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
      providerType: 'anthropic',
      authMethod: 'api_key',
      baseUrl: 'https://api.anthropic.test',
      primaryModel: 'claude-sonnet-4',
      allowedModels: ['claude-sonnet-4'],
      active: true,
      apiKey: 'draft-secret',
    };

    assert.deepEqual(await local.testLlmProviderDraft(input), {
      provider: null,
      status: 'configuration_valid',
      probed: false,
      detail: 'configuration_only',
    });
    assert.deepEqual(
      await local.testLlmProviderDraft({ ...input, baseUrl: 'file:///tmp/not-an-api' }),
      {
        provider: null,
        status: 'configuration_invalid',
        probed: false,
        detail: 'configuration_only',
        errorMessage: 'invalid_base_url',
      }
    );
    assert.deepEqual(calls, []);

    assert.deepEqual(await cloud.testLlmProviderDraft(input), {
      provider: null,
      status: 'healthy',
      probed: true,
      detail: null,
      lastChecked: '2026-07-14T10:00:00Z',
      responseTimeMs: 37,
      errorMessage: null,
    });
    assert.equal(
      calls[0]?.input,
      'https://api.example.test/api/v1/llm-providers/test-connection'
    );
    assert.equal(calls[0]?.init?.method, 'POST');
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      name: 'Draft provider',
      provider_type: 'anthropic',
      base_url: 'https://api.anthropic.test',
      llm_model: 'claude-sonnet-4',
      allowed_models: ['claude-sonnet-4'],
      is_active: true,
      api_key: 'draft-secret',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});
