import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  beginWorkspaceSurfaceLoad,
  createWorkspaceCollaborationCanvasState,
  failWorkspaceSurfaceLoad,
  invalidateWorkspaceSurfaceAuthority,
  resolveWorkspaceSurfaceLoad,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/workspaceCollaborationModel.js',
);
const canvasSource = readFileSync(
  new URL('../src/features/workspace/WorkspaceCollaborationCanvas.tsx', import.meta.url),
  'utf8',
);
const primitiveSource = readFileSync(
  new URL(
    '../src/features/workspace/WorkspaceCollaborationSurfacePrimitives.tsx',
    import.meta.url,
  ),
  'utf8',
);
const componentSource = `${canvasSource}\n${primitiveSource}`;
const cssSource = readFileSync(
  new URL('../src/features/workspace/WorkspaceCollaborationCanvas.css', import.meta.url),
  'utf8',
);

test('Workspace Collaboration Canvas exposes all ten authority-backed tabs', () => {
  for (const surface of [
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
  ]) {
    assert.match(componentSource, new RegExp(`case '${surface}'|surface === '${surface}'`, 'u'));
  }
  assert.match(componentSource, /WORKSPACE_COLLABORATION_TABS\.map/u);
  assert.match(componentSource, /role="tablist"/u);
  assert.match(componentSource, /role="tab"/u);
  assert.match(componentSource, /role="tabpanel"/u);
  assert.match(componentSource, /ArrowLeft/u);
  assert.match(componentSource, /ArrowRight/u);
});

test('active-tab loading aborts replaced work and mutations always canonical-refetch', () => {
  assert.match(componentSource, /new AbortController\(\)/u);
  assert.match(componentSource, /\.abort\(\)/u);
  assert.match(componentSource, /client\.getSurface\(/u);
  assert.match(componentSource, /client\.refetchAuthority\(/u);
  assert.match(componentSource, /client\.mutateSurface\(/u);
  assert.match(componentSource, /invalidateWorkspaceSurfaceAuthority\(/u);
  assert.match(componentSource, /beginWorkspaceSurfaceLoad\(/u);
  assert.match(componentSource, /resolveWorkspaceSurfaceLoad\(/u);
  assert.match(componentSource, /failWorkspaceSurfaceLoad\(/u);

  const mutationCall = componentSource.indexOf('client.mutateSurface(');
  const canonicalRefetch = componentSource.indexOf('client.refetchAuthority(', mutationCall);
  assert.ok(mutationCall >= 0);
  assert.ok(canonicalRefetch > mutationCall);
});

test('reconnect, cursor gaps, and scoped deltas invalidate then canonical-refetch', () => {
  assert.match(componentSource, /authorityInvalidation/u);
  assert.match(componentSource, /lastAuthorityInvalidationRef/u);
  assert.match(componentSource, /invalidateWorkspaceSurfaceAuthority\(/u);
  assert.match(componentSource, /loadSurface\(surface,\s*'canonical'\)/u);
});

test('failed or unavailable mutations retain local drafts instead of resolving as success', () => {
  assert.match(componentSource, /Promise<boolean>/u);
  assert.match(componentSource, /return false;/u);
  assert.match(componentSource, /return true;/u);
  assert.match(componentSource, /if \(!succeeded\) return false;/u);
  assert.doesNotMatch(componentSource, /\.then\(\(\) => \{\s*set(?:Title|Body|Reply|SourceId)/u);
});

test('every authority state remains explicit and refreshable', () => {
  for (const status of ['loading', 'empty', 'stale', 'error', 'unavailable']) {
    assert.match(componentSource, new RegExp(`'${status}'`, 'u'));
  }
  assert.match(componentSource, /workspaceCollaboration\.actions\.refresh/u);
  assert.match(componentSource, /data-reason-code/u);
  assert.match(componentSource, /'empty'/u);
  assert.match(componentSource, /status === 'unavailable'/u);
});

test('authoritative empty collections still render their first-item creation controls', () => {
  const showStateStart = canvasSource.indexOf('const showStateOnly');
  const tabHandlerStart = canvasSource.indexOf('const onTabKeyDown', showStateStart);
  assert.ok(showStateStart >= 0);
  assert.ok(tabHandlerStart > showStateStart);
  const showStateSource = canvasSource.slice(showStateStart, tabHandlerStart);
  assert.match(showStateSource, /!hasData/u);
  assert.match(showStateSource, /status === 'loading'/u);
  assert.match(showStateSource, /status === 'unavailable'/u);
  assert.doesNotMatch(showStateSource, /status === 'empty'/u);
});

test('surface-specific interactions cover goals, discussion, members, genes, and topology', () => {
  assert.match(componentSource, /workspace-collaboration-layout-toggle/u);
  assert.match(componentSource, /'flat'/u);
  assert.match(componentSource, /'lanes'/u);
  for (const action of [
    'create_objective',
    'create_task',
    'create_post',
    'create_reply',
    'pin_post',
    'unpin_post',
    'add_member',
    'remove_member',
    'update_gene',
    'create_node',
    'delete_node',
    'create_edge',
    'delete_edge',
    'update_workspace',
  ]) {
    assert.match(componentSource, new RegExp(`'${action}'`, 'u'));
  }
  assert.doesNotMatch(
    componentSource,
    /'toggle_gene'|'create_topology_node'|'delete_topology_node'|'create_topology_edge'|'delete_topology_edge'|'update_settings'/u,
  );
});

test('Notes is a read-only derived projection and all owned copy uses collaboration keys', () => {
  const notesStart = canvasSource.indexOf('function NotesSurface');
  const topologyStart = canvasSource.indexOf('function initialCanvasState', notesStart);
  assert.ok(notesStart >= 0);
  assert.ok(topologyStart > notesStart);
  const notesSource = canvasSource.slice(notesStart, topologyStart);
  assert.match(notesSource, /aria-readonly="true"/u);
  assert.match(notesSource, /workspaceCollaboration\.notes\.derived/u);
  assert.doesNotMatch(notesSource, /onMutate|<button|<input|<textarea|<form/u);

  assert.match(componentSource, /useI18n\(\)/u);
  assert.doesNotMatch(componentSource, /\bt\('(?!workspaceCollaboration\.)/u);
});

test('Canvas CSS preserves bounded scrolling, responsive tabs, and keyboard focus', () => {
  assert.match(cssSource, /\.workspace-collaboration-canvas/u);
  assert.match(cssSource, /overflow:\s*(?:auto|hidden)/u);
  assert.match(cssSource, /:focus-visible/u);
  assert.match(cssSource, /@media\s*\(max-width:/u);
  assert.match(cssSource, /grid-template-columns/u);
});

test(
  'refresh failures retain stale authority data while explicit empty and unavailable survive',
  () => {
    let state = createWorkspaceCollaborationCanvasState('workspace-1');
    state = beginWorkspaceSurfaceLoad(state, 'files');
    state = resolveWorkspaceSurfaceLoad(state, 'files', state.requestGenerations.files, {
      workspace_id: 'workspace-1',
      surface: 'files',
      authority: 'cloud',
      status: 'ready',
      revision: 4,
      cursor: 'cursor-4',
      data: { files: [{ id: 'file-1', name: 'report.pdf' }] },
      reason_code: null,
    });

    state = beginWorkspaceSurfaceLoad(state, 'files');
    assert.equal(state.surfaces.files.status, 'stale');
    const failed = failWorkspaceSurfaceLoad(
      state,
      'files',
      state.requestGenerations.files,
      'workspace_surface_load_failed',
    );
    assert.equal(failed.surfaces.files.status, 'error');
    assert.deepEqual(failed.surfaces.files.data, {
      files: [{ id: 'file-1', name: 'report.pdf' }],
    });

    for (const status of ['empty', 'unavailable']) {
      let next = beginWorkspaceSurfaceLoad(failed, 'notes');
      next = resolveWorkspaceSurfaceLoad(
        next,
        'notes',
        next.requestGenerations.notes,
        {
          workspace_id: 'workspace-1',
          surface: 'notes',
          authority: 'cloud',
          status,
          revision: 5,
          cursor: null,
          data: status === 'empty' ? { notes: [] } : null,
          reason_code:
            status === 'unavailable' ? 'workspace_notes_unavailable' : null,
        },
      );
      assert.equal(next.surfaces.notes.status, status);
    }
  },
);

test('mutation acknowledgement invalidation is settled only by a newer canonical snapshot', () => {
  let state = createWorkspaceCollaborationCanvasState('workspace-1');
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
      revision: 10,
      cursor: 'cursor-10',
      data: { posts: [{ id: 'post-1' }] },
      reason_code: null,
    },
  );

  state = invalidateWorkspaceSurfaceAuthority(state, 'discussion', 'mutation_ack');
  assert.equal(state.surfaces.discussion.status, 'stale');
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
      revision: 11,
      cursor: 'cursor-11',
      data: { posts: [{ id: 'post-1' }, { id: 'post-2' }] },
      reason_code: null,
    },
  );
  assert.equal(state.surfaces.discussion.status, 'ready');
  assert.equal(state.surfaces.discussion.revision, 11);
});
