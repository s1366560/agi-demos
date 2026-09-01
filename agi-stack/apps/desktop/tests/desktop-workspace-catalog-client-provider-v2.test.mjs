import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopWorkspaceCatalogClientProviderV2,
  DesktopWorkspaceCatalogClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/' +
    'desktopWorkspaceCatalogClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('desktop workspace catalog client provider fails closed before publication', () => {
  const provider = createDesktopWorkspaceCatalogClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(error instanceof DesktopWorkspaceCatalogClientProviderErrorV2, true);
      assert.equal(error.reasonCode, 'desktop_workspace_catalog_client_unpublished');
      assert.equal(error.message, 'desktop_workspace_catalog_client_unpublished');
      return true;
    },
  );
});

test('publications and operation bindings pin frozen one-method workspace catalog clients', async () => {
  const provider = createDesktopWorkspaceCatalogClientProviderV2();
  const publicationConfig = runtimeConfig(
    'http://127.0.0.1:43901',
    'publication-session',
    'publication-launch',
    'tenant-1',
    'project-1',
  );
  const publication = provider.publish({ config: publicationConfig });
  const operationConfig = runtimeConfig(
    'http://127.0.0.1:43902',
    'operation-session',
    'operation-launch',
    'tenant / operation',
    'project / operation',
  );
  const operationClient = publication.bindOperation(operationConfig);
  publicationConfig.apiBaseUrl = 'http://127.0.0.1:49998';
  operationConfig.apiBaseUrl = 'http://127.0.0.1:49999';
  operationConfig.apiKey = 'mutated-session';
  operationConfig.localApiToken = 'mutated-launch';
  operationConfig.tenantId = 'mutated-tenant';
  operationConfig.projectId = 'mutated-project';
  const next = provider.publish({
    config: runtimeConfig(
      'http://127.0.0.1:43903',
      'next-session',
      'next-launch',
      'tenant-2',
      'project-2',
    ),
  });
  const originalFetch = globalThis.fetch;
  const calls = [];
  const controller = new AbortController();
  globalThis.fetch = async (input, init) => {
    calls.push({ url: new URL(String(input)), init });
    return json([workspaceRecord('tenant / operation', 'project / operation')]);
  };

  try {
    await operationClient.listWorkspacesForProject(
      'project / operation',
      'tenant / operation',
      controller.signal,
    );

    assert.equal(Object.isFrozen(provider), true);
    assert.equal(Object.isFrozen(publication), true);
    assert.equal(Object.isFrozen(publication.client), true);
    assert.equal(Object.isFrozen(operationClient), true);
    assert.equal(Object.isFrozen(next), true);
    assert.notEqual(publication, next);
    assert.notEqual(publication.client, next.client);
    assert.equal(provider.resolve(), next);
    assert.deepEqual(Object.keys(publication.client), ['listWorkspacesForProject']);
    assert.deepEqual(Object.keys(operationClient), ['listWorkspacesForProject']);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url.origin, 'http://127.0.0.1:43902');
    assert.equal(
      calls[0].url.pathname,
      '/api/v1/tenants/tenant%20%2F%20operation/projects/project%20%2F%20operation/workspaces',
    );
    assert.equal(calls[0].url.searchParams.get('limit'), '500');
    assert.equal(calls[0].url.searchParams.get('offset'), '0');
    assert.equal(calls[0].init.signal, controller.signal);
    const headers = new Headers(calls[0].init.headers);
    assert.equal(headers.get('Authorization'), 'Bearer operation-session');
    assert.equal(headers.get('X-Agistack-Launch'), 'operation-launch');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('failed workspace catalog publication keeps the last-good binding', () => {
  const provider = createDesktopWorkspaceCatalogClientProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get apiBaseUrl() {
      throw new Error('candidate_workspace_catalog_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_workspace_catalog_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

function runtimeConfig(apiBaseUrl, apiKey, localApiToken, tenantId, projectId) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl,
    apiKey,
    localApiToken,
    tenantId,
    projectId,
    workspaceId: '',
    mode: 'local',
  };
}

function workspaceRecord(tenantId, projectId) {
  return {
    id: 'workspace-1',
    tenant_id: tenantId,
    project_id: projectId,
    name: 'Workspace 1',
    created_by: 'user-1',
    description: null,
    is_archived: false,
    metadata: {},
    office_status: 'idle',
    hex_layout_config: {},
    created_at: '2026-09-01T00:00:00Z',
    updated_at: null,
  };
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
