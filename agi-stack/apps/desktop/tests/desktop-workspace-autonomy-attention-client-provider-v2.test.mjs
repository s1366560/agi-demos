import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopWorkspaceAutonomyAttentionClientProviderV2,
  DesktopWorkspaceAutonomyAttentionClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/' +
    'desktopWorkspaceAutonomyAttentionClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('desktop workspace autonomy attention client provider fails closed before publication', () => {
  const provider = createDesktopWorkspaceAutonomyAttentionClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(
        error instanceof DesktopWorkspaceAutonomyAttentionClientProviderErrorV2,
        true,
      );
      assert.equal(
        error.reasonCode,
        'desktop_workspace_autonomy_attention_client_unpublished',
      );
      assert.equal(
        error.message,
        'desktop_workspace_autonomy_attention_client_unpublished',
      );
      return true;
    },
  );
});

test('publications and operation bindings pin frozen four-method attention clients', async () => {
  const provider = createDesktopWorkspaceAutonomyAttentionClientProviderV2();
  const publicationConfig = runtimeConfig(
    'http://127.0.0.1:43801',
    'publication-session',
    'publication-launch',
  );
  const publication = provider.publish({ config: publicationConfig });
  const operationConfig = runtimeConfig(
    'http://127.0.0.1:43802',
    'operation-session',
    'operation-launch',
  );
  operationConfig.tenantId = 'tenant / operation';
  operationConfig.projectId = 'project / operation';
  operationConfig.workspaceId = 'workspace / operation';
  const operationClient = publication.bindOperation(operationConfig);
  publicationConfig.apiBaseUrl = 'http://127.0.0.1:49998';
  operationConfig.apiBaseUrl = 'http://127.0.0.1:49999';
  operationConfig.apiKey = 'mutated-session';
  operationConfig.localApiToken = 'mutated-launch';
  operationConfig.workspaceId = 'mutated-workspace';

  const originalFetch = globalThis.fetch;
  const calls = [];
  const controller = new AbortController();
  globalThis.fetch = async (input, init) => {
    const url = new URL(String(input));
    calls.push({ url, init });
    if (url.pathname.endsWith('/collaboration/authority')) {
      return json({
        contract_version: '2.0.0',
        tenant_id: 'tenant / operation',
        project_id: 'project / operation',
        workspace_id: 'workspace / operation',
        revision: 7,
        cursor: 'authority-cursor-7',
      });
    }
    if (url.pathname.endsWith('/retry')) {
      return json({ attention_id: 'attention / retry', status: 'retry_queued' });
    }
    if (url.pathname.endsWith('/resolve')) {
      return json({
        attention_id: 'attention / resolve',
        status: 'resolved',
        committed_revision: 8,
        replayed: false,
      });
    }
    return json([
      {
        attention_id: 'attention-1',
        root_task_id: null,
        source_kind: 'judge_block',
        source_id: 'judge-1',
        reason: 'Needs operator attention',
        status: 'open',
        created_at_ms: 17,
      },
    ]);
  };

  try {
    assert.deepEqual(await operationClient.listWorkspaceAutonomyAttentions(controller.signal), [
      {
        attention_id: 'attention-1',
        root_task_id: null,
        source_kind: 'judge_block',
        source_id: 'judge-1',
        reason: 'Needs operator attention',
        status: 'open',
        created_at_ms: 17,
      },
    ]);
    assert.equal(await operationClient.getWorkspaceAuthorityRevision(controller.signal), 7);
    assert.deepEqual(
      await operationClient.retryWorkspaceAutonomyAttention(
        'attention / retry',
        controller.signal,
      ),
      { attention_id: 'attention / retry', status: 'retry_queued' },
    );
    assert.deepEqual(
      await operationClient.resolveWorkspaceAutonomyAttention(
        'attention / resolve',
        7,
        'desktop-attention-idempotency-1',
        controller.signal,
      ),
      {
        attention_id: 'attention / resolve',
        status: 'resolved',
        committed_revision: 8,
        replayed: false,
      },
    );

    assert.equal(Object.isFrozen(provider), true);
    assert.equal(Object.isFrozen(publication), true);
    assert.equal(Object.isFrozen(publication.client), true);
    assert.equal(Object.isFrozen(operationClient), true);
    assert.equal(provider.resolve(), publication);
    assert.deepEqual(Object.keys(publication.client), attentionMethods());
    assert.deepEqual(Object.keys(operationClient), attentionMethods());
    assert.equal(calls.length, 4);
    for (const call of calls) {
      const headers = new Headers(call.init.headers);
      assert.equal(call.url.origin, 'http://127.0.0.1:43802');
      assert.equal(call.init.signal, controller.signal);
      assert.equal(headers.get('Authorization'), 'Bearer operation-session');
      assert.equal(headers.get('X-Agistack-Launch'), 'operation-launch');
    }
    assert.equal(
      calls[0].url.pathname,
      '/api/v1/workspaces/workspace%20%2F%20operation/autonomy/attentions',
    );
    assert.equal(
      calls[1].url.pathname,
      '/api/v1/tenants/tenant%20%2F%20operation/projects/project%20%2F%20operation/' +
        'workspaces/workspace%20%2F%20operation/collaboration/authority',
    );
    assert.equal(
      calls[2].url.pathname,
      '/api/v1/workspaces/workspace%20%2F%20operation/autonomy/attentions/' +
        'attention%20%2F%20retry/retry',
    );
    assert.equal(
      calls[3].url.pathname,
      '/api/v1/workspaces/workspace%20%2F%20operation/autonomy/attentions/' +
        'attention%20%2F%20resolve/resolve',
    );
    const resolveHeaders = new Headers(calls[3].init.headers);
    assert.equal(calls[2].init.method, 'POST');
    assert.equal(calls[3].init.method, 'POST');
    assert.equal(resolveHeaders.get('If-Match'), '7');
    assert.equal(resolveHeaders.get('X-Expected-Revision'), '7');
    assert.equal(
      resolveHeaders.get('Idempotency-Key'),
      'desktop-attention-idempotency-1',
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('failed workspace autonomy attention publication keeps the last-good binding', () => {
  const provider = createDesktopWorkspaceAutonomyAttentionClientProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get apiBaseUrl() {
      throw new Error('candidate_workspace_autonomy_attention_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_workspace_autonomy_attention_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

function runtimeConfig(apiBaseUrl, apiKey, localApiToken) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl,
    apiKey,
    localApiToken,
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    mode: 'local',
  };
}

function attentionMethods() {
  return [
    'listWorkspaceAutonomyAttentions',
    'getWorkspaceAuthorityRevision',
    'retryWorkspaceAutonomyAttention',
    'resolveWorkspaceAutonomyAttention',
  ];
}

function json(payload) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}
