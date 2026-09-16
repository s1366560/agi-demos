import assert from 'node:assert/strict';
import { test } from 'node:test';

const { createProjectWorkspacesV2Client } = await import(
  '/tmp/agistack-desktop-test-dist/src/features/project-workspaces/projectWorkspacesV2Client.js'
);

test('Project Workspaces maps list and create through project-scoped V2 operations', async () => {
  const received = [];
  const controller = new AbortController();
  const config = runtimeConfig({ workspaceId: 'stale-workspace' });
  const client = createProjectWorkspacesV2Client(config, operationsFixture(received));

  const listedPending = client.list(scope(), { signal: controller.signal });
  const createdPending = client.create(
    scope(),
    { name: '  Created  ', description: '  Native workspace  ' },
    { signal: controller.signal },
  );
  config.projectId = 'mutated-project';

  const [listed, created] = await Promise.all([listedPending, createdPending]);
  assert.equal(listed.availability, 'available');
  assert.equal(listed.reasonCode, null);
  assert.equal(listed.serviceVersion, '1.0.0');
  assert.equal(listed.contractVersion, '1.0.0');
  assert.equal(listed.authorityRevision, null);
  assert.deepEqual(listed.allowedActions, ['view', 'list', 'create', 'open-blackboard']);
  assert.equal(listed.workspaces[0].projectId, 'project-1');
  assert.equal(created.id, 'workspace-created');
  assert.equal(Object.isFrozen(listed), true);
  assert.equal(Object.isFrozen(listed.workspaces), true);

  assert.deepEqual(received[0], {
    kind: 'list',
    input: {
      config: runtimeConfig(),
      signal: controller.signal,
    },
  });
  assert.equal(Object.isFrozen(received[0].input.config), true);
  assert.deepEqual(received[1], {
    kind: 'create',
    input: {
      config: runtimeConfig(),
      input: {
        name: 'Created',
        description: 'Native workspace',
        useCase: 'conversation',
        collaborationMode: 'multi_agent_shared',
        metadata: {
          source: 'desktop',
          workspace_use_case: 'conversation',
          workspace_type: 'general',
          collaboration_mode: 'multi_agent_shared',
          agent_conversation_mode: 'multi_agent_shared',
          autonomy_profile: { workspace_type: 'general' },
        },
      },
      signal: controller.signal,
    },
  });
  assert.equal(Object.isFrozen(received[1].input.input), true);
  assert.equal(Object.isFrozen(received[1].input.input.metadata), true);
});

test('Project Workspaces preserves the declared Local partial lifecycle contract', async () => {
  const client = createProjectWorkspacesV2Client(
    runtimeConfig({
      mode: 'local',
      apiBaseUrl: 'http://127.0.0.1:4777',
    }),
    operationsFixture([]),
  );

  const listed = await client.list({ ...scope(), authority: 'local' });

  assert.equal(listed.authority, 'local');
  assert.equal(listed.availability, 'degraded');
  assert.equal(listed.reasonCode, 'local_workspace_lifecycle_partial');
  assert.deepEqual(listed.allowedActions, ['view', 'list', 'create', 'open-blackboard']);
});

test('Project Workspaces rejects scope drift before acquiring a V2 operation lease', async () => {
  const received = [];
  const client = createProjectWorkspacesV2Client(runtimeConfig(), operationsFixture(received));

  await assert.rejects(
    client.list({ ...scope(), projectId: 'other-project' }),
    /project_workspaces_runtime_scope_mismatch/u,
  );
  assert.equal(received.length, 0);
});

test('Project Workspaces rejects V2 records outside the selected project scope', async () => {
  const client = createProjectWorkspacesV2Client(
    runtimeConfig(),
    operationsFixture([], {
      workspaces: [workspace({ project_id: 'other-project' })],
    }),
  );

  await assert.rejects(client.list(scope()), /cloud_project_workspaces_contract_invalid/u);
});

test('Project Workspaces rejects malformed V2 catalog collections', async () => {
  const client = createProjectWorkspacesV2Client(
    runtimeConfig(),
    operationsFixture([], { workspaces: {} }),
  );

  await assert.rejects(
    client.list(scope()),
    /cloud_project_workspaces_contract_invalid/u,
  );
});

test('Project Workspaces requires both declared V2 operation dependencies', () => {
  assert.throws(
    () =>
      createProjectWorkspacesV2Client(runtimeConfig(), {
        catalogOperations: {},
        lifecycleOperations: { async createWorkspace() {} },
      }),
    /desktop_workspace_catalog_authority_required/u,
  );
  assert.throws(
    () =>
      createProjectWorkspacesV2Client(runtimeConfig(), {
        catalogOperations: { async listWorkspacesForProject() {} },
        lifecycleOperations: {},
      }),
    /desktop_workspace_lifecycle_authority_required/u,
  );
});

function operationsFixture(received, overrides = {}) {
  return {
    catalogOperations: {
      async listWorkspacesForProject(input) {
        received.push({ kind: 'list', input });
        return overrides.workspaces ?? [workspace()];
      },
    },
    lifecycleOperations: {
      async createWorkspace(input) {
        received.push({ kind: 'create', input });
        return overrides.created ?? workspace({ id: 'workspace-created', name: input.input.name });
      },
    },
  };
}

function runtimeConfig(overrides = {}) {
  return {
    mode: 'cloud',
    apiBaseUrl: 'https://memstack.test',
    deviceAuthorizationBaseUrl: 'https://memstack.test',
    apiKey: 'test-token',
    localApiToken: 'test-local-token',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: '',
    workspaceRoot: '/workspace',
    ...overrides,
  };
}

function scope() {
  return {
    authority: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
  };
}

function workspace(overrides = {}) {
  return {
    id: 'workspace-1',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    name: 'Alpha workspace',
    description: 'Workspace description',
    status: 'active',
    is_archived: false,
    created_at: '2026-07-31T00:00:00Z',
    updated_at: null,
    metadata: {},
    ...overrides,
  };
}
