import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  WorkspaceCollaborationContractError,
  createHttpWorkspaceCollaborationClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/workspace/httpWorkspaceCollaborationClient.js');
const {
  buildWorkspaceAuthorityMutationRequest,
} = require('/tmp/agistack-desktop-test-dist/src/features/workspace/workspaceCollaborationHttpMutations.js');
const {
  normalizeWorkspaceCollaborationCapabilityContract,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/workbenchCapabilityClient.js');
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

const scope = {
  tenantId: 'tenant / one',
  projectId: 'project / one',
  workspaceId: 'workspace / one',
};

const mutationActions = {
  goals: [
    'create_objective',
    'update_objective',
    'delete_objective',
    'project_objective_to_task',
    'create_task',
    'update_task',
    'delete_task',
    'assign_task_agent',
    'unassign_task_agent',
  ],
  discussion: [
    'create_post',
    'update_post',
    'delete_post',
    'pin_post',
    'unpin_post',
    'create_reply',
    'update_reply',
    'delete_reply',
  ],
  status: ['update_task', 'apply_task_recovery_action'],
  collaboration: [
    'bind_agent',
    'update_agent_binding',
    'unbind_agent',
    'add_member',
    'update_member_role',
    'remove_member',
    'create_task',
    'update_task',
    'delete_task',
    'assign_task_agent',
    'unassign_task_agent',
  ],
  members: ['add_member', 'update_member_role', 'remove_member'],
  genes: ['create_gene', 'update_gene', 'delete_gene'],
  files: ['create_directory', 'upload_file', 'update_file', 'delete_file', 'copy_file'],
  notes: [],
  topology: [
    'create_node',
    'update_node',
    'delete_node',
    'create_edge',
    'update_edge',
    'delete_edge',
  ],
  settings: ['update_workspace'],
};

test('available Workspace capability requires exact revision and idempotency action authority', () => {
  const normalized = normalizeWorkspaceCollaborationCapabilityContract(
    {
      service_version: '0.2.0',
      contract_version: '2.0.0',
      authority: 'cloud',
      tenant_id: scope.tenantId,
      project_id: scope.projectId,
      workspace_id: scope.workspaceId,
      status: 'available',
      reason_code: null,
      canonical_read: true,
      read_surfaces: Object.keys(mutationActions),
      mutations: {
        allowed: true,
        revision_guarded: true,
        idempotency_guarded: true,
        actions: mutationActions,
      },
      allowed_actions: mutationActions,
    },
    scope
  );

  assert.deepEqual(normalized, {
    status: 'available',
    reason_code: null,
    service_version: '0.2.0',
    contract_version: '2.0.0',
    minimum_contract_version: '2.0.0',
  });
});

test('Workspace capability rejects top-level actions that diverge from mutation guards', () => {
  const divergentActions = {
    ...mutationActions,
    notes: ['delete_workspace'],
  };
  const normalized = normalizeWorkspaceCollaborationCapabilityContract(
    {
      service_version: '0.2.0',
      contract_version: '2.0.0',
      authority: 'cloud',
      tenant_id: scope.tenantId,
      project_id: scope.projectId,
      workspace_id: scope.workspaceId,
      status: 'available',
      reason_code: null,
      canonical_read: true,
      read_surfaces: Object.keys(mutationActions),
      mutations: {
        allowed: true,
        revision_guarded: true,
        idempotency_guarded: true,
        actions: mutationActions,
      },
      allowed_actions: divergentActions,
    },
    scope
  );

  assert.equal(normalized.status, 'unavailable');
  assert.equal(
    normalized.reason_code,
    'workspace_collaboration_capability_contract_invalid'
  );
});

test('authority command uses one scoped endpoint and strips spoofed scope fields', () => {
  const request = buildWorkspaceAuthorityMutationRequest(scope, 'discussion', {
    action: 'create_post',
    expected_revision: 7,
    idempotency_key: 'workspace-command-0001',
    payload: {
      tenant_id: 'spoofed',
      project_id: 'spoofed',
      workspace_id: 'spoofed',
      title: 'Decision',
      content: 'Ship it',
    },
  });

  assert.equal(request.method, 'POST');
  assert.equal(
    request.path,
    '/api/v1/tenants/tenant%20%2F%20one/projects/project%20%2F%20one/' +
      'workspaces/workspace%20%2F%20one/collaboration/mutations'
  );
  assert.deepEqual(request.body, {
    contract_version: '2.0.0',
    surface: 'discussion',
    action: 'create_post',
    expected_revision: 7,
    idempotency_key: 'workspace-command-0001',
    payload: { title: 'Decision', content: 'Ship it' },
  });
});

test('mutation rejects a canonical refetch older than the durable receipt', async () => {
  const originalFetch = globalThis.fetch;
  const base =
    'https://api.memstack.test/api/v1/tenants/tenant%20%2F%20one/projects/' +
    'project%20%2F%20one/workspaces/workspace%20%2F%20one';
  globalThis.fetch = async (input, init) => {
    const url = String(input);
    if (init.method === 'POST') {
      return new Response(
        JSON.stringify({
          contract_version: '2.0.0',
          receipt_id: 'receipt-1',
          workspace_id: scope.workspaceId,
          surface: 'discussion',
          action: 'create_post',
          revision: 9,
          duplicate: false,
        }),
        { status: 200, headers: { 'content-type': 'application/json' } }
      );
    }
    if (url === `${base}/blackboard/posts`) {
      return new Response(JSON.stringify({ items: [] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    if (url === `${base}/collaboration/authority`) {
      return new Response(
        JSON.stringify({
          contract_version: '2.0.0',
          tenant_id: scope.tenantId,
          project_id: scope.projectId,
          workspace_id: scope.workspaceId,
          revision: 8,
          cursor: 'workspace:workspace / one:revision:8',
        }),
        { status: 200, headers: { 'content-type': 'application/json' } }
      );
    }
    throw new Error(`unexpected request: ${url}`);
  };

  try {
    const client = createHttpWorkspaceCollaborationClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'https://api.memstack.test',
      apiKey: 'workspace-session',
      tenantId: scope.tenantId,
      projectId: scope.projectId,
      workspaceId: scope.workspaceId,
      mode: 'cloud',
    });
    await assert.rejects(
      client.mutateSurface(scope.workspaceId, 'discussion', {
        action: 'create_post',
        expected_revision: 7,
        idempotency_key: 'workspace-command-0001',
        payload: { title: 'Decision', content: 'Ship it' },
      }),
      (error) =>
        error instanceof WorkspaceCollaborationContractError &&
        error.reason_code === 'workspace_surface_stale_refetch'
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
