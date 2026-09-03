import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopWorkspaceContextTransactionClientProviderV2,
  DesktopWorkspaceContextTransactionClientProviderErrorV2,
  runDesktopWorkspaceContextOperationV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/' +
    'desktopWorkspaceContextTransactionClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('desktop workspace-context transaction client provider fails closed before publication', () => {
  const provider = createDesktopWorkspaceContextTransactionClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(
        error instanceof DesktopWorkspaceContextTransactionClientProviderErrorV2,
        true,
      );
      assert.equal(
        error.reasonCode,
        'desktop_workspace_context_transaction_client_unpublished',
      );
      assert.equal(
        error.message,
        'desktop_workspace_context_transaction_client_unpublished',
      );
      return true;
    },
  );
});

test('publication and operation bindings pin the exact three-method authority and config', async () => {
  const provider = createDesktopWorkspaceContextTransactionClientProviderV2();
  const publicationConfig = runtimeConfig(
    'http://127.0.0.1:44201',
    'publication-session',
    'publication-launch',
  );
  const publication = provider.publish({ config: publicationConfig });
  const operationConfig = runtimeConfig(
    'http://127.0.0.1:44202',
    'operation-session',
    'operation-launch',
  );
  const operationClient = publication.bindOperation(operationConfig);
  publicationConfig.apiBaseUrl = 'http://127.0.0.1:49998';
  operationConfig.apiBaseUrl = 'http://127.0.0.1:49999';
  operationConfig.apiKey = 'mutated-session';
  operationConfig.localApiToken = 'mutated-launch';
  const next = provider.publish({
    config: runtimeConfig(
      'http://127.0.0.1:44203',
      'next-session',
      'next-launch',
    ),
  });
  const originalFetch = globalThis.fetch;
  const calls = [];
  const controller = new AbortController();
  globalThis.fetch = async (input, init) => {
    const url = new URL(String(input));
    calls.push({ url, init });
    if (url.pathname === '/api/v1/projects') {
      return json({
        projects: [{ id: 'project / one', tenant_id: 'tenant / one', name: 'Project one' }],
        total: 1,
        page: 1,
        page_size: 100,
      });
    }
    if (url.pathname === '/api/v1/workspace-context') {
      return json({
        context: workspaceContext('tenant-old', 'project-old', 6),
        membership_role: 'owner',
      });
    }
    return json({
      context: workspaceContext('tenant / one', 'project / one', 7),
      changed: true,
    });
  };

  try {
    const projects = await operationClient.listProjects('tenant / one', controller.signal);
    const current = await operationClient.getWorkspaceContext(controller.signal);
    const switched = await operationClient.switchWorkspaceContext(
      'tenant / one',
      'project / one',
      current.context.revision,
      'context-switch / one',
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
    assert.deepEqual(Object.keys(publication.client), [
      'listProjects',
      'getWorkspaceContext',
      'switchWorkspaceContext',
    ]);
    assert.deepEqual(Object.keys(operationClient), [
      'listProjects',
      'getWorkspaceContext',
      'switchWorkspaceContext',
    ]);
    assert.equal('listTenants' in operationClient, false);
    assert.equal('currentUser' in operationClient, false);
    assert.equal(projects[0].id, 'project / one');
    assert.equal(switched.context.revision, 7);
    assert.deepEqual(
      calls.map(({ url, init }) => [url.origin, url.pathname, init.method ?? 'GET']),
      [
        ['http://127.0.0.1:44202', '/api/v1/projects', 'GET'],
        ['http://127.0.0.1:44202', '/api/v1/workspace-context', 'GET'],
        ['http://127.0.0.1:44202', '/api/v1/workspace-context/switch', 'POST'],
      ],
    );
    assert.equal(calls[0].url.searchParams.get('tenant_id'), 'tenant / one');
    assert.equal(calls[0].url.searchParams.get('page'), '1');
    assert.equal(calls[0].url.searchParams.get('page_size'), '100');
    assert.deepEqual(JSON.parse(String(calls[2].init.body)), {
      tenant_id: 'tenant / one',
      project_id: 'project / one',
      expected_revision: 6,
      idempotency_key: 'context-switch / one',
    });
    for (const call of calls) {
      assert.equal(call.init.signal, controller.signal);
      const headers = new Headers(call.init.headers);
      assert.equal(headers.get('Authorization'), 'Bearer operation-session');
      assert.equal(headers.get('X-Agistack-Launch'), 'operation-launch');
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('workspace-context operations hold one generation lease until settlement', async () => {
  let releaseCount = 0;
  let settleOperation;
  const operation = new Promise((resolve) => {
    settleOperation = resolve;
  });
  const pending = runDesktopWorkspaceContextOperationV2(
    () => ({
      digest: 'sha256:generation-one',
      kind: 'generation',
      release: async () => {
        releaseCount += 1;
      },
    }),
    async () => operation,
  );

  await Promise.resolve();
  assert.equal(releaseCount, 0);
  settleOperation('done');
  assert.equal(await pending, 'done');
  assert.equal(releaseCount, 1);
});

test('workspace-context operations fail closed without a generation and release exactly once', async () => {
  let releaseCount = 0;
  let operationCount = 0;

  await assert.rejects(
    runDesktopWorkspaceContextOperationV2(
      () => ({
        digest: undefined,
        kind: 'authentication-kernel',
        release: async () => {
          releaseCount += 1;
        },
      }),
      async () => {
        operationCount += 1;
      },
    ),
    (error) => {
      assert.equal(
        error instanceof DesktopWorkspaceContextTransactionClientProviderErrorV2,
        true,
      );
      assert.equal(
        error.reasonCode,
        'desktop_workspace_context_transaction_generation_unavailable',
      );
      return true;
    },
  );
  assert.equal(operationCount, 0);
  assert.equal(releaseCount, 1);
});

test('lease cleanup errors never replace a workspace-context operation error', async () => {
  const operationError = new Error('workspace_context_operation_failed');

  await assert.rejects(
    runDesktopWorkspaceContextOperationV2(
      () => ({
        digest: 'sha256:generation-two',
        kind: 'generation',
        release: async () => {
          throw new Error('workspace_context_release_failed');
        },
      }),
      async () => {
        throw operationError;
      },
    ),
    (error) => error === operationError,
  );
});

test('failed workspace-context publication keeps the last-good binding', () => {
  const provider = createDesktopWorkspaceContextTransactionClientProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get apiBaseUrl() {
      throw new Error('candidate_workspace_context_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_workspace_context_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

function runtimeConfig(apiBaseUrl, apiKey, localApiToken) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl,
    apiKey,
    localApiToken,
    mode: 'local',
    tenantId: 'tenant-publication',
    projectId: 'project-publication',
    workspaceId: 'workspace-publication',
  };
}

function workspaceContext(tenantId, projectId, revision) {
  return {
    tenant_id: tenantId,
    project_id: projectId,
    revision,
    updated_at: '2026-09-01T00:00:00Z',
  };
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
