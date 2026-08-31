import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopWorkspaceLifecycleClientProviderV2,
  DesktopWorkspaceLifecycleClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/' +
    'desktopWorkspaceLifecycleClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('desktop workspace lifecycle client provider fails closed before publication', () => {
  const provider = createDesktopWorkspaceLifecycleClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(
        error instanceof DesktopWorkspaceLifecycleClientProviderErrorV2,
        true,
      );
      assert.equal(
        error.reasonCode,
        'desktop_workspace_lifecycle_client_unpublished',
      );
      assert.equal(
        error.message,
        'desktop_workspace_lifecycle_client_unpublished',
      );
      return true;
    },
  );
});

test('publications and operation bindings pin frozen workspace lifecycle clients', async () => {
  const provider = createDesktopWorkspaceLifecycleClientProviderV2();
  const firstConfig = runtimeConfig('http://127.0.0.1:43301', 'tenant-1', 'project-1');
  const first = provider.publish({ config: firstConfig });
  const operationConfig = runtimeConfig(
    'http://127.0.0.1:43303',
    'tenant / operation',
    'project / operation',
  );
  operationConfig.workspaceId = 'workspace / operation';
  const operationClient = first.bindOperation(operationConfig);
  firstConfig.apiBaseUrl = 'http://127.0.0.1:49999';
  operationConfig.apiBaseUrl = 'http://127.0.0.1:49998';
  const second = provider.publish({
    config: runtimeConfig('http://127.0.0.1:43302', 'tenant-2', 'project-2'),
  });
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    const updating = init?.method === 'PATCH';
    return json(
      workspaceRecord({
        id: updating ? 'workspace / operation' : 'workspace-created',
        tenantId: 'tenant / operation',
        projectId: 'project / operation',
        name: updating ? 'Updated workspace' : 'Created workspace',
        archived: updating,
      }),
      updating ? 200 : 201,
    );
  };

  try {
    const created = await operationClient.createWorkspaceForProject(
      'project / operation',
      {
        name: 'Created workspace',
        description: 'Created through V2',
        useCase: 'conversation',
        collaborationMode: 'multi_agent_shared',
        metadata: { source: 'desktop' },
      },
      'tenant / operation',
    );
    const updated = await operationClient.updateWorkspaceForProject(
      'project / operation',
      'workspace / operation',
      {
        name: 'Updated workspace',
        description: 'Updated through V2',
        isArchived: true,
        metadata: { source: 'desktop-v2' },
      },
      'tenant / operation',
    );

    assert.equal(created.id, 'workspace-created');
    assert.equal(updated.id, 'workspace / operation');
    assert.equal(updated.is_archived, true);
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
    const collectionPath =
      'http://127.0.0.1:43303/api/v1/tenants/tenant%20%2F%20operation/' +
      'projects/project%20%2F%20operation/workspaces';
    assert.deepEqual(
      calls.map((call) => [call.input, call.init.method]),
      [
        [collectionPath, 'POST'],
        [`${collectionPath}/workspace%20%2F%20operation`, 'PATCH'],
      ],
    );
    assert.deepEqual(JSON.parse(calls[0].init.body), {
      name: 'Created workspace',
      description: 'Created through V2',
      metadata: { source: 'desktop' },
      use_case: 'conversation',
      collaboration_mode: 'multi_agent_shared',
    });
    assert.deepEqual(JSON.parse(calls[1].init.body), {
      name: 'Updated workspace',
      description: 'Updated through V2',
      is_archived: true,
      metadata: { source: 'desktop-v2' },
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('failed workspace lifecycle publication keeps the last-good binding', () => {
  const provider = createDesktopWorkspaceLifecycleClientProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get apiBaseUrl() {
      throw new Error('candidate_workspace_lifecycle_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_workspace_lifecycle_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

function ownedMethodNames() {
  return ['createWorkspaceForProject', 'updateWorkspaceForProject'];
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

function workspaceRecord({ id, tenantId, projectId, name, archived }) {
  return {
    id,
    tenant_id: tenantId,
    project_id: projectId,
    name,
    created_by: 'user-1',
    description: null,
    is_archived: archived,
    metadata: {},
    office_status: 'idle',
    hex_layout_config: {},
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:01:00Z',
  };
}

function json(payload, status) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
