import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { createTenantProvidersHttpClientV2Fixture } from './tenantProvidersOperationsV2Fixture.mjs';

const require = createRequire(import.meta.url);
const {
  providerSetupOptions,
  providerTypeDisplayName,
  providerDraftFromProvider,
  providerMutationFromDraft,
  providerMutationForActiveState,
  localRuntimeRoutingModelIds,
} = require('/tmp/agistack-desktop-test-dist/src/features/settings/providerManagementModel.js');
const descriptor = {
  providerType: 'openai_compatible',
  authMethods: ['api_key', 'environment', 'none'],
  unavailableAuthMethods: [],
  operationType: 'llm',
  probeSupported: true,
  source: 'local_runtime',
};
const runtime = {
  apiBaseUrl: 'http://127.0.0.1:43117',
  deviceAuthorizationBaseUrl: '',
  apiKey: 'fixture-owner',
  localApiToken: 'fixture-launch',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: '',
  workspaceRoot: '',
  mode: 'local',
};
const json = (body) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });

test('local Ark is a distinct supported OpenAI-protocol preset with explicit environment reference', () => {
  const options = providerSetupOptions([descriptor]);
  const ark = options.find((option) => option.id === 'preset:volcengine-ark');
  assert.ok(ark);
  assert.equal(ark.name, 'Volcengine Ark');
  assert.equal(ark.descriptor, descriptor);
  assert.equal(ark.authMethod, 'environment');
  assert.equal(ark.environmentVariable, 'ARK_API_KEY');
  assert.equal(ark.baseUrl, 'https://ark.cn-beijing.volces.com/api/v3');
  assert.equal('primaryModel' in ark, false);
  assert.equal('audioInputModels' in ark, false);
  assert.equal(new Set(options.map((option) => option.id)).size, options.length);
  assert.equal(
    options.find((option) => option.id === 'preset:kimi').environmentVariable,
    'KIMI_API_KEY'
  );
  for (const unsupported of [
    { ...descriptor, source: 'cloud_api' },
    { ...descriptor, authMethods: ['api_key'] },
    { ...descriptor, unavailableAuthMethods: ['environment'] },
    { ...descriptor, operationType: 'embedding' },
  ])
    assert.equal(
      providerSetupOptions([unsupported]).some((option) => option.id === ark.id),
      false
    );
});

test('cloud Volcengine uses its declared protocol and canonical Ark endpoint without native environment permission', () => {
  const cloud = {
    ...descriptor,
    providerType: 'volcengine',
    source: 'cloud_api',
    authMethods: ['api_key'],
  };
  const [option] = providerSetupOptions([cloud]);
  assert.equal(providerTypeDisplayName('volcengine'), 'Volcengine Ark');
  assert.equal(option.id, 'type:volcengine');
  assert.equal(option.name, 'Volcengine Ark');
  assert.equal(option.baseUrl, 'https://ark.cn-beijing.volces.com/api/v3');
  assert.equal(option.authMethod, 'api_key');
  assert.equal(option.environmentVariable, '');
});

test('Ark create, discovery, explicit audio declaration and activation retain the exact provider and model', async () => {
  const previous = globalThis.fetch;
  const requests = [];
  const model = 'explicit-ark-model';
  let saved;
  globalThis.fetch = async (url, init) => {
    const path = new URL(url).pathname;
    const body = init.body ? JSON.parse(init.body) : null;
    requests.push({ path, method: init.method, body });
    if (path.endsWith('/models/discover'))
      return json({
        provider_id: saved.id,
        provider_type: 'openai_compatible',
        availability: 'available',
        source: 'provider-api',
        models: { chat: [model], embedding: [], rerank: [] },
      });
    saved = {
      ...(saved ?? {
        id: 'ark-1',
        tenant_id: runtime.tenantId,
        revision: 0,
        credential_configured: true,
        health_status: 'connected',
        is_enabled: true,
        audio_input_models: [],
      }),
      ...body,
      revision: (saved?.revision ?? 0) + 1,
    };
    return json(saved);
  };
  try {
    const client = createTenantProvidersHttpClientV2Fixture(runtime);
    const ark = providerSetupOptions([descriptor]).find(
      (option) => option.id === 'preset:volcengine-ark'
    );
    assert.ok(ark);
    const created = await client.createLlmProvider(
      {
        name: ark.name,
        providerType: ark.descriptor.providerType,
        authMethod: ark.authMethod,
        baseUrl: ark.baseUrl,
        environmentVariable: ark.environmentVariable,
        primaryModel: model,
        allowedModels: [model],
        active: true,
      },
      'ark-create-fixture'
    );
    assert.deepEqual(created.audio_input_models, []);
    assert.equal(requests[0].body.environment_variable, 'ARK_API_KEY');
    assert.equal('api_key' in requests[0].body, false);
    assert.equal('audio_input_models' in requests[0].body, false);
    const catalog = await client.discoverLlmProviderModels(created.id, created.revision);
    assert.deepEqual(catalog.models, [{ id: model, capability: 'chat' }]);
    assert.deepEqual(requests[1].body, { expected_revision: created.revision });
    const draft = providerDraftFromProvider(created);
    draft.audioInputModels = [model];
    const declared = await client.updateLlmProvider(created.id, providerMutationFromDraft(draft));
    assert.deepEqual(declared.audio_input_models, [model]);
    assert.equal(requests[2].body.expected_revision, created.revision);
    assert.equal(requests[2].body.provider_type, 'openai_compatible');
    assert.equal(requests[2].body.base_url, ark.baseUrl);
    assert.equal(requests[2].body.environment_variable, 'ARK_API_KEY');
    const disabled = await client.updateLlmProvider(
      declared.id,
      providerMutationForActiveState(declared, false)
    );
    assert.deepEqual(localRuntimeRoutingModelIds(disabled), []);
    const active = await client.updateLlmProvider(
      disabled.id,
      providerMutationForActiveState(disabled, true)
    );
    assert.deepEqual(localRuntimeRoutingModelIds(active), [model]);
    assert.deepEqual(active.audio_input_models, [model]);
    assert.equal(active.environment_variable, 'ARK_API_KEY');
  } finally {
    globalThis.fetch = previous;
  }
});

test('cloud Ark nested audio edits preserve the public provider configuration', async () => {
  const previous = globalThis.fetch;
  const requests = [];
  const model = 'opaque-audio-endpoint';
  let saved = {
    id: 'cloud-ark',
    name: 'Ark cloud',
    provider_type: 'volcengine',
    auth_method: 'api_key',
    revision: 3,
    is_active: true,
    base_url: 'https://ark.cn-beijing.volces.com/api/v3',
    llm_model: model,
    allowed_models: [model],
    credential_configured: true,
    config: {
      temperature: 0.25,
      max_tokens: 1000,
      region: 'cn-beijing',
      retries: { max_attempts: 2, base_delay: 0.5 },
      transport: { request_timeout_seconds: 120 },
      embedding: {
        model: 'opaque-embedding',
        dimensions: 1024,
        provider_options: { input_type: 'search_document', truncate: 'END' },
      },
      audio_input_models: [model],
      headers: { authorization: 'private-fixture' },
    },
  };
  globalThis.fetch = async (_url, init) => {
    const body = init.body ? JSON.parse(init.body) : null;
    requests.push(body);
    if (!body) return json([saved]);
    saved = { ...saved, ...body, revision: saved.revision + 1 };
    return json(saved);
  };
  try {
    const client = createTenantProvidersHttpClientV2Fixture({
      ...runtime,
      mode: 'cloud',
    });
    const [provider] = await client.listLlmProviders();
    assert.deepEqual(provider.audio_input_models, [model]);
    assert.notEqual(provider.config.retries, saved.config.retries);
    assert.equal('headers' in provider.config, false);
    const draft = providerDraftFromProvider(provider, 'cloud');
    draft.audioInputModels = [];
    const cleared = await client.updateLlmProvider(provider.id, providerMutationFromDraft(draft));
    assert.equal('audio_input_models' in requests[1], false);
    assert.deepEqual(requests[1].config.audio_input_models, []);
    assert.equal(requests[1].config.temperature, 0.25);
    assert.equal(requests[1].config.max_tokens, 1000);
    assert.deepEqual(requests[1].config.retries, {
      max_attempts: 2,
      base_delay: 0.5,
    });
    assert.deepEqual(requests[1].config.transport, {
      request_timeout_seconds: 120,
    });
    assert.deepEqual(requests[1].config.embedding.provider_options, {
      input_type: 'search_document',
      truncate: 'END',
    });
    assert.equal(JSON.stringify(requests[1]).includes('private-fixture'), false);
    assert.deepEqual(cleared.audio_input_models, []);
    const declaredDraft = providerDraftFromProvider(cleared, 'cloud');
    declaredDraft.audioInputModels = [model];
    const declared = await client.updateLlmProvider(
      provider.id,
      providerMutationFromDraft(declaredDraft)
    );
    await client.updateLlmProvider(
      provider.id,
      providerMutationForActiveState(declared, false, 'cloud')
    );
    assert.deepEqual(requests[3].config.audio_input_models, [model]);
    assert.equal(requests[3].config.temperature, 0.25);
    assert.equal(requests[3].expected_revision, declared.revision);
  } finally {
    globalThis.fetch = previous;
  }
});

test('cloud audio declarations enforce exact configured IDs and their public config boundary before transport', async () => {
  const previous = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return json({});
  };
  const mutation = {
    name: 'Ark cloud',
    providerType: 'volcengine',
    authMethod: 'api_key',
    baseUrl: 'https://ark.cn-beijing.volces.com/api/v3',
    primaryModel: 'opaque',
    allowedModels: ['opaque'],
    providerConfig: {},
    active: true,
    expectedRevision: 2,
  };
  try {
    const client = createTenantProvidersHttpClientV2Fixture({
      ...runtime,
      mode: 'cloud',
    });
    for (const audioInputModels of [
      ['missing'],
      ['opaque', 'opaque'],
      Array(101).fill('opaque'),
      null,
    ]) {
      await assert.rejects(
        client.updateLlmProvider('cloud-ark', {
          ...mutation,
          audioInputModels,
        }),
        /audio_input_models_invalid/
      );
    }
    await assert.rejects(
      client.updateLlmProvider('cloud-ark', {
        ...mutation,
        providerType: 'anthropic',
        audioInputModels: ['opaque'],
      }),
      /audio_input_models_invalid/
    );
    await assert.rejects(
      client.updateLlmProvider('cloud-ark', {
        ...mutation,
        providerConfig: { audio_input_models: ['missing'] },
      }),
      /audio_input_models_invalid/
    );
    for (const providerConfig of [
      { headers: {} },
      { api_key: 'private-fixture' },
      {
        embedding: {
          provider_options: { api_base: 'https://example.invalid' },
        },
      },
    ])
      await assert.rejects(
        client.updateLlmProvider('cloud-ark', { ...mutation, providerConfig }),
        /public_config_invalid/
      );
    assert.equal(calls, 0);
  } finally {
    globalThis.fetch = previous;
  }
});

test('cloud Ark rejects malformed, unlisted or ambiguous nested declarations', async () => {
  const previous = globalThis.fetch;
  let config;
  let top;
  globalThis.fetch = async () =>
    json([
      {
        id: 'cloud-ark',
        name: 'Ark cloud',
        provider_type: 'volcengine',
        llm_model: 'opaque',
        allowed_models: ['opaque'],
        config,
        ...(top === undefined ? {} : { audio_input_models: top }),
      },
    ]);
  try {
    const client = createTenantProvidersHttpClientV2Fixture({
      ...runtime,
      mode: 'cloud',
    });
    for (const value of [null, 'opaque', ['opaque', 'opaque'], [3]]) {
      config = { audio_input_models: value };
      await assert.rejects(client.listLlmProviders(), /Invalid provider public configuration/);
    }
    config = { audio_input_models: ['missing'] };
    await assert.rejects(client.listLlmProviders(), /Invalid provider audio input declaration/);
    config = { audio_input_models: ['opaque'] };
    top = ['opaque'];
    await assert.rejects(client.listLlmProviders(), /Invalid provider audio input declaration/);
  } finally {
    globalThis.fetch = previous;
  }
});
