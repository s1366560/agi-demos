import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  WORKSPACE_HTTP_MUTATION_ACTIONS,
  WorkspaceCollaborationContractError,
  createHttpWorkspaceCollaborationClient,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/httpWorkspaceCollaborationClient.js',
);
const { buildWorkspaceMutationRequest } = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/workspaceCollaborationHttpMutations.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

const tenantId = 'tenant / one';
const projectId = 'project / one';
const workspaceId = 'workspace / one';
const encodedBase =
  'https://api.memstack.test/api/v1/tenants/tenant%20%2F%20one/projects/' +
  'project%20%2F%20one/workspaces/workspace%20%2F%20one';
const encodedRoot =
  'https://api.memstack.test/api/v1/workspaces/workspace%20%2F%20one';

function config(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'https://api.memstack.test',
    apiKey: 'workspace-session',
    tenantId,
    projectId,
    workspaceId,
    mode: 'cloud',
    ...overrides,
  };
}

function json(payload, headers = {}) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json', ...headers },
  });
}

function scoped(id, extra = {}) {
  return { id, workspace_id: workspaceId, ...extra };
}

function canonicalResponse(input) {
  const url = String(input);
  if (url === encodedBase) {
    return json({
      id: workspaceId,
      tenant_id: tenantId,
      project_id: projectId,
      name: 'Parity workspace',
      description: 'Canonical workspace notes',
      revision: 7,
      cursor: 'cursor-7',
    });
  }
  if (url === `${encodedBase}/objectives`) {
    return json({
      items: [scoped('objective-1', { title: 'Ship parity' })],
      revision: 7,
      cursor: 'cursor-7',
    });
  }
  if (url === `${encodedRoot}/tasks`) {
    return json([scoped('task-1', { title: 'Implement authority' })]);
  }
  if (url === `${encodedBase}/blackboard/posts`) {
    return json({
      items: [
        scoped('post-1', { title: 'General', is_pinned: false }),
        scoped('post-2', { title: 'Pinned', is_pinned: true }),
      ],
      revision: 7,
      cursor: 'cursor-7',
    });
  }
  if (url === `${encodedBase}/blackboard/execution-diagnostics`) {
    return json({
      workspace_id: workspaceId,
      generated_at: '2026-07-28T00:00:00Z',
      task_status_counts: {},
      attempt_status_counts: {},
      tool_status_counts: {},
      tasks: [],
      blockers: [],
      pending_adjudications: [],
      evidence_gaps: [],
      recent_tool_failures: [],
      revision: 7,
      cursor: 'cursor-7',
    });
  }
  if (url === `${encodedBase}/agents`) {
    return json([scoped('binding-1', { agent_id: 'agent-1' })]);
  }
  if (url === `${encodedBase}/members`) {
    return json([scoped('member-1', { user_id: 'user-1' })]);
  }
  if (url === `${encodedBase}/genes`) {
    return json({
      items: [scoped('gene-1', { name: 'Research' })],
      revision: 7,
      cursor: 'cursor-7',
    });
  }
  if (url === `${encodedBase}/blackboard/files?parent_path=%2F`) {
    return json({
      items: [scoped('file-1', { name: 'README.md' })],
      revision: 7,
      cursor: 'cursor-7',
    });
  }
  if (url === `${encodedRoot}/topology/nodes`) {
    return json([scoped('node-1', { title: 'Goal' })]);
  }
  if (url === `${encodedRoot}/topology/edges`) {
    return json({
      items: [scoped('edge-1', { source_node_id: 'node-1', target_node_id: 'node-2' })],
      revision: 7,
      cursor: 'cursor-7',
    });
  }
  throw new Error(`unexpected canonical request: ${url}`);
}

test('loads every Web-aligned Workspace surface from canonical REST authorities', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ url: String(input), init });
    return canonicalResponse(input);
  };

  try {
    const client = createHttpWorkspaceCollaborationClient(config());
    const surfaces = [
      'goals',
      'discussion',
      'status',
      'collaboration',
      'members',
      'genes',
      'files',
      'notes',
      'topology',
      'settings',
    ];
    const states = {};
    for (const surface of surfaces) {
      states[surface] = await client.getSurface(workspaceId, surface);
      assert.equal(states[surface].workspace_id, workspaceId);
      assert.equal(states[surface].surface, surface);
      assert.equal(states[surface].authority, 'cloud');
      assert.equal(states[surface].status, 'ready');
      const hasExplicitAuthority = surface !== 'collaboration' && surface !== 'members';
      assert.equal(states[surface].revision, hasExplicitAuthority ? 7 : null);
      assert.equal(states[surface].cursor, hasExplicitAuthority ? 'cursor-7' : null);
    }

    assert.deepEqual(Object.keys(states.goals.data), ['objectives', 'tasks']);
    assert.deepEqual(Object.keys(states.discussion.data), ['posts']);
    assert.deepEqual(Object.keys(states.status.data), ['diagnostics', 'tasks']);
    assert.deepEqual(Object.keys(states.collaboration.data), ['agents', 'members', 'tasks']);
    assert.deepEqual(Object.keys(states.members.data), ['members']);
    assert.deepEqual(Object.keys(states.genes.data), ['genes']);
    assert.deepEqual(Object.keys(states.files.data), ['files']);
    assert.deepEqual(
      states.notes.data.pinned_posts.map(({ id }) => id),
      ['post-2'],
    );
    assert.deepEqual(Object.keys(states.topology.data), ['nodes', 'edges']);
    assert.deepEqual(Object.keys(states.settings.data), ['workspace']);

    assert.deepEqual(
      calls.map(({ url }) => url),
      [
        `${encodedBase}/objectives`,
        `${encodedRoot}/tasks`,
        `${encodedBase}/blackboard/posts`,
        `${encodedBase}/blackboard/execution-diagnostics`,
        `${encodedRoot}/tasks`,
        `${encodedBase}/agents`,
        `${encodedBase}/members`,
        `${encodedRoot}/tasks`,
        `${encodedBase}/members`,
        `${encodedBase}/genes`,
        `${encodedBase}/blackboard/files?parent_path=%2F`,
        encodedBase,
        `${encodedBase}/objectives`,
        `${encodedBase}/blackboard/posts`,
        `${encodedRoot}/topology/nodes`,
        `${encodedRoot}/topology/edges`,
        encodedBase,
      ],
    );
    for (const { init } of calls) {
      assert.equal(init.method, 'GET');
      assert.equal(init.headers.get('Authorization'), 'Bearer workspace-session');
      assert.equal(init.headers.has('X-Agistack-Launch'), false);
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('uses only explicit authority metadata and preserves structural emptiness', async () => {
  const originalFetch = globalThis.fetch;
  let empty = false;
  globalThis.fetch = async () =>
    json(
      empty
        ? []
        : [
            scoped('member-1', {
              user_id: 'user-1',
              updated_at: '2099-01-01T00:00:00Z',
            }),
          ],
      { ETag: '"members-v3"' },
    );

  try {
    const client = createHttpWorkspaceCollaborationClient(config());
    const ready = await client.getSurface(workspaceId, 'members');
    assert.equal(ready.status, 'ready');
    assert.equal(ready.revision, null);
    assert.equal(ready.cursor, '"members-v3"');

    empty = true;
    const emptyState = await client.refetchAuthority(workspaceId, 'members');
    assert.equal(emptyState.status, 'empty');
    assert.equal(emptyState.revision, null);
    assert.equal(emptyState.cursor, '"members-v3"');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('fails closed before or after fetch when Workspace scope drifts', async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  let responseMode = 'row';
  globalThis.fetch = async () => {
    calls += 1;
    return responseMode === 'row'
      ? json([scoped('member-1', { workspace_id: 'workspace-other' })])
      : json({ items: [], workspace_id: 'workspace-other' });
  };

  try {
    const client = createHttpWorkspaceCollaborationClient(config());
    await assert.rejects(
      client.getSurface('workspace-other', 'members'),
      (error) =>
        error instanceof WorkspaceCollaborationContractError &&
        error.reason_code === 'workspace_surface_scope_mismatch',
    );
    assert.equal(calls, 0);

    await assert.rejects(
      client.getSurface(workspaceId, 'members'),
      (error) =>
        error instanceof WorkspaceCollaborationContractError &&
        error.reason_code === 'workspace_surface_scope_mismatch',
    );
    assert.equal(calls, 1);

    responseMode = 'envelope';
    await assert.rejects(
      client.getSurface(workspaceId, 'members'),
      (error) =>
        error instanceof WorkspaceCollaborationContractError &&
        error.reason_code === 'workspace_surface_scope_mismatch',
    );
    assert.equal(calls, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('does not reinterpret HTTP errors or conflicting metadata as capability state', async () => {
  const originalFetch = globalThis.fetch;
  let mode = 'http-error';
  globalThis.fetch = async (input) => {
    if (mode === 'http-error') {
      return new Response(JSON.stringify({ detail: 'not found' }), {
        status: 404,
        headers: { 'content-type': 'application/json' },
      });
    }
    const url = String(input);
    if (url === encodedBase) {
      return json({
        id: workspaceId,
        tenant_id: tenantId,
        project_id: projectId,
        revision: 3,
        cursor: 'cursor-3',
      });
    }
    if (url === `${encodedBase}/objectives`) {
      return json({ items: [], revision: 4, cursor: 'cursor-3' });
    }
    if (url === `${encodedBase}/blackboard/posts`) {
      return json({ items: [], revision: 3, cursor: 'cursor-3' });
    }
    throw new Error(`unexpected request: ${url}`);
  };

  try {
    const client = createHttpWorkspaceCollaborationClient(config());
    await assert.rejects(
      client.getSurface(workspaceId, 'members'),
      (error) =>
        error instanceof WorkspaceCollaborationContractError &&
        error.reason_code === 'workspace_surface_request_failed' &&
        error.status === 404,
    );

    mode = 'revision-conflict';
    await assert.rejects(
      client.getSurface(workspaceId, 'notes'),
      (error) =>
        error instanceof WorkspaceCollaborationContractError &&
        error.reason_code === 'workspace_surface_revision_conflict',
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('mutations carry authority headers then canonically refetch', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ url: String(input), init });
    if (init.method === 'POST') {
      return json(scoped('post-created', { title: 'Decision', is_pinned: false }));
    }
    return canonicalResponse(input);
  };

  try {
    const client = createHttpWorkspaceCollaborationClient(
      config({
        mode: 'local',
        localApiToken: 'sidecar-launch-capability',
      }),
    );
    const state = await client.mutateSurface(workspaceId, 'discussion', {
      action: 'create_post',
      expected_revision: 8,
      idempotency_key: 'workspace-mutation-0001',
      payload: { title: 'Decision', content: 'Ship it' },
    });

    assert.equal(state.status, 'ready');
    assert.equal(calls.length, 2);
    assert.equal(calls[0].url, `${encodedBase}/blackboard/posts`);
    assert.equal(calls[0].init.method, 'POST');
    assert.equal(calls[0].init.headers.get('X-Expected-Revision'), '8');
    assert.equal(calls[0].init.headers.get('Idempotency-Key'), 'workspace-mutation-0001');
    assert.equal(
      calls[0].init.headers.get('X-Agistack-Launch'),
      'sidecar-launch-capability',
    );
    assert.deepEqual(JSON.parse(calls[0].init.body), {
      title: 'Decision',
      content: 'Ship it',
    });
    assert.equal(calls[1].init.method, 'GET');

    const beforeUnsupported = calls.length;
    const unsupported = await client.mutateSurface(workspaceId, 'notes', {
      action: 'create_note',
      expected_revision: -1,
      idempotency_key: 'invalid',
      payload: { content: 'Do not invent a Notes store' },
    });
    assert.deepEqual(unsupported, {
      workspace_id: workspaceId,
      surface: 'notes',
      authority: 'local',
      status: 'unavailable',
      revision: null,
      cursor: null,
      data: null,
      reason_code: 'workspace_surface_action_unavailable',
    });
    assert.equal(calls.length, beforeUnsupported);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('declares a static mutation allow-list for canonical mutable surfaces', () => {
  assert.deepEqual(WORKSPACE_HTTP_MUTATION_ACTIONS, {
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
  });
});

test('every allowlisted action maps to an existing canonical REST route', () => {
  const scope = { tenantId, projectId, workspaceId };
  const payload = {
    tenant_id: 'spoofed-tenant',
    project_id: 'spoofed-project',
    workspace_id: 'spoofed-workspace',
    objective_id: 'objective / one',
    task_id: 'task / one',
    post_id: 'post / one',
    reply_id: 'reply / one',
    workspace_agent_id: 'binding / one',
    user_id: 'user / one',
    gene_id: 'gene / one',
    file_id: 'file / one',
    node_id: 'node / one',
    edge_id: 'edge / one',
    parent_path: '/',
    recursive: true,
    file: new Blob(['payload'], { type: 'text/plain' }),
    filename: 'payload.txt',
    title: 'Update',
    content: 'Canonical mutation',
  };
  const descriptors = new Map();

  for (const [surface, actions] of Object.entries(WORKSPACE_HTTP_MUTATION_ACTIONS)) {
    for (const action of actions) {
      const descriptor = buildWorkspaceMutationRequest(scope, surface, {
        action,
        expected_revision: 11,
        idempotency_key: 'workspace-route-map-0001',
        payload,
      });
      descriptors.set(`${surface}:${action}`, descriptor);
      assert.equal(['POST', 'PATCH', 'DELETE'].includes(descriptor.method), true);
      assert.equal(descriptor.path.startsWith('/api/v1/'), true);
      if (action === 'upload_file') {
        assert.equal(descriptor.body instanceof FormData, true);
      } else if (descriptor.body) {
        assert.equal(Object.hasOwn(descriptor.body, 'expected_revision'), false);
        assert.equal(Object.hasOwn(descriptor.body, 'idempotency_key'), false);
        assert.equal(Object.hasOwn(descriptor.body, 'tenant_id'), false);
        assert.equal(Object.hasOwn(descriptor.body, 'project_id'), false);
        assert.equal(Object.hasOwn(descriptor.body, 'workspace_id'), false);
      }
    }
  }

  assert.equal(
    descriptors.get('goals:update_objective').path,
    '/api/v1/tenants/tenant%20%2F%20one/projects/project%20%2F%20one/' +
      'workspaces/workspace%20%2F%20one/objectives/objective%20%2F%20one',
  );
  assert.equal(
    descriptors.get('status:apply_task_recovery_action').path,
    '/api/v1/workspaces/workspace%20%2F%20one/tasks/task%20%2F%20one/recovery-actions',
  );
  assert.equal(
    descriptors.get('discussion:update_reply').path,
    '/api/v1/tenants/tenant%20%2F%20one/projects/project%20%2F%20one/' +
      'workspaces/workspace%20%2F%20one/blackboard/posts/post%20%2F%20one/' +
      'replies/reply%20%2F%20one',
  );
  assert.equal(
    descriptors.get('members:remove_member').path.endsWith(
      '/members/user%20%2F%20one',
    ),
    true,
  );
  assert.equal(
    descriptors.get('files:delete_file').path.endsWith(
      '/blackboard/files/file%20%2F%20one?recursive=true',
    ),
    true,
  );
  assert.equal(
    descriptors.get('topology:update_edge').path,
    '/api/v1/workspaces/workspace%20%2F%20one/topology/edges/edge%20%2F%20one',
  );
  assert.equal(
    descriptors.get('settings:update_workspace').path,
    '/api/v1/tenants/tenant%20%2F%20one/projects/project%20%2F%20one/' +
      'workspaces/workspace%20%2F%20one',
  );
  assert.equal(descriptors.size, 48);
});
