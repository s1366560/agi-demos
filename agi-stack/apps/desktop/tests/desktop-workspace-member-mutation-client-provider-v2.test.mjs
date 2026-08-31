import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopWorkspaceMemberMutationClientProviderV2,
  DesktopWorkspaceMemberMutationClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/' +
    'desktopWorkspaceMemberMutationClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('desktop workspace-member mutation client provider fails closed before publication', () => {
  const provider = createDesktopWorkspaceMemberMutationClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(
        error instanceof DesktopWorkspaceMemberMutationClientProviderErrorV2,
        true,
      );
      assert.equal(
        error.reasonCode,
        'desktop_workspace_member_mutation_client_unpublished',
      );
      assert.equal(
        error.message,
        'desktop_workspace_member_mutation_client_unpublished',
      );
      return true;
    },
  );
});

test('publications and operation bindings pin frozen workspace-member mutation clients', async () => {
  const provider = createDesktopWorkspaceMemberMutationClientProviderV2();
  const firstConfig = runtimeConfig('http://127.0.0.1:43201', 'tenant-1', 'project-1');
  const first = provider.publish({ config: firstConfig });
  const operationConfig = runtimeConfig(
    'http://127.0.0.1:43203',
    'tenant / operation',
    'project / operation',
  );
  operationConfig.workspaceId = 'workspace / operation';
  const operationClient = first.bindOperation(operationConfig);
  firstConfig.apiBaseUrl = 'http://127.0.0.1:49999';
  operationConfig.apiBaseUrl = 'http://127.0.0.1:49998';
  const second = provider.publish({
    config: runtimeConfig('http://127.0.0.1:43202', 'tenant-2', 'project-2'),
  });
  const originalFetch = globalThis.fetch;
  const calls = [];
  let responseRole = 'viewer';
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    if (init?.method === 'DELETE') return new Response(null, { status: 204 });
    return json({
      id: 'member-record-1',
      workspace_id: 'workspace / operation',
      user_id: 'user / one',
      user_email: 'member@example.test',
      role: responseRole,
      invited_by: 'owner-1',
      created_at: '2026-09-01T00:00:00Z',
      updated_at: '2026-09-01T00:01:00Z',
    });
  };

  try {
    const added = await operationClient.addWorkspaceMemberForProject(
      'project / operation',
      'workspace / operation',
      'user / one',
      'viewer',
      'tenant / operation',
    );
    responseRole = 'editor';
    const updated = await operationClient.updateWorkspaceMemberRoleForProject(
      'project / operation',
      'workspace / operation',
      'user / one',
      'editor',
      'tenant / operation',
    );
    await operationClient.removeWorkspaceMemberForProject(
      'project / operation',
      'workspace / operation',
      'user / one',
      'tenant / operation',
    );

    assert.equal(added.role, 'viewer');
    assert.equal(updated.role, 'editor');
    assert.equal(Object.isFrozen(provider), true);
    assert.equal(Object.isFrozen(first), true);
    assert.equal(Object.isFrozen(first.client), true);
    assert.equal(Object.isFrozen(operationClient), true);
    assert.equal(Object.isFrozen(second), true);
    assert.notEqual(first, second);
    assert.notEqual(first.client, second.client);
    assert.equal(provider.resolve(), second);
    assert.deepEqual(Object.keys(first.client).sort(), ownedMethodNames());
    assert.deepEqual(Object.keys(operationClient).sort(), ownedMethodNames());
    const memberPath =
      'http://127.0.0.1:43203/api/v1/tenants/tenant%20%2F%20operation/' +
      'projects/project%20%2F%20operation/workspaces/workspace%20%2F%20operation/members';
    assert.deepEqual(
      calls.map((call) => [call.input, call.init.method]),
      [
        [memberPath, 'POST'],
        [`${memberPath}/user%20%2F%20one`, 'PATCH'],
        [`${memberPath}/user%20%2F%20one`, 'DELETE'],
      ],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('failed workspace-member mutation publication keeps the last-good binding', () => {
  const provider = createDesktopWorkspaceMemberMutationClientProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get apiBaseUrl() {
      throw new Error('candidate_workspace_member_mutation_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_workspace_member_mutation_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

function ownedMethodNames() {
  return [
    'addWorkspaceMemberForProject',
    'removeWorkspaceMemberForProject',
    'updateWorkspaceMemberRoleForProject',
  ];
}

function runtimeConfig(apiBaseUrl, tenantId, projectId) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl,
    apiKey: 'trusted-session',
    localApiToken: 'launch-capability',
    tenantId,
    projectId,
    workspaceId: 'workspace-1',
    mode: 'local',
  };
}

function json(payload) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}
