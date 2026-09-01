import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopWorkspaceExecutionSnapshotClientProviderV2,
  DesktopWorkspaceExecutionSnapshotClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/' +
    'desktopWorkspaceExecutionSnapshotClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('desktop workspace execution snapshot client provider fails closed before publication', () => {
  const provider = createDesktopWorkspaceExecutionSnapshotClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(
        error instanceof DesktopWorkspaceExecutionSnapshotClientProviderErrorV2,
        true,
      );
      assert.equal(
        error.reasonCode,
        'desktop_workspace_execution_snapshot_client_unpublished',
      );
      assert.equal(
        error.message,
        'desktop_workspace_execution_snapshot_client_unpublished',
      );
      return true;
    },
  );
});

test('publications and operation bindings pin frozen task and plan snapshot clients', async () => {
  const provider = createDesktopWorkspaceExecutionSnapshotClientProviderV2();
  const publicationConfig = runtimeConfig(
    'http://127.0.0.1:44001',
    'publication-session',
    'publication-launch',
    'workspace-1',
  );
  const publication = provider.publish({ config: publicationConfig });
  const operationConfig = runtimeConfig(
    'http://127.0.0.1:44002',
    'operation-session',
    'operation-launch',
    'workspace / operation',
  );
  const operationClient = publication.bindOperation(operationConfig);
  publicationConfig.apiBaseUrl = 'http://127.0.0.1:49998';
  operationConfig.apiBaseUrl = 'http://127.0.0.1:49999';
  operationConfig.apiKey = 'mutated-session';
  operationConfig.localApiToken = 'mutated-launch';
  operationConfig.workspaceId = 'mutated-workspace';
  const next = provider.publish({
    config: runtimeConfig(
      'http://127.0.0.1:44003',
      'next-session',
      'next-launch',
      'workspace-2',
    ),
  });
  const originalFetch = globalThis.fetch;
  const calls = [];
  const controller = new AbortController();
  globalThis.fetch = async (input, init) => {
    const url = new URL(String(input));
    calls.push({ url, init });
    if (url.pathname.endsWith('/tasks')) {
      return json({ tasks: [{ id: 'task-1', title: 'Pinned task snapshot' }] });
    }
    return json({ id: 'plan-1', title: 'Pinned plan snapshot', tasks: [] });
  };

  try {
    const [tasks, plan] = await Promise.all([
      operationClient.listTasks(controller.signal),
      operationClient.getPlanSnapshot(controller.signal),
    ]);

    assert.equal(Object.isFrozen(provider), true);
    assert.equal(Object.isFrozen(publication), true);
    assert.equal(Object.isFrozen(publication.client), true);
    assert.equal(Object.isFrozen(operationClient), true);
    assert.equal(Object.isFrozen(next), true);
    assert.notEqual(publication, next);
    assert.notEqual(publication.client, next.client);
    assert.equal(provider.resolve(), next);
    assert.deepEqual(Object.keys(publication.client), ['listTasks', 'getPlanSnapshot']);
    assert.deepEqual(Object.keys(operationClient), ['listTasks', 'getPlanSnapshot']);
    assert.equal('listMessages' in operationClient, false);
    assert.equal('sendMessage' in operationClient, false);
    assert.equal(tasks[0].title, 'Pinned task snapshot');
    assert.equal(plan.title, 'Pinned plan snapshot');
    assert.deepEqual(
      calls.map(({ url }) => `${url.origin}${url.pathname}`).sort(),
      [
        'http://127.0.0.1:44002/api/v1/workspaces/workspace%20%2F%20operation/plan',
        'http://127.0.0.1:44002/api/v1/workspaces/workspace%20%2F%20operation/tasks',
      ],
    );
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

test('failed workspace execution snapshot publication keeps the last-good binding', () => {
  const provider = createDesktopWorkspaceExecutionSnapshotClientProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get apiBaseUrl() {
      throw new Error('candidate_workspace_execution_snapshot_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_workspace_execution_snapshot_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

function runtimeConfig(apiBaseUrl, apiKey, localApiToken, workspaceId) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl,
    apiKey,
    localApiToken,
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
