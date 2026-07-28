import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  WORKSPACE_COLLABORATION_TABS,
  beginWorkspaceSurfaceLoad,
  buildWorkspaceSurfaceMutation,
  createWorkspaceCollaborationCanvasState,
  invalidateWorkspaceSurfaceAuthority,
  resolveWorkspaceSurfaceLoad,
  selectWorkspaceCollaborationTab,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/workspaceCollaborationModel.js'
);

test('declares the complete Web-aligned ten-tab Workspace surface', () => {
  assert.deepEqual(
    WORKSPACE_COLLABORATION_TABS.map(({ id }) => id),
    [
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
    ],
  );
  assert.equal(new Set(WORKSPACE_COLLABORATION_TABS.map(({ id }) => id)).size, 10);
});

test('tracks per-surface request generations and rejects stale responses', () => {
  let state = createWorkspaceCollaborationCanvasState('workspace-1');
  state = beginWorkspaceSurfaceLoad(state, 'discussion');
  const firstGeneration = state.requestGenerations.discussion;
  state = beginWorkspaceSurfaceLoad(state, 'discussion');
  const secondGeneration = state.requestGenerations.discussion;
  assert.equal(secondGeneration, firstGeneration + 1);

  const stale = resolveWorkspaceSurfaceLoad(state, 'discussion', firstGeneration, {
    workspace_id: 'workspace-1',
    surface: 'discussion',
    authority: 'cloud',
    status: 'ready',
    revision: 1,
    cursor: 'cursor-1',
    data: { posts: [{ id: 'post-1' }] },
    reason_code: null,
  });
  assert.equal(stale, state);

  const ready = resolveWorkspaceSurfaceLoad(state, 'discussion', secondGeneration, {
    workspace_id: 'workspace-1',
    surface: 'discussion',
    authority: 'cloud',
    status: 'ready',
    revision: 2,
    cursor: 'cursor-2',
    data: { posts: [{ id: 'post-2' }] },
    reason_code: null,
  });
  assert.equal(ready.surfaces.discussion.revision, 2);
  assert.deepEqual(ready.surfaces.discussion.data, {
    posts: [{ id: 'post-2' }],
  });
});

test('fails closed on scope mismatch and never lets an older revision overwrite authority', () => {
  let state = createWorkspaceCollaborationCanvasState('workspace-1');
  state = beginWorkspaceSurfaceLoad(state, 'topology');
  const generation = state.requestGenerations.topology;
  state = resolveWorkspaceSurfaceLoad(state, 'topology', generation, {
    workspace_id: 'workspace-2',
    surface: 'topology',
    authority: 'cloud',
    status: 'ready',
    revision: 4,
    cursor: null,
    data: { nodes: [] },
    reason_code: null,
  });
  assert.equal(state.surfaces.topology.status, 'error');
  assert.equal(state.surfaces.topology.reason_code, 'workspace_surface_scope_mismatch');

  state = beginWorkspaceSurfaceLoad(state, 'topology');
  const currentGeneration = state.requestGenerations.topology;
  state = resolveWorkspaceSurfaceLoad(state, 'topology', currentGeneration, {
    workspace_id: 'workspace-1',
    surface: 'topology',
    authority: 'cloud',
    status: 'ready',
    revision: 5,
    cursor: 'cursor-5',
    data: { nodes: [{ id: 'node-5' }] },
    reason_code: null,
  });
  const authoritative = state;
  state = beginWorkspaceSurfaceLoad(state, 'topology');
  const oldGeneration = state.requestGenerations.topology;
  const rejected = resolveWorkspaceSurfaceLoad(state, 'topology', oldGeneration, {
    workspace_id: 'workspace-1',
    surface: 'topology',
    authority: 'cloud',
    status: 'ready',
    revision: 3,
    cursor: 'cursor-3',
    data: { nodes: [{ id: 'node-3' }] },
    reason_code: null,
  });
  assert.equal(rejected.surfaces.topology.revision, authoritative.surfaces.topology.revision);
  assert.deepEqual(rejected.surfaces.topology.data, authoritative.surfaces.topology.data);
});

test('reconnect, cursor gap, and mutation acknowledgement require canonical refetch', () => {
  let state = createWorkspaceCollaborationCanvasState('workspace-1');
  state = beginWorkspaceSurfaceLoad(state, 'files');
  state = resolveWorkspaceSurfaceLoad(state, 'files', state.requestGenerations.files, {
    workspace_id: 'workspace-1',
    surface: 'files',
    authority: 'cloud',
    status: 'ready',
    revision: 9,
    cursor: 'cursor-9',
    data: { files: [{ id: 'file-1' }] },
    reason_code: null,
  });

  for (const trigger of ['reconnect', 'cursor_gap', 'mutation_ack']) {
    const invalidated = invalidateWorkspaceSurfaceAuthority(state, 'files', trigger);
    assert.equal(invalidated.surfaces.files.status, 'stale');
    assert.equal(
      invalidated.surfaces.files.reason_code,
      `workspace_surface_${trigger}_refetch_required`,
    );
    assert.deepEqual(invalidated.surfaces.files.data, {
      files: [{ id: 'file-1' }],
    });
  }
});

test('surface mutation requires current revision and a bounded idempotency key', () => {
  let state = createWorkspaceCollaborationCanvasState('workspace-1');
  assert.deepEqual(
    buildWorkspaceSurfaceMutation(state, 'discussion', 'create_post', 'idem-123', {
      body: 'Ship it',
    }),
    { ok: false, reasonCode: 'workspace_surface_revision_required' },
  );

  state = beginWorkspaceSurfaceLoad(state, 'discussion');
  state = resolveWorkspaceSurfaceLoad(
    state,
    'discussion',
    state.requestGenerations.discussion,
    {
      workspace_id: 'workspace-1',
      surface: 'discussion',
      authority: 'cloud',
      status: 'ready',
      revision: 12,
      cursor: null,
      data: { posts: [] },
      reason_code: null,
    },
  );
  assert.deepEqual(
    buildWorkspaceSurfaceMutation(state, 'discussion', 'create_post', 'idem-123', {
      body: 'Ship it',
    }),
    {
      ok: true,
      mutation: {
        action: 'create_post',
        expected_revision: 12,
        idempotency_key: 'idem-123',
        payload: { body: 'Ship it' },
      },
    },
  );
});

test('tab selection is structural and ignores unknown identifiers', () => {
  const state = createWorkspaceCollaborationCanvasState('workspace-1');
  assert.equal(selectWorkspaceCollaborationTab(state, 'discussion').activeSurface, 'discussion');
  assert.equal(selectWorkspaceCollaborationTab(state, 'unknown').activeSurface, 'goals');
});
