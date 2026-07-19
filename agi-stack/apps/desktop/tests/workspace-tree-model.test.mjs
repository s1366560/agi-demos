import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const { WorkspaceDock } = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/WorkspaceDock.js'
);
const {
  beginWorkspaceConversationRequest,
  buildWorkspaceTree,
  conversationTreeMetadataSummary,
  conversationTreeStatusPresentation,
  conversationTreeStatusValue,
  isWorkspaceConversationSelected,
  isCurrentWorkspaceConversationRequest,
  isWorkspaceOverviewSelected,
  reconcileExpandedWorkspaceIds,
  reconcileWorkspaceConversationRowsAfterRefresh,
  shouldClearConversationSelectionAfterRefresh,
  shouldLoadWorkspaceConversations,
  supersedeWorkspaceConversationRequests,
  workspaceConversationLoadTargets,
  workspaceTreeRootStatusPresentation,
  workspaceTreeRefreshFailed,
  workspaceTreeSessionAvailability,
  workspaceTreeAvailability,
} = require('/tmp/agistack-desktop-test-dist/src/features/workspace/workspaceTreeModel.js');

function conversation(id, title, updatedAt) {
  return {
    id,
    project_id: 'project-1',
    tenant_id: 'tenant-1',
    user_id: 'user-1',
    title,
    status: 'active',
    message_count: 1,
    created_at: '2026-07-01T00:00:00Z',
    updated_at: updatedAt,
  };
}

function renderWorkspaceDock(nodeState, conversationsByWorkspace) {
  return renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(WorkspaceDock, {
        workspaces: [
          {
            id: 'workspace-a',
            tenant_id: 'tenant-1',
            project_id: 'project-1',
            name: 'Desktop Client',
          },
        ],
        conversationsByWorkspace,
        nodeState,
        currentProjectId: 'project-1',
        currentWorkspaceId: 'workspace-a',
        currentConversationId: 'conversation-a',
        selectionMode: 'conversation',
        expandedWorkspaceIds: new Set(['workspace-a']),
        onToggleWorkspace: () => {},
        onRetryProject: () => {},
        onRetryWorkspace: () => {},
        onSelectWorkspace: () => {},
        onSelectConversation: () => {},
      })
    )
  );
}

test('workspace tree preserves the authoritative server order within the current project', () => {
  const workspaces = [
    { id: 'workspace-b', name: 'Beta', project_id: 'project-1' },
    { id: 'workspace-a', name: 'Alpha', project_id: 'project-1' },
  ];
  const conversations = {
    'workspace-a': [
      conversation('conversation-z', 'Zebra task', '2026-07-02T00:00:00Z'),
      conversation('conversation-a', 'Alpha task', '2026-07-03T00:00:00Z'),
    ],
  };

  const tree = buildWorkspaceTree(workspaces, conversations, 'project');

  assert.deepEqual(
    tree.map((node) => node.workspace.id),
    ['workspace-b', 'workspace-a']
  );
  assert.deepEqual(
    tree[1].conversations.map((item) => item.id),
    ['conversation-z', 'conversation-a']
  );
  assert.equal(tree.some((node) => 'project' in node), false);
});

test('recent grouping orders workspaces and conversations by authoritative timestamps', () => {
  const workspaces = [
    { id: 'workspace-old', name: 'Old', updated_at: '2026-07-01T00:00:00Z' },
    { id: 'workspace-new', name: 'New', updated_at: '2026-07-02T00:00:00Z' },
  ];
  const conversations = {
    'workspace-old': [
      conversation('conversation-latest', 'Latest', '2026-07-13T10:00:00Z'),
      conversation('conversation-earlier', 'Earlier', '2026-07-13T09:00:00Z'),
    ],
  };

  const tree = buildWorkspaceTree(workspaces, conversations, 'recent');

  assert.equal(tree[0].workspace.id, 'workspace-old');
  assert.deepEqual(
    tree[0].conversations.map((item) => item.id),
    ['conversation-latest', 'conversation-earlier']
  );
});

test('workspace root is selected only while its overview is visible', () => {
  assert.equal(isWorkspaceOverviewSelected('workspace-a', 'workspace-a', 'overview'), true);
  assert.equal(isWorkspaceOverviewSelected('workspace-a', 'workspace-a', 'conversation'), false);
  assert.equal(isWorkspaceOverviewSelected('workspace-a', 'workspace-b', 'overview'), false);
});

test('conversation rows are selected only in conversation and My Work views', () => {
  assert.equal(
    isWorkspaceConversationSelected('conversation-a', 'conversation-a', 'conversation'),
    true
  );
  assert.equal(
    isWorkspaceConversationSelected('conversation-a', 'conversation-a', 'my-work'),
    true
  );
  assert.equal(
    isWorkspaceConversationSelected('conversation-a', 'conversation-a', 'overview'),
    false
  );
});

test('workspace refresh expands only the selected root on first load', () => {
  assert.deepEqual(
    [
      ...reconcileExpandedWorkspaceIds(
        new Set(),
        ['workspace-a', 'workspace-b'],
        'workspace-b',
        true
      ),
    ],
    ['workspace-b']
  );
});

test('workspace refresh preserves valid manual expansion and removes stale roots', () => {
  assert.deepEqual(
    [
      ...reconcileExpandedWorkspaceIds(
        new Set(['workspace-a', 'workspace-stale']),
        ['workspace-a', 'workspace-b'],
        'workspace-b',
        false
      ),
    ],
    ['workspace-a']
  );
});

test('same-project refresh preserves a manual collapse of the selected workspace', () => {
  assert.deepEqual(
    [
      ...reconcileExpandedWorkspaceIds(
        new Set(),
        ['workspace-a', 'workspace-b'],
        'workspace-b',
        false
      ),
    ],
    []
  );
});

test('same-project refresh keeps cached roots visible without presenting them as current', () => {
  assert.equal(workspaceTreeAvailability({ loading: true, error: null }, 3), 'refreshing');
  assert.equal(
    workspaceTreeAvailability({ loading: false, error: 'offline' }, 3),
    'stale-error'
  );
  assert.equal(workspaceTreeAvailability({ loading: false, error: null }, 3), 'ready');
});

test('stale project and session notices retain the last verified hierarchy and retry actions', () => {
  const conversations = {
    'workspace-a': [
      {
        ...conversation('conversation-a', 'Review auth middleware', '2026-07-14T09:30:00Z'),
        workspace_id: 'workspace-a',
      },
    ],
  };
  const staleProjectMarkup = renderWorkspaceDock(
    {
      projects: { 'project-1': { loading: false, error: 'Project refresh failed' } },
      workspaces: { 'workspace-a': { loading: false, error: null } },
    },
    conversations
  );
  assert.match(staleProjectMarkup, /Refresh failed · showing last verified workspaces/);
  assert.match(staleProjectMarkup, /Desktop Client/);
  assert.match(staleProjectMarkup, /Review auth middleware/);
  assert.match(staleProjectMarkup, />Retry<\/button>/);

  const staleSessionsMarkup = renderWorkspaceDock(
    {
      projects: { 'project-1': { loading: false, error: null } },
      workspaces: { 'workspace-a': { loading: false, error: 'Session refresh failed' } },
    },
    conversations
  );
  assert.match(staleSessionsMarkup, /Refresh failed · showing last verified sessions/);
  assert.match(staleSessionsMarkup, /1 verified sessions · refresh failed/);
  assert.match(staleSessionsMarkup, /Review auth middleware/);
  assert.match(staleSessionsMarkup, />Retry<\/button>/);
});

test('empty tree renders the authoritative loading, error, or empty state', () => {
  assert.equal(workspaceTreeAvailability({ loading: true, error: null }, 0), 'loading');
  assert.equal(workspaceTreeAvailability({ loading: false, error: 'offline' }, 0), 'error');
  assert.equal(workspaceTreeAvailability(undefined, 0), 'empty');
});

test('refresh failure settles the active project without discarding workspace node state', () => {
  assert.deepEqual(
    workspaceTreeRefreshFailed(
      {
        projects: {
          'project-a': { loading: true, error: null },
          'project-b': { loading: false, error: null },
        },
        workspaces: { 'workspace-a': { loading: false, error: null } },
      },
      'project-a',
      'offline'
    ),
    {
      projects: {
        'project-a': { loading: false, error: 'offline' },
        'project-b': { loading: false, error: null },
      },
      workspaces: { 'workspace-a': { loading: false, error: null } },
    }
  );
});

test('conversation hydration targets only the selected and expanded workspace roots', () => {
  const workspaces = [
    { id: 'workspace-a' },
    { id: 'workspace-b' },
    { id: 'workspace-c' },
  ];

  assert.deepEqual(
    workspaceConversationLoadTargets(
      workspaces,
      'workspace-b',
      new Set(['workspace-a', 'workspace-missing'])
    ),
    ['workspace-a', 'workspace-b']
  );
  assert.deepEqual(workspaceConversationLoadTargets(workspaces, '', new Set()), []);
});

test('workspace conversations load once and can retry after a node error', () => {
  assert.equal(shouldLoadWorkspaceConversations(undefined), true);
  assert.equal(shouldLoadWorkspaceConversations({ loading: true, error: null }), false);
  assert.equal(shouldLoadWorkspaceConversations({ loading: false, error: null }), false);
  assert.equal(shouldLoadWorkspaceConversations({ loading: false, error: 'offline' }), true);

  assert.equal(workspaceTreeSessionAvailability(undefined, 0), 'deferred');
  assert.equal(
    workspaceTreeSessionAvailability({ loading: true, error: null }, 0),
    'loading'
  );
  assert.equal(
    workspaceTreeSessionAvailability({ loading: false, error: 'offline' }, 0),
    'error'
  );
  assert.equal(
    workspaceTreeSessionAvailability({ loading: false, error: null }, 0),
    'empty'
  );
  assert.equal(
    workspaceTreeSessionAvailability({ loading: false, error: null }, 2),
    'ready'
  );
  assert.equal(
    workspaceTreeSessionAvailability({ loading: true, error: null }, 2),
    'refreshing'
  );
  assert.equal(
    workspaceTreeSessionAvailability({ loading: false, error: 'offline' }, 2),
    'stale-error'
  );
});

test('failed workspace conversation refresh retains the last verified rows', () => {
  const cached = [conversation('conversation-a', 'Cached', '2026-07-14T09:30:00Z')];
  const refreshed = [conversation('conversation-b', 'Fresh', '2026-07-15T09:30:00Z')];

  assert.equal(
    reconcileWorkspaceConversationRowsAfterRefresh(cached, [], 'offline'),
    cached,
  );
  assert.equal(
    reconcileWorkspaceConversationRowsAfterRefresh(cached, refreshed, null),
    refreshed,
  );
});

test('a completed workspace refresh clears only the unchanged missing selection', () => {
  const selected = {
    scopeKey: 'project-1\u0000workspace-a',
    conversationId: 'conversation-a',
  };
  const changedSelection = {
    scopeKey: 'project-1\u0000workspace-a',
    conversationId: 'conversation-b',
  };
  const refreshed = [
    conversation('conversation-b', 'Still here', '2026-07-14T09:30:00Z'),
  ];

  assert.equal(
    shouldClearConversationSelectionAfterRefresh(
      selected,
      selected,
      'project-1\u0000workspace-a',
      refreshed
    ),
    true
  );
  assert.equal(
    shouldClearConversationSelectionAfterRefresh(
      selected,
      changedSelection,
      'project-1\u0000workspace-a',
      refreshed
    ),
    false
  );
  assert.equal(
    shouldClearConversationSelectionAfterRefresh(
      selected,
      selected,
      'project-1\u0000workspace-b',
      refreshed
    ),
    false
  );
  assert.equal(
    shouldClearConversationSelectionAfterRefresh(
      changedSelection,
      changedSelection,
      'project-1\u0000workspace-a',
      refreshed
    ),
    false
  );
  assert.equal(
    shouldClearConversationSelectionAfterRefresh(
      null,
      selected,
      'project-1\u0000workspace-a',
      refreshed
    ),
    false
  );
});

test('workspace conversation request generations allow only the latest request to settle', () => {
  const generations = new Map();
  const first = beginWorkspaceConversationRequest(generations, 'workspace-a');
  const unrelated = beginWorkspaceConversationRequest(generations, 'workspace-b');
  const second = beginWorkspaceConversationRequest(generations, 'workspace-a');

  assert.equal(first, 1);
  assert.equal(unrelated, 1);
  assert.equal(second, 2);
  assert.equal(isCurrentWorkspaceConversationRequest(generations, 'workspace-a', first), false);
  assert.equal(isCurrentWorkspaceConversationRequest(generations, 'workspace-a', second), true);
  assert.equal(isCurrentWorkspaceConversationRequest(generations, 'workspace-b', unrelated), true);
});

test('a newer runtime refresh takes ownership of unresolved refresh workspace requests', () => {
  const generations = new Map();
  const firstA = beginWorkspaceConversationRequest(generations, 'workspace-a');
  const firstB = beginWorkspaceConversationRequest(generations, 'workspace-b');
  const activeRefresh = new Map([
    ['workspace-a', firstA],
    ['workspace-b', firstB],
  ]);
  const newerLazyB = beginWorkspaceConversationRequest(generations, 'workspace-b');

  const nextRefresh = supersedeWorkspaceConversationRequests(generations, activeRefresh);

  assert.equal(isCurrentWorkspaceConversationRequest(generations, 'workspace-a', firstA), false);
  assert.equal(nextRefresh.get('workspace-a'), 2);
  assert.equal(nextRefresh.has('workspace-b'), false);
  assert.equal(isCurrentWorkspaceConversationRequest(generations, 'workspace-b', newerLazyB), true);
});

test('tree status presentation translates every governed conversation state', () => {
  const expected = {
    active: 'idle',
    running: 'active',
    queued: 'queued',
    paused: 'paused',
    needs_input: 'attention',
    needs_approval: 'attention',
    ready_review: 'ready',
    completed: 'completed',
    failed: 'danger',
    disconnected: 'danger',
    interrupted: 'danger',
    cancelled: 'offline',
    archived: 'offline',
    inactive: 'offline',
  };

  for (const [status, tone] of Object.entries(expected)) {
    const presentation = conversationTreeStatusPresentation(status);
    assert.equal(presentation.tone, tone, status);
    assert.match(presentation.labelKey, /^workspaceTree\./, status);
  }
  assert.deepEqual(conversationTreeStatusPresentation('future_state'), {
    tone: 'unknown',
    labelKey: 'workspaceTree.unknown',
  });
  assert.deepEqual(conversationTreeStatusPresentation('needs_approval'), {
    tone: 'attention',
    labelKey: 'workspaceTree.needsApproval',
  });
});

test('conversation lifecycle activity remains distinct from an executing run', () => {
  const lifecycleOnly = conversation(
    'conversation-active',
    'Active conversation',
    '2026-07-14T09:30:00Z'
  );

  assert.equal(conversationTreeStatusValue(lifecycleOnly), 'active');
  assert.deepEqual(conversationTreeStatusPresentation('active'), {
    tone: 'idle',
    labelKey: 'workspaceTree.active',
  });
  assert.deepEqual(workspaceTreeRootStatusPresentation('inactive', [lifecycleOnly]), {
    tone: 'offline',
    labelKey: 'workspaceTree.offline',
  });
});

test('workspace root remains unknown when neither runtime nor loaded run metadata reports status', () => {
  const lifecycleOnly = conversation(
    'conversation-active',
    'Active conversation',
    '2026-07-14T09:30:00Z'
  );

  assert.deepEqual(workspaceTreeRootStatusPresentation(undefined, []), {
    tone: 'unknown',
    labelKey: 'workspaceTree.unknown',
  });
  assert.deepEqual(workspaceTreeRootStatusPresentation('', [lifecycleOnly]), {
    tone: 'unknown',
    labelKey: 'workspaceTree.unknown',
  });
});

test('conversation tree summary prefers explicit structured display metadata', () => {
  const item = conversation(
    'conversation-display',
    'Offline running task 99%',
    '2026-07-14T09:30:00Z'
  );
  item.metadata = {
    display: { subtitle: 'Reviewing verified changes' },
    run: {
      environment: { label: 'Worktree' },
      progress: { percent: 72 },
    },
  };

  assert.equal(conversationTreeMetadataSummary(item), 'Reviewing verified changes');
});

test('conversation tree summary composes explicit environment and progress metadata', () => {
  const item = conversation(
    'conversation-progress',
    'A title must never drive the secondary text',
    '2026-07-14T09:30:00Z'
  );
  item.metadata = {
    run: {
      environment: { label: 'Worktree' },
      progress: { percent: 72 },
    },
  };

  assert.equal(conversationTreeMetadataSummary(item), 'Worktree · 72%');
});

test('conversation tree summary ignores titles and malformed metadata', () => {
  const titleOnly = conversation(
    'conversation-title-only',
    'Running in Worktree · 72%',
    '2026-07-14T09:30:00Z'
  );
  const malformed = conversation(
    'conversation-malformed',
    'Needs approval',
    '2026-07-14T09:30:00Z'
  );
  malformed.metadata = {
    display: { subtitle: 42 },
    run: {
      environment: { label: false },
      progress: { percent: '72' },
    },
  };

  assert.equal(conversationTreeMetadataSummary(titleOnly), null);
  assert.equal(conversationTreeMetadataSummary(malformed), null);
});

test('workspace root status escalates structured child attention before runtime health', () => {
  const running = conversation('conversation-running', 'Running', '2026-07-14T09:30:00Z');
  running.metadata = { run: { status: 'running' } };
  const approval = conversation('conversation-approval', 'Approval', '2026-07-14T09:31:00Z');
  approval.metadata = { run: { status: 'needs_approval' } };
  const input = conversation('conversation-input', 'Input', '2026-07-14T09:31:30Z');
  input.metadata = { run: { status: 'needs_input' } };
  const failed = conversation('conversation-failed', 'Failed', '2026-07-14T09:32:00Z');
  failed.metadata = { run: { status: 'failed' } };

  assert.equal(conversationTreeStatusValue(approval), 'needs_approval');
  assert.deepEqual(
    workspaceTreeRootStatusPresentation('online', [running, failed, approval]),
    { tone: 'attention', labelKey: 'workspaceTree.needsAttention' }
  );
  assert.deepEqual(
    workspaceTreeRootStatusPresentation('online', [approval, input]),
    workspaceTreeRootStatusPresentation('online', [input, approval])
  );
  assert.deepEqual(workspaceTreeRootStatusPresentation('online', [running, failed]), {
    tone: 'danger',
    labelKey: 'workspaceTree.issue',
  });
  assert.deepEqual(workspaceTreeRootStatusPresentation('online', []), {
    tone: 'active',
    labelKey: 'workspaceTree.online',
  });
});
