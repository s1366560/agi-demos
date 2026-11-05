import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { createTenantProvidersHttpClientV2Fixture } from './tenantProvidersOperationsV2Fixture.mjs';

const require = createRequire(import.meta.url);
const root = '/tmp/agistack-desktop-test-dist';
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require(`${root}/src/i18n.js`);
const { ProviderModelsPanel } = require(`${root}/src/features/settings/ProviderModelsPanel.js`);
const {
  providerDraftFromProvider,
  providerMutationFromDraft,
  providerMutationForEnabledModels,
  providerMutationForActiveState,
} = require(`${root}/src/features/settings/providerManagementModel.js`);
const runtime = {
  apiBaseUrl: 'http://127.0.0.1:43117',
  deviceAuthorizationBaseUrl: '',
  apiKey: 'fixture-identity',
  localApiToken: 'fixture-launch',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: '',
  workspaceRoot: '',
  mode: 'local',
};
const provider = {
  id: 'provider-1',
  tenant_id: 'tenant-1',
  provider_type: 'openai_compatible',
  name: 'Configured provider',
  auth_method: 'none',
  base_url: runtime.apiBaseUrl,
  revision: 3,
  is_active: true,
  llm_model: 'opaque-a',
  allowed_models: ['opaque-a', 'opaque-b'],
  audio_input_models: ['opaque-b'],
};
const mutation = {
  name: provider.name,
  providerType: provider.provider_type,
  authMethod: 'none',
  baseUrl: runtime.apiBaseUrl,
  primaryModel: 'opaque-a',
  allowedModels: ['opaque-a', 'opaque-b'],
  active: true,
  expectedRevision: 3,
};
const json = (body) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });

test('explicit audio input declaration saves, clears and preserves omission through typed transport', async () => {
  const previous = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (_url, init) => {
    const body = JSON.parse(init.body);
    requests.push(body);
    return json({
      ...provider,
      revision: 4,
      audio_input_models: body.audio_input_models ?? [],
    });
  };
  try {
    const client = createTenantProvidersHttpClientV2Fixture(runtime);
    const saved = await client.updateLlmProvider(provider.id, {
      ...mutation,
      audioInputModels: ['opaque-b'],
    });
    assert.deepEqual(requests[0].audio_input_models, ['opaque-b']);
    assert.equal(requests[0].expected_revision, 3);
    assert.deepEqual(saved.audio_input_models, ['opaque-b']);
    await client.updateLlmProvider(provider.id, {
      ...mutation,
      audioInputModels: [],
    });
    assert.deepEqual(requests[1].audio_input_models, []);
    await client.updateLlmProvider(provider.id, mutation);
    assert.equal('audio_input_models' in requests[2], false);
  } finally {
    globalThis.fetch = previous;
  }
});

test('audio declaration rejects non-enabled IDs, malformed values and unsupported protocols before transport', async () => {
  const previous = globalThis.fetch;
  let requests = 0;
  globalThis.fetch = async () => {
    requests++;
    return json(provider);
  };
  try {
    const client = createTenantProvidersHttpClientV2Fixture(runtime);
    for (const audioInputModels of [
      null,
      'opaque-b',
      [3],
      ['missing'],
      [' opaque-b '],
      [''],
      ['bad\n'],
      Array(2001).fill('opaque-b'),
    ]) {
      await assert.rejects(
        client.updateLlmProvider(provider.id, {
          ...mutation,
          audioInputModels,
        }),
        /audio_input_models_invalid/,
      );
    }
    await assert.rejects(
      client.updateLlmProvider(provider.id, {
        ...mutation,
        providerType: 'anthropic',
        audioInputModels: ['opaque-b'],
      }),
      /audio_input_models_invalid/,
    );
    assert.equal(requests, 0);
    await client.updateLlmProvider(provider.id, {
      ...mutation,
      audioInputModels: ['opaque-a'],
    });
    await client.updateLlmProvider(provider.id, {
      ...mutation,
      providerType: 'anthropic',
      audioInputModels: [],
    });
    assert.equal(requests, 2);
  } finally {
    globalThis.fetch = previous;
  }
});

test('provider responses preserve explicit audio declaration and reject invalid declarations', async () => {
  const previous = globalThis.fetch;
  let current = provider;
  globalThis.fetch = async () => json([current]);
  try {
    const client = createTenantProvidersHttpClientV2Fixture(runtime);
    assert.deepEqual((await client.listLlmProviders())[0].audio_input_models, ['opaque-b']);
    for (const audio_input_models of [null, 'opaque-b', ['missing'], [3]]) {
      current = { ...provider, audio_input_models };
      await assert.rejects(client.listLlmProviders(), /Invalid provider audio input declaration/);
    }
    const { audio_input_models: _ignored, ...legacy } = provider;
    current = legacy;
    assert.equal('audio_input_models' in (await client.listLlmProviders())[0], false);
  } finally {
    globalThis.fetch = previous;
  }
});

test('activation and connection edits retain audio declarations while disabling a model removes its declaration', () => {
  assert.deepEqual(
    providerMutationFromDraft(providerDraftFromProvider(provider)).audioInputModels,
    ['opaque-b'],
  );
  assert.deepEqual(providerMutationForActiveState(provider, false).audioInputModels, ['opaque-b']);
  assert.deepEqual(providerMutationForEnabledModels(provider, ['opaque-a']).audioInputModels, []);
  assert.deepEqual(
    providerMutationForEnabledModels(provider, ['opaque-a', 'opaque-b']).audioInputModels,
    ['opaque-b'],
  );
  const draft = providerDraftFromProvider(provider);
  draft.providerType = 'anthropic';
  assert.deepEqual(providerMutationFromDraft(draft).audioInputModels, []);
});

test('Models UI exposes declared audio input per enabled model with readonly and local protocol limits', () => {
  const render = (extra = {}) =>
    renderToStaticMarkup(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(ProviderModelsPanel, {
          provider,
          canManage: true,
          allowAudioInputDeclaration: true,
          onLoadCatalog: async () => ({
            availability: 'unavailable',
            models: [],
          }),
          onSave: async () => provider,
          ...extra,
        }),
      ),
    );
  const html = render();
  assert.match(html, /Declare audio input for opaque-b/);
  assert.match(html, /aria-label="Declare audio input for opaque-b"[^>]*checked=""/);
  assert.match(html, /Confirm that the enabled model accepts audio input/);
  assert.match(
    render({ provider: { ...provider, provider_type: 'volcengine' } }),
    /aria-label="Declare audio input for opaque-b"[^>]*checked=""/,
  );
  assert.doesNotMatch(render({ allowAudioInputDeclaration: false }), /Declare audio input/);
  assert.doesNotMatch(
    render({ provider: { ...provider, provider_type: 'anthropic' } }),
    /Declare audio input/,
  );
  assert.match(
    render({ canManage: false }),
    /aria-label="Declare audio input for opaque-b"[^>]*disabled=""/,
  );
  assert.match(
    render({
      provider: {
        ...provider,
        allowed_models: ['opaque-b'],
        audio_input_models: [],
      },
    }),
    /Declare audio input for opaque-a/,
  );
});
