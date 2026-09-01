import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopWorkspaceMessageCatalogClientProviderV2,
  DesktopWorkspaceMessageCatalogClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/' +
    'desktopWorkspaceMessageCatalogClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('desktop workspace message catalog client provider fails closed before publication', () => {
  const provider = createDesktopWorkspaceMessageCatalogClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(
        error instanceof DesktopWorkspaceMessageCatalogClientProviderErrorV2,
        true,
      );
      assert.equal(
        error.reasonCode,
        'desktop_workspace_message_catalog_client_unpublished',
      );
      assert.equal(
        error.message,
        'desktop_workspace_message_catalog_client_unpublished',
      );
      return true;
    },
  );
});

test('publications and operation bindings pin frozen message catalog read clients', async () => {
  const provider = createDesktopWorkspaceMessageCatalogClientProviderV2();
  const publicationConfig = runtimeConfig(
    'http://127.0.0.1:43801',
    'publication-session',
    'publication-launch',
    'tenant-1',
    'project-1',
    'workspace-1',
  );
  const publication = provider.publish({ config: publicationConfig });
  const operationConfig = runtimeConfig(
    'http://127.0.0.1:43802',
    'operation-session',
    'operation-launch',
    'tenant / operation',
    'project / operation',
    'workspace / operation',
  );
  const operationClient = publication.bindOperation(operationConfig);
  publicationConfig.apiBaseUrl = 'http://127.0.0.1:49998';
  operationConfig.apiBaseUrl = 'http://127.0.0.1:49999';
  operationConfig.apiKey = 'mutated-session';
  operationConfig.localApiToken = 'mutated-launch';
  operationConfig.tenantId = 'mutated-tenant';
  operationConfig.projectId = 'mutated-project';
  operationConfig.workspaceId = 'mutated-workspace';
  const next = provider.publish({
    config: runtimeConfig(
      'http://127.0.0.1:43803',
      'next-session',
      'next-launch',
      'tenant-2',
      'project-2',
      'workspace-2',
    ),
  });
  const originalFetch = globalThis.fetch;
  const calls = [];
  const controller = new AbortController();
  globalThis.fetch = async (input, init) => {
    calls.push({ url: new URL(String(input)), init });
    return json({
      messages: [
        {
          id: 'message-1',
          workspace_id: 'workspace / operation',
          content: 'Pinned message catalog',
        },
      ],
    });
  };

  try {
    const messages = await operationClient.listMessages(controller.signal);

    assert.equal(Object.isFrozen(provider), true);
    assert.equal(Object.isFrozen(publication), true);
    assert.equal(Object.isFrozen(publication.client), true);
    assert.equal(Object.isFrozen(operationClient), true);
    assert.equal(Object.isFrozen(next), true);
    assert.notEqual(publication, next);
    assert.notEqual(publication.client, next.client);
    assert.equal(provider.resolve(), next);
    assert.deepEqual(Object.keys(publication.client), ['listMessages']);
    assert.deepEqual(Object.keys(operationClient), ['listMessages']);
    assert.equal('sendMessage' in operationClient, false);
    assert.equal('listTasks' in operationClient, false);
    assert.equal('getPlanSnapshot' in operationClient, false);
    assert.equal(messages[0].content, 'Pinned message catalog');
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url.origin, 'http://127.0.0.1:43802');
    assert.equal(
      calls[0].url.pathname,
      '/api/v1/tenants/tenant%20%2F%20operation/projects/project%20%2F%20operation/' +
        'workspaces/workspace%20%2F%20operation/messages',
    );
    assert.equal(calls[0].init.signal, controller.signal);
    const headers = new Headers(calls[0].init.headers);
    assert.equal(headers.get('Authorization'), 'Bearer operation-session');
    assert.equal(headers.get('X-Agistack-Launch'), 'operation-launch');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('failed workspace message catalog publication keeps the last-good binding', () => {
  const provider = createDesktopWorkspaceMessageCatalogClientProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get apiBaseUrl() {
      throw new Error('candidate_workspace_message_catalog_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_workspace_message_catalog_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

function runtimeConfig(
  apiBaseUrl,
  apiKey,
  localApiToken,
  tenantId,
  projectId,
  workspaceId,
) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl,
    apiKey,
    localApiToken,
    tenantId,
    projectId,
    workspaceId,
    mode: 'local',
  };
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
