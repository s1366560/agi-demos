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
const { createDesktopNativeKnowledgeInputsClientV2 } = require(
  `${root}/src/plugins/desktopNativeKnowledgeInputsClientV2.js`,
);
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
  revision: 3,
  is_active: true,
  llm_model: 'opaque-a',
  allowed_models: ['opaque-a', 'opaque-b'],
  embedding_model: 'opaque-b',
};
const mutation = {
  name: 'Configured provider',
  providerType: 'openai_compatible',
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

test('provider V2 saves and clears explicit embedding model using the existing revision-bound mutation', async () => {
  const previous = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (_url, init) => {
    const body = JSON.parse(init.body);
    requests.push(body);
    return json({ ...provider, revision: 4, embedding_model: body.embedding_model || null });
  };
  try {
    const client = createTenantProvidersHttpClientV2Fixture(runtime);
    const saved = await client.updateLlmProvider(provider.id, {
      ...mutation,
      embeddingModel: 'opaque-b',
    });
    assert.equal(requests[0].embedding_model, 'opaque-b');
    assert.equal(requests[0].expected_revision, 3);
    assert.equal(saved.embedding_model, 'opaque-b');
    assert.equal(saved.revision, 4);
    await client.updateLlmProvider(provider.id, { ...mutation, embeddingModel: '' });
    assert.equal(requests[1].embedding_model, '');
    await client.updateLlmProvider(provider.id, mutation);
    assert.equal('embedding_model' in requests[2], false);
  } finally {
    globalThis.fetch = previous;
  }
});

test('embedding declaration rejects unlisted and malformed model IDs before transport', async () => {
  const previous = globalThis.fetch;
  let count = 0;
  globalThis.fetch = async () => {
    count++;
    return json(provider);
  };
  try {
    const client = createTenantProvidersHttpClientV2Fixture(runtime);
    for (const embeddingModel of ['not-allowed', ' opaque-b ', 3, null])
      await assert.rejects(
        client.updateLlmProvider(provider.id, { ...mutation, embeddingModel }),
        /embedding_model_invalid/,
      );
    assert.equal(count, 0);
  } finally {
    globalThis.fetch = previous;
  }
});

test('actual typed provider catalog projection supplies explicit configuration to native inputs adapter', async () => {
  const previous = globalThis.fetch;
  const nativeScope = {
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    context_revision: 7,
    profile_id: 'profile',
    generation: 1,
    digest: 'digest',
  };
  const scope = { authority: 'local', tenantId: 'tenant-1', projectId: 'project-1' };
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ path: new URL(url).pathname, body: init.body ? JSON.parse(init.body) : null });
    // Exact native producer shape: role comes from saved provider configuration.
    return json(
      new URL(url).pathname.endsWith('/models/discover')
        ? {
            provider_id: provider.id,
            provider_type: provider.provider_type,
            availability: 'available',
            source: 'provider-api+explicit-configuration',
            models: { chat: ['opaque-a', 'opaque-b'], embedding: ['opaque-b'], rerank: [] },
          }
        : [provider],
    );
  };
  try {
    const client = createDesktopNativeKnowledgeInputsClientV2(runtime, {
      processing: { query: async () => ({ scope: nativeScope }) },
      providers: createTenantProvidersHttpClientV2Fixture(runtime),
      workspaces: {
        listWorkspacesForProject: async () => {
          throw Error('unrelated workspace lookup');
        },
      },
      isCurrent: () => true,
    });
    const inputs = await client.load(scope, {
      operation: 'configure_embedding',
      expectedScope: nativeScope,
    });
    assert.deepEqual(inputs.embeddingModels.items, [
      {
        providerId: provider.id,
        providerName: provider.name,
        providerRevision: 3,
        modelId: 'opaque-b',
      },
    ]);
    assert.deepEqual(requests[1].body, { expected_revision: 3 });
    assert.equal(inputs.workspaces.availability, 'unavailable');
  } finally {
    globalThis.fetch = previous;
  }
});

test('native provider editor exposes an explicit enabled-model selector; readonly and cloud stay bounded', () => {
  const render = (extra) =>
    renderToStaticMarkup(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(ProviderModelsPanel, {
          provider,
          canManage: true,
          onLoadCatalog: async () => ({ availability: 'unavailable', models: [] }),
          onSave: async () => provider,
          ...extra,
        }),
      ),
    );
  const html = render({ allowEmbeddingDeclaration: true });
  assert.match(html, /Model to use for embeddings/);
  assert.match(html, /<option value="opaque-b" selected=""/);
  assert.match(html, /Knowledge configuration verifies the actual embedding API/);
  assert.doesNotMatch(render({ allowEmbeddingDeclaration: false }), /Model to use for embeddings/);
  assert.match(
    render({ allowEmbeddingDeclaration: true, canManage: false }),
    /<select[^>]*disabled=""/,
  );
});
