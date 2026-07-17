import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  countMyWorkDisplayGroups,
  countMyWorkGroups,
  describeMyWorkAuthority,
  filterMyWorkDisplayItems,
  filterMyWorkItems,
  groupMyWorkDisplayItems,
  MY_WORK_DISPLAY_GROUP_BY_AUTHORITY_GROUP,
  MY_WORK_DISPLAY_GROUPS,
  myWorkDisplayGroupForAuthorityGroup,
  myWorkConversationMatchesScope,
  myWorkItemKey,
  myWorkRefreshScopeIsCurrent,
  socketEventInvalidatesMyWork,
} = require('/tmp/agistack-desktop-test-dist/src/features/my-work/myWorkModel.js');

const items = [
  {
    id: 'approval',
    title: 'Approve release boundary',
    group: 'needs_approval',
    capability_mode: 'code',
    updated_at: '2026-07-13T02:00:00Z',
    created_at: '2026-07-13T01:00:00Z',
  },
  {
    id: 'input',
    title: 'Clarify research scope',
    group: 'needs_input',
    capability_mode: 'work',
    updated_at: '2026-07-13T03:00:00Z',
    created_at: '2026-07-13T01:00:00Z',
  },
  {
    id: 'review',
    title: 'Review release evidence',
    group: 'ready_review',
    capability_mode: 'code',
    updated_at: '2026-07-13T04:00:00Z',
    created_at: '2026-07-13T01:00:00Z',
  },
  {
    id: 'unclassified',
    title: 'Inspect imported workspace task',
    group: 'running',
    capability_mode: null,
    updated_at: '2026-07-13T05:00:00Z',
    created_at: '2026-07-13T01:00:00Z',
  },
];

test('My Work keeps an unclassified backend item visible without guessing its mode', () => {
  assert.deepEqual(
    filterMyWorkItems(items, 'all', 'code').map((item) => item.id),
    ['unclassified', 'review', 'approval']
  );
  assert.deepEqual(
    filterMyWorkItems(items, 'all', 'work').map((item) => item.id),
    ['unclassified', 'input']
  );
  assert.deepEqual(
    filterMyWorkItems(items, 'needs_input', 'all').map((item) => item.id),
    ['input']
  );
});

test('My Work list identity includes the authority namespace', () => {
  assert.equal(
    myWorkItemKey({ authority_kind: 'workspace_attempt', authority_id: 'shared-1' }),
    'workspace_attempt:shared-1'
  );
  assert.notEqual(
    myWorkItemKey({ authority_kind: 'workspace_attempt', authority_id: 'shared-1' }),
    myWorkItemKey({ authority_kind: 'hitl_request', authority_id: 'shared-1' })
  );
});

test('My Work search is a case-insensitive title filter inside the selected mode', () => {
  assert.deepEqual(
    filterMyWorkItems(items, 'all', 'code', 'RELEASE').map((item) => item.id),
    ['review', 'approval']
  );
  assert.deepEqual(
    filterMyWorkItems(items, 'all', 'work', 'release').map((item) => item.id),
    []
  );
});

test('My Work counts preserve the four authoritative attention groups', () => {
  assert.deepEqual(countMyWorkGroups(items), {
    needs_input: 1,
    needs_approval: 1,
    running: 1,
    ready_review: 1,
  });
});

test('My Work maps four authority groups into the source prototype display order', () => {
  assert.deepEqual(MY_WORK_DISPLAY_GROUPS, ['needs_input', 'running', 'ready_review']);
  assert.equal(Object.isFrozen(MY_WORK_DISPLAY_GROUPS), true);
  assert.deepEqual(MY_WORK_DISPLAY_GROUP_BY_AUTHORITY_GROUP, {
    needs_input: 'needs_input',
    needs_approval: 'needs_input',
    running: 'running',
    ready_review: 'ready_review',
  });
  assert.equal(Object.isFrozen(MY_WORK_DISPLAY_GROUP_BY_AUTHORITY_GROUP), true);
  assert.equal(myWorkDisplayGroupForAuthorityGroup('needs_input'), 'needs_input');
  assert.equal(myWorkDisplayGroupForAuthorityGroup('needs_approval'), 'needs_input');
  assert.equal(myWorkDisplayGroupForAuthorityGroup('running'), 'running');
  assert.equal(myWorkDisplayGroupForAuthorityGroup('ready_review'), 'ready_review');
});

test('My Work display groups and counts combine input and approval authority structurally', () => {
  assert.deepEqual(
    groupMyWorkDisplayItems(items).map(({ group, items: groupItems }) => ({
      group,
      ids: groupItems.map((item) => item.id),
    })),
    [
      { group: 'needs_input', ids: ['input', 'approval'] },
      { group: 'running', ids: ['unclassified'] },
      { group: 'ready_review', ids: ['review'] },
    ]
  );
  assert.deepEqual(countMyWorkDisplayGroups(items), {
    needs_input: 2,
    running: 1,
    ready_review: 1,
  });
});

test('My Work display filtering uses explicit capability mode and keeps unclassified items visible', () => {
  assert.deepEqual(
    filterMyWorkDisplayItems(items, 'needs_input', 'code').map((item) => item.id),
    ['approval']
  );
  assert.deepEqual(
    groupMyWorkDisplayItems(items, 'code').map(({ group, items: groupItems }) => ({
      group,
      ids: groupItems.map((item) => item.id),
    })),
    [
      { group: 'needs_input', ids: ['approval'] },
      { group: 'running', ids: ['unclassified'] },
      { group: 'ready_review', ids: ['review'] },
    ]
  );
  assert.deepEqual(countMyWorkDisplayGroups(items, 'work'), {
    needs_input: 1,
    running: 1,
    ready_review: 0,
  });
});

test('My Work titles never infer or override the structured display group', () => {
  const narrativeDecoys = [
    {
      ...items[0],
      id: 'approval-called-running',
      title: 'Running and ready to review',
      group: 'needs_approval',
    },
    {
      ...items[3],
      id: 'running-called-input',
      title: 'Needs input before approval',
      group: 'running',
    },
    {
      ...items[2],
      id: 'ready-called-input',
      title: 'Needs input while running',
      group: 'ready_review',
    },
  ];

  assert.deepEqual(
    groupMyWorkDisplayItems(narrativeDecoys).map(({ group, items: groupItems }) => ({
      group,
      ids: groupItems.map((item) => item.id),
    })),
    [
      { group: 'needs_input', ids: ['approval-called-running'] },
      { group: 'running', ids: ['running-called-input'] },
      { group: 'ready_review', ids: ['ready-called-input'] },
    ]
  );
});

test('My Work exposes desktop runtime facts only for desktop-run authority', () => {
  assert.deepEqual(
    describeMyWorkAuthority({
      authority_kind: 'desktop_run',
      authority_id: 'run-1',
      run_id: 'run-1',
      revision: 7,
      attempt_number: null,
      permission_profile: 'workspace_write',
      environment: { id: 'environment-1', label: 'main worktree' },
      last_heartbeat_at: '2026-07-13T05:00:00Z',
    }),
    {
      sourceKey: 'myWork.authorityKind.desktop_run',
      descriptionKey: 'myWork.authorityDescription.desktop_run',
      identifier: 'run-1',
      sequence: { labelKey: 'myWork.runRevisionLabel', value: '7' },
      runtime: {
        runId: 'run-1',
        revision: 7,
        permissionProfile: 'workspace_write',
        environment: { id: 'environment-1', label: 'main worktree' },
        lastHeartbeatAt: '2026-07-13T05:00:00Z',
      },
    }
  );
});

test('My Work presents workspace attempts without fabricated desktop runtime facts', () => {
  assert.deepEqual(
    describeMyWorkAuthority({
      authority_kind: 'workspace_attempt',
      authority_id: 'attempt-4',
      run_id: null,
      revision: null,
      attempt_number: 4,
      permission_profile: null,
      environment: null,
      last_heartbeat_at: null,
    }),
    {
      sourceKey: 'myWork.authorityKind.workspace_attempt',
      descriptionKey: 'myWork.authorityDescription.workspace_attempt',
      identifier: 'attempt-4',
      sequence: { labelKey: 'myWork.attemptNumber', value: '4' },
      runtime: null,
    }
  );
});

test('My Work presents HITL authority without exposing request payload details', () => {
  const presentation = describeMyWorkAuthority({
    authority_kind: 'hitl_request',
    authority_id: 'hitl-2',
    run_id: null,
    revision: null,
    attempt_number: null,
    permission_profile: null,
    environment: null,
    last_heartbeat_at: null,
    question: 'SECRET prompt text',
    options: ['SECRET option'],
    context: { secret: 'SECRET context' },
  });

  assert.deepEqual(presentation, {
    sourceKey: 'myWork.authorityKind.hitl_request',
    descriptionKey: 'myWork.authorityDescription.hitl_request',
    identifier: 'hitl-2',
    sequence: null,
    runtime: null,
  });
  assert.equal('question' in presentation, false);
  assert.equal('options' in presentation, false);
  assert.equal('context' in presentation, false);
});

test('My Work fails closed when a backend sends an unknown authority discriminator', () => {
  assert.deepEqual(
    describeMyWorkAuthority({
      authority_kind: 'legacy_guess',
      authority_id: 'legacy-1',
      run_id: null,
      revision: null,
      attempt_number: null,
      permission_profile: null,
      environment: null,
      last_heartbeat_at: null,
    }),
    {
      sourceKey: 'myWork.authorityKind.unknown',
      descriptionKey: 'myWork.authorityDescription.unknown',
      identifier: 'legacy-1',
      sequence: null,
      runtime: null,
    }
  );
});

test('My Work refreshes only for structured run, HITL, and review state events', () => {
  assert.equal(
    socketEventInvalidatesMyWork({ type: 'event', payload: { event_type: 'run_status' } }),
    true
  );
  assert.equal(socketEventInvalidatesMyWork({ event_type: 'permission_asked' }), true);
  assert.equal(socketEventInvalidatesMyWork({ type: 'review_decision' }), true);
  for (const eventType of [
    'a2ui_action_asked',
    'a2ui_action_answered',
    'clarification_answered',
    'decision_answered',
    'env_var_provided',
    'permission_replied',
  ]) {
    assert.equal(socketEventInvalidatesMyWork({ event_type: eventType }), true, eventType);
  }
  assert.equal(socketEventInvalidatesMyWork({ type: 'text_delta' }), false);
  assert.equal(socketEventInvalidatesMyWork({ payload: { type: 'assistant_message' } }), false);
});

test('My Work scheduled refresh rejects a later context or request scope', () => {
  const scheduled = { contextRevision: 4, scopeEpoch: 7 };

  assert.equal(myWorkRefreshScopeIsCurrent(scheduled, scheduled), true);
  assert.equal(
    myWorkRefreshScopeIsCurrent(scheduled, { contextRevision: 5, scopeEpoch: 7 }),
    false
  );
  assert.equal(
    myWorkRefreshScopeIsCurrent(scheduled, { contextRevision: 4, scopeEpoch: 8 }),
    false
  );
});

test('My Work opens only the exact tenant, project, workspace, and conversation scope', () => {
  const item = {
    ...items[0],
    project_id: 'project-1',
    workspace_id: 'workspace-1',
    conversation_id: 'conversation-1',
  };
  const conversation = {
    id: 'conversation-1',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    workspace_id: 'workspace-1',
  };
  const context = { tenantId: 'tenant-1', projectId: 'project-1' };

  assert.equal(myWorkConversationMatchesScope(item, conversation, context), true);
  assert.equal(
    myWorkConversationMatchesScope(
      item,
      { ...conversation, id: 'conversation-2' },
      context
    ),
    false
  );
  assert.equal(
    myWorkConversationMatchesScope(
      item,
      { ...conversation, project_id: 'project-2' },
      context
    ),
    false
  );
  assert.equal(
    myWorkConversationMatchesScope(
      { ...item, project_id: 'project-2' },
      conversation,
      context
    ),
    false
  );
  assert.equal(
    myWorkConversationMatchesScope(
      item,
      { ...conversation, workspace_id: null },
      context
    ),
    false
  );
  assert.equal(
    myWorkConversationMatchesScope(
      item,
      { ...conversation, tenant_id: 'tenant-2' },
      context
    ),
    false
  );
});
