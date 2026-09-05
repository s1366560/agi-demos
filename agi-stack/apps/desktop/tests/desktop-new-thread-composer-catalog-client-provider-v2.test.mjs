import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopNewThreadComposerCatalogClientProviderV2,
  DesktopNewThreadComposerCatalogClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/task/' +
    'desktopNewThreadComposerCatalogClientProviderV2.js'
);
const {
  loadComposerCatalog,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/composerCatalogModel.js');
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');
const { DesktopApiClient } = require('/tmp/agistack-desktop-test-dist/src/api/client.js');
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const providerSource = readFileSync(
  new URL(
    '../src/features/task/desktopNewThreadComposerCatalogClientProviderV2.ts',
    import.meta.url
  ),
  'utf8'
);

test('desktop new-thread composer catalog provider fails closed before publication', () => {
  const provider = createDesktopNewThreadComposerCatalogClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(error instanceof DesktopNewThreadComposerCatalogClientProviderErrorV2, true);
      assert.equal(error.reasonCode, 'desktop_new_thread_composer_catalog_client_unpublished');
      assert.equal(error.message, 'desktop_new_thread_composer_catalog_client_unpublished');
      return true;
    }
  );
});

test('bound publications pin one frozen composer catalog client to each workspace generation', async () => {
  const provider = createDesktopNewThreadComposerCatalogClientProviderV2();
  const firstConfig = runtimeConfig('http://127.0.0.1:42001', 'workspace-1');
  const first = provider.publish({
    config: firstConfig,
    pluginMarketplaceOperationsV2: pluginMarketplaceOperationsV2(),
    tenantAgentDefinitionsOperationsV2: tenantAgentDefinitionsOperationsV2(),
    tenantPromptTemplatesOperationsV2: tenantPromptTemplatesOperationsV2(),
    workspaceRosterOperationsV2: workspaceRosterOperationsV2(),
  });
  firstConfig.apiBaseUrl = 'http://127.0.0.1:49999';
  firstConfig.workspaceId = 'workspace-poisoned';
  const second = provider.publish({
    config: runtimeConfig('http://127.0.0.1:42002', 'workspace-2'),
    pluginMarketplaceOperationsV2: pluginMarketplaceOperationsV2(),
    tenantAgentDefinitionsOperationsV2: tenantAgentDefinitionsOperationsV2(),
    tenantPromptTemplatesOperationsV2: tenantPromptTemplatesOperationsV2(),
    workspaceRosterOperationsV2: workspaceRosterOperationsV2(),
  });
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input) => {
    calls.push(String(input));
    return json([]);
  };

  try {
    await first.client.listWorkspaceAgents();
    await second.client.listWorkspaceAgents();

    assert.equal(Object.isFrozen(first), true);
    assert.equal(Object.isFrozen(first.client), true);
    assert.equal(Object.isFrozen(second), true);
    assert.equal(Object.isFrozen(second.client), true);
    assert.notEqual(first, second);
    assert.notEqual(first.client, second.client);
    assert.equal(provider.resolve(), second);
    assert.deepEqual(calls, [
      workspaceAgentsUrl('http://127.0.0.1:42001', 'workspace-1'),
      workspaceAgentsUrl('http://127.0.0.1:42002', 'workspace-2'),
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('unbound publications hide workspace agents while retaining project catalogs and upload', async () => {
  const provider = createDesktopNewThreadComposerCatalogClientProviderV2();
  const publication = provider.publish({
    config: runtimeConfig('http://127.0.0.1:42003', ''),
    pluginMarketplaceOperationsV2: pluginMarketplaceOperationsV2(),
    tenantAgentDefinitionsOperationsV2: tenantAgentDefinitionsOperationsV2(),
    tenantPromptTemplatesOperationsV2: tenantPromptTemplatesOperationsV2(),
    workspaceRosterOperationsV2: workspaceRosterOperationsV2(),
  });
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input) => {
    const url = String(input);
    calls.push(url);
    if (url.endsWith('/api/v1/projects/project-1/sandbox/execute')) {
      return json({
        success: true,
        is_error: false,
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              success: true,
              path: '/workspace/input/evidence.txt',
              size_bytes: 2,
            }),
          },
        ],
      });
    }
    return json([]);
  };

  try {
    const catalog = await loadComposerCatalog(publication.client);
    const uploaded = await publication.client.uploadSandboxFile({
      name: 'evidence.txt',
      type: 'text/plain',
      size: 2,
      arrayBuffer: async () => Uint8Array.from([1, 2]).buffer,
    });

    assert.deepEqual(catalog, {
      workspaceAgents: [],
      agents: [],
      skills: [],
      plugins: [],
      subagents: [],
    });
    assert.deepEqual(uploaded, {
      filename: 'evidence.txt',
      sandbox_path: '/workspace/input/evidence.txt',
      mime_type: 'text/plain',
      size_bytes: 2,
    });
    assert.equal(
      calls.some((url) => url.includes('/workspaces/')),
      false
    );
    assert.equal(
      calls.some((url) => url.includes('/agent/definitions?')),
      false
    );
    assert.equal(
      calls.some((url) => url.includes('/skills/?')),
      true
    );
    assert.equal(
      calls.some((url) => url.includes('/plugin-marketplace/packages?')),
      true
    );
    assert.equal(
      calls.some((url) => url.includes('/subagents/?')),
      true
    );
    assert.equal(
      calls.some((url) => url.endsWith('/sandbox/execute')),
      true
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('failed composer catalog publication keeps the last-good binding', () => {
  const provider = createDesktopNewThreadComposerCatalogClientProviderV2();
  const lastGood = provider.publish({
    config: DEFAULT_CONFIG,
    pluginMarketplaceOperationsV2: pluginMarketplaceOperationsV2(),
    tenantAgentDefinitionsOperationsV2: tenantAgentDefinitionsOperationsV2(),
    tenantPromptTemplatesOperationsV2: tenantPromptTemplatesOperationsV2(),
    workspaceRosterOperationsV2: workspaceRosterOperationsV2(),
  });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get workspaceId() {
      throw new Error('candidate_new_thread_composer_catalog_config_invalid');
    },
  };

  assert.throws(
    () =>
      provider.publish({
        config: poisonedConfig,
        pluginMarketplaceOperationsV2: pluginMarketplaceOperationsV2(),
        tenantAgentDefinitionsOperationsV2: tenantAgentDefinitionsOperationsV2(),
        tenantPromptTemplatesOperationsV2: tenantPromptTemplatesOperationsV2(),
        workspaceRosterOperationsV2: workspaceRosterOperationsV2(),
      }),
    /candidate_new_thread_composer_catalog_config_invalid/u
  );
  assert.equal(provider.resolve(), lastGood);
});

test('App consumes the published V2 catalog client without constructing a new-thread API client', () => {
  assert.match(appSource, /desktopNewThreadComposerCatalogClientProviderV2\.publish/u);
  assert.match(appSource, /config: newThreadRuntimeConfig/u);
  assert.match(appSource, /pluginMarketplaceOperationsV2:\s*desktopPluginMarketplaceOperationsV2/u);
  assert.match(appSource, /api:\s*desktopNewThreadComposerCatalogClientV2\.client/u);
  assert.doesNotMatch(appSource, /const newThreadApi =/u);
  assert.doesNotMatch(appSource, /new DesktopApiClient\(newThreadRuntimeConfig\)/u);
  assert.match(providerSource, /new DesktopApiClient\(config\)/u);
  assert.match(
    providerSource,
    /input\.pluginMarketplaceOperationsV2\.listMarketplacePlugins\(config/u
  );
  assert.match(
    providerSource,
    /createDesktopTenantAgentDefinitionsClientV2\(\s*input\.tenantAgentDefinitionsOperationsV2/u
  );
  assert.match(
    providerSource,
    /createDesktopTenantPromptTemplatesClientV2\(\s*input\.tenantPromptTemplatesOperationsV2/u
  );
  assert.match(providerSource, /input\.workspaceRosterOperationsV2\.listWorkspaceAgents/u);
  for (const method of [
    'listWorkspaceAgents',
    'listManagedAgents',
    'listManagedSkills',
    'listMarketplacePlugins',
    'listManagedSubAgents',
    'uploadSandboxFile',
  ]) {
    assert.match(providerSource, new RegExp(`${method}:`));
  }
});

function workspaceAgentsUrl(apiBaseUrl, workspaceId) {
  const scopePath = `/api/v1/tenants/tenant-1/projects/project-1/workspaces/${workspaceId}`;
  return `${apiBaseUrl}${scopePath}/agents?active_only=false&limit=500&offset=0`;
}

function pluginMarketplaceOperationsV2() {
  return {
    listMarketplacePlugins: (config, signal) =>
      new DesktopApiClient(config).listMarketplacePlugins(signal),
  };
}

function tenantAgentDefinitionsOperationsV2() {
  return {
    loadTenantAgentDefinitions: async () => [],
  };
}

function tenantPromptTemplatesOperationsV2() {
  return {
    listTenantPromptTemplates: async () => [],
    createTenantPromptTemplate: async () => {
      throw new Error('prompt_template_create_not_used');
    },
    deleteTenantPromptTemplate: async () => {},
  };
}

function workspaceRosterOperationsV2() {
  return {
    listWorkspaceAgents: ({ config, signal }) =>
      new DesktopApiClient(config).listWorkspaceAgents(signal),
  };
}

function runtimeConfig(apiBaseUrl, workspaceId) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl,
    localApiToken: 'local-session-token',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId,
    mode: 'local',
  };
}

function json(payload) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}
