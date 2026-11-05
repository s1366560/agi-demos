import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { createTenantProvidersHttpClientV2Fixture } from './tenantProvidersOperationsV2Fixture.mjs';

const require = createRequire(import.meta.url);
const dist = '/tmp/agistack-desktop-test-dist/src';
const {
  providerDraftFromProvider,
  providerEnabledModelIds,
  providerMutationForEnabledModels,
  providerMutationForActiveState,
  providerMutationFromDraft,
} = require(`${dist}/features/settings/providerManagementModel.js`);
const { normalizeManagedLlmProviderV2 } = require(
  `${dist}/plugins/desktopTenantProvidersResponseContractV2.js`
);
const { workspaceRuntimeModelOptions } = require(
  `${dist}/features/settings/workspaceRuntimeProviderModel.js`
);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require(`${dist}/i18n.js`);
const { ProviderModelsPanel } = require(`${dist}/features/settings/ProviderModelsPanel.js`);
const repo = fileURLToPath(new URL('../../../..', import.meta.url));
// Exercise the actual Python response builder and validator, not a mirrored TS-only payload.
const fixture = JSON.parse(
  execFileSync(
    `${repo}/.venv/bin/python`,
    [fileURLToPath(new URL('./fixtures/cloud_provider_response.py', import.meta.url))],
    { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, encoding: 'utf8' }
  )
);
const runtime = {
  apiBaseUrl: 'http://127.0.0.1:43117',
  deviceAuthorizationBaseUrl: '',
  apiKey: 'fixture-owner',
  localApiToken: '',
  tenantId: 'default',
  projectId: 'project-1',
  workspaceId: '',
  workspaceRoot: '',
  mode: 'cloud',
};
const json = (body) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });

test('real Python cloud response preserves small/secondary declarations and distinguishes prefix filters', () => {
  const provider = normalizeManagedLlmProviderV2(fixture.response);
  assert.equal(provider.llm_small_model, 'ep-fast');
  assert.deepEqual(provider.secondary_models, ['ep-secondary']);
  assert.deepEqual(provider.audio_input_models, ['ep-fast', 'ep-secondary']);
  assert.deepEqual(providerEnabledModelIds(provider, 'cloud'), [
    'ep-primary',
    'ep-fast',
    'ep-secondary',
  ]);
  assert.deepEqual(provider.allowed_models, ['ep-']);
  for (const id of fixture.rejected) {
    assert.throws(
      () =>
        normalizeManagedLlmProviderV2({
          ...fixture.response,
          config: { ...fixture.response.config, audio_input_models: [id] },
        }),
      /Invalid provider audio input declaration/
    );
  }
  const draft = providerDraftFromProvider(provider, 'cloud');
  const mutation = providerMutationFromDraft(draft);
  assert.deepEqual(mutation.audioInputModels, ['ep-fast', 'ep-secondary']);
  assert.equal(mutation.smallModel, 'ep-fast');
  assert.deepEqual(mutation.secondaryModels, ['ep-secondary']);
  assert.deepEqual(
    providerMutationForActiveState(provider, false, 'cloud').providerConfig,
    provider.config
  );
});

test('cloud Models UI and routing present exact configured IDs and omit prefix filter rows', () => {
  const provider = normalizeManagedLlmProviderV2(fixture.response);
  const html = renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      { initialLocale: 'en' },
      React.createElement(ProviderModelsPanel, {
        provider,
        mode: 'cloud',
        canManage: true,
        allowAudioInputDeclaration: true,
        onLoadCatalog: async () => ({
          models: [],
          availability: 'unavailable',
        }),
        onSave: async () => provider,
      })
    )
  );
  for (const id of ['ep-primary', 'ep-fast', 'ep-secondary']) assert.ok(html.includes(id));
  assert.equal(html.includes('>ep-<'), false);
  const options = workspaceRuntimeModelOptions(
    { roles: { default: null }, fallbacks: [] },
    [provider],
    'default',
    'cloud'
  );
  assert.deepEqual(
    options.map((option) => option.modelId),
    ['ep-primary', 'ep-fast', 'ep-secondary']
  );
});

test('cloud model edits persist exact secondary roster, clear disabled small/audio and retain prefix filters/config', async () => {
  const previous = globalThis.fetch;
  let saved = structuredClone(fixture.response);
  const bodies = [];
  globalThis.fetch = async (_url, init) => {
    const body = JSON.parse(init.body);
    bodies.push(body);
    saved = { ...saved, ...body, revision: saved.revision + 1 };
    return json(saved);
  };
  try {
    const provider = normalizeManagedLlmProviderV2(saved);
    const mutation = providerMutationForEnabledModels(
      provider,
      ['ep-primary', 'ep-secondary', 'ep-added'],
      'cloud'
    );
    const client = createTenantProvidersHttpClientV2Fixture(runtime);
    const updated = await client.updateLlmProvider(provider.id, mutation);
    assert.equal(bodies[0].llm_small_model, null);
    assert.deepEqual(bodies[0].secondary_models, ['ep-secondary', 'ep-added']);
    assert.deepEqual(bodies[0].allowed_models, ['ep-']);
    assert.deepEqual(bodies[0].config, {
      temperature: 0.25,
      retries: { max_attempts: 2 },
      audio_input_models: ['ep-secondary'],
    });
    assert.deepEqual(providerEnabledModelIds(updated, 'cloud'), [
      'ep-primary',
      'ep-secondary',
      'ep-added',
    ]);
    assert.deepEqual(updated.audio_input_models, ['ep-secondary']);
    const declared = {
      ...providerMutationForActiveState(updated, false, 'cloud'),
      audioInputModels: ['ep-added'],
    };
    await client.updateLlmProvider(provider.id, declared);
    assert.deepEqual(bodies[1].config.audio_input_models, ['ep-added']);
    for (const id of fixture.rejected) {
      await assert.rejects(
        client.updateLlmProvider(provider.id, {
          ...declared,
          audioInputModels: [id],
        }),
        /audio_input_models_invalid/
      );
    }
    assert.equal(bodies.length, 2);
  } finally {
    globalThis.fetch = previous;
  }
});

test('cloud audio-only updates require an explicit public configuration snapshot before transport', async () => {
  const previous = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return json(fixture.response);
  };
  try {
    const provider = normalizeManagedLlmProviderV2(fixture.response);
    const { providerConfig: _snapshot, ...mutation } = providerMutationForActiveState(
      provider,
      true,
      'cloud'
    );
    const client = createTenantProvidersHttpClientV2Fixture(runtime);
    await assert.rejects(
      client.updateLlmProvider(provider.id, mutation),
      /public_config_snapshot_required/
    );
    assert.equal(calls, 0);
    // Explicit empty means there are no public settings to preserve; creation has no prior snapshot.
    await client.updateLlmProvider(provider.id, {
      ...mutation,
      providerConfig: {},
    });
    const { expectedRevision: _revision, ...create } = mutation;
    await client.createLlmProvider(create, 'fixture-cloud-create');
    assert.equal(calls, 2);
  } finally {
    globalThis.fetch = previous;
  }
});
