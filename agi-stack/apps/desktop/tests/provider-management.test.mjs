import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { DesktopApiClient } = require('/tmp/agistack-desktop-test-dist/src/api/client.js');
const {
  providerDraftFromProvider,
  providerManagementAllowed,
  providerMutationFromDraft,
  providerValidationSignal,
} = require('/tmp/agistack-desktop-test-dist/src/features/settings/providerManagementModel.js');
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('provider management permissions keep local owner and cloud admin boundaries explicit', () => {
  assert.equal(providerManagementAllowed('local', ['owner']), true);
  assert.equal(providerManagementAllowed('local', ['member']), false);
  assert.equal(providerManagementAllowed('cloud', ['admin']), true);
  assert.equal(providerManagementAllowed('cloud', ['owner']), false);
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
    revision: 7,
  });
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
