import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { createTenantProvidersHttpClientV2Fixture } from './tenantProvidersOperationsV2Fixture.mjs';

const require = createRequire(import.meta.url);
const root = '/tmp/agistack-desktop-test-dist';
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require(`${root}/src/i18n.js`);
const { ProviderRequestTimeoutField } = require(
  `${root}/src/features/settings/ProviderRequestTimeoutField.js`,
);
const {
  providerDraftFromProvider,
  providerMutationFromDraft,
  providerMutationForActiveState,
  providerMutationForEnabledModels,
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
  request_timeout_ms: 120_000,
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

test('provider timeout survives create, list, edit, activation and model changes', async () => {
  const previous = globalThis.fetch;
  const requests = [];
  let saved = { ...provider };
  globalThis.fetch = async (_url, init) => {
    if (!init.body) return json([saved]);
    const body = JSON.parse(init.body);
    requests.push(body);
    saved = { ...saved, request_timeout_ms: body.request_timeout_ms ?? saved.request_timeout_ms };
    return json(saved);
  };
  try {
    const client = createTenantProvidersHttpClientV2Fixture(runtime);
    const created = await client.createLlmProvider(
      { ...mutation, requestTimeoutMs: 120_000 },
      'request-timeout-create',
    );
    assert.equal(created.request_timeout_ms, 120_000);
    const [listed] = await client.listLlmProviders();
    const draft = providerDraftFromProvider(listed);
    assert.equal(draft.requestTimeoutMs, 120_000);
    draft.requestTimeoutMs = 90_000;
    const updated = await client.updateLlmProvider(provider.id, providerMutationFromDraft(draft));
    assert.equal(updated.request_timeout_ms, 90_000);
    await client.updateLlmProvider(provider.id, providerMutationForActiveState(updated, false));
    await client.updateLlmProvider(
      provider.id,
      providerMutationForEnabledModels(updated, ['opaque-a']),
    );
    await client.updateLlmProvider(provider.id, mutation);
    assert.deepEqual(requests.map((body) => body.request_timeout_ms), [
      120_000, 90_000, 90_000, 90_000, undefined,
    ]);
    assert.equal(requests[1].expected_revision, 3);
    assert.equal(saved.request_timeout_ms, 90_000);
  } finally {
    globalThis.fetch = previous;
  }
});

test('provider timeout rejects malformed and unbounded values before transport', async () => {
  const previous = globalThis.fetch;
  let requests = 0;
  globalThis.fetch = async () => {
    requests++;
    return json(provider);
  };
  try {
    const client = createTenantProvidersHttpClientV2Fixture(runtime);
    for (const requestTimeoutMs of [0, -1, 300_001, 1.5, '120000', null]) {
      await assert.rejects(
        client.updateLlmProvider(provider.id, { ...mutation, requestTimeoutMs }),
        /request_timeout_invalid/,
      );
    }
    for (const requestTimeoutMs of [NaN, Infinity]) {
      await assert.rejects(
        client.updateLlmProvider(provider.id, { ...mutation, requestTimeoutMs }),
        /tenant_provider_json_invalid/,
      );
    }
    assert.equal(requests, 0);
    for (const requestTimeoutMs of [1, 45_000, 300_000]) {
      await client.updateLlmProvider(provider.id, { ...mutation, requestTimeoutMs });
    }
    assert.equal(requests, 3);
  } finally {
    globalThis.fetch = previous;
  }
});

test('provider response rejects invalid timeout and preserves legacy omission', async () => {
  const previous = globalThis.fetch;
  let timeout;
  globalThis.fetch = async () => json([{ ...provider, request_timeout_ms: timeout }]);
  try {
    const client = createTenantProvidersHttpClientV2Fixture(runtime);
    const [legacy] = await client.listLlmProviders();
    assert.equal('request_timeout_ms' in legacy, false);
    assert.equal(
      'requestTimeoutMs' in providerMutationFromDraft(providerDraftFromProvider(legacy)),
      false,
    );
    for (timeout of [0, 300_001, '45000', null]) {
      await assert.rejects(client.listLlmProviders(), /Invalid provider request timeout/);
    }
  } finally {
    globalThis.fetch = previous;
  }
});

test('provider timeout field renders seconds, bounded input and readonly state', () => {
  const render = (props) =>
    renderToStaticMarkup(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(ProviderRequestTimeoutField, { onChange: () => {}, ...props }),
      ),
    );
  const html = render({});
  assert.match(html, /type="number"/);
  assert.match(html, /min="0.001"/);
  assert.match(html, /max="300"/);
  assert.match(html, /value="45"/);
  assert.match(render({ value: 120_000, disabled: true }), /disabled=""[^>]*value="120"/);
});
