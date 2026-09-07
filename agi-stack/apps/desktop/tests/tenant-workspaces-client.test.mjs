import assert from 'node:assert/strict';
import { test } from 'node:test';

const { createTenantWorkspacesV2Client } = await import(
  '/tmp/agistack-desktop-test-dist/src/features/tenant/tenantWorkspacesV2Client.js'
);

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

test('Cloud Tenant Workspaces binds list and create to V2 project authorities', async () => {
  const received = [];
  const controller = new AbortController();
  const config = runtimeConfig();
  const client = createTenantWorkspacesV2Client(config, operationsFixture(received));
  const catalogPending = client.list(scope(), { signal: controller.signal });
  const createdPending = client.create(
    scope(),
    { name: '  Created  ', description: '  Native workspace  ' },
    { signal: controller.signal },
  );
  config.projectId = 'mutated-project';

  const [catalog, created] = await Promise.all([catalogPending, createdPending]);
  assert.equal(catalog.availability, 'degraded');
  assert.equal(catalog.reasonCode, 'desktop_tenant_workspaces_advanced_management_partial');
  assert.deepEqual(catalog.allowedActions, ['view', 'list', 'create']);
  assert.equal(catalog.workspaces[0].projectId, 'project-1');
  assert.equal(created.id, 'workspace-created');
  assert.equal(received.length, 2);
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

test('Local Tenant Workspaces retains the stable degraded lifecycle contract', async () => {
  const client = createTenantWorkspacesV2Client(
    runtimeConfig({
      mode: 'local',
      apiBaseUrl: 'http://127.0.0.1:4777',
    }),
    operationsFixture([]),
  );

  const catalog = await client.list({ ...scope(), authority: 'local' });

  assert.equal(catalog.authority, 'local');
  assert.equal(catalog.availability, 'degraded');
  assert.equal(catalog.reasonCode, 'local_workspace_lifecycle_partial');
  assert.deepEqual(catalog.allowedActions, ['view', 'list', 'create']);
});

test('Tenant Workspaces fails closed before V2 authority calls when runtime scope drifts', async () => {
  const received = [];
  const client = createTenantWorkspacesV2Client(runtimeConfig(), operationsFixture(received));

  await assert.rejects(
    client.list({ ...scope(), projectId: 'other-project' }),
    /tenant_workspaces_runtime_scope_mismatch/u,
  );
  assert.equal(received.length, 0);
});

test('Tenant Workspaces rejects V2 records outside the selected scope', async () => {
  const client = createTenantWorkspacesV2Client(
    runtimeConfig(),
    operationsFixture([], { workspaces: [workspace({ project_id: 'other-project' })] }),
  );

  await assert.rejects(
    client.list(scope()),
    /cloud_tenant_workspaces_contract_invalid/u,
  );
});

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
