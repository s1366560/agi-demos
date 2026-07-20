import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildPlanReplacementPayloads,
  buildPlanReplacementPrompt,
  buildExecutionPrompt,
  buildPlanningPrompt,
  buildRevisionPrompt,
  canResumeLegacyPlanApproval,
  canActivateNewTaskSession,
  clearLegacyPlanApprovalRecovery,
  createLegacyPlanApprovalRecovery,
  createReviewPlanDraft,
  enabledReviewPlanSteps,
  hasReviewPlanChanges,
  isFreshPlanningPlan,
  LEGACY_PLAN_APPROVAL_TTL_MS,
  legacyPlanApprovalRuntimeScope,
  newTaskAgentTurnResolution,
  newTaskAgentTurnTransport,
  newTaskDefinitionSignature,
  orderedPlanTasks,
  planPriorityTranslationKey,
  planTaskSignature,
  planningTurnAttempt,
  readLegacyPlanApprovalRecovery,
  shouldOfferPlanRetry,
  writeLegacyPlanApprovalRecovery,
} from '/tmp/agistack-desktop-test-dist/src/features/task/newTaskPlanModel.js';

test('planning prompt establishes a real structured plan and approval boundary', () => {
  const prompt = buildPlanningPrompt({
    title: 'Repair session UX',
    objective: 'Redesign the conversation detail experience',
    kind: 'programming',
    workspaceRoot: '/workspace/app',
  });

  assert.match(prompt, /todowrite/);
  assert.match(prompt, /submit_plan/);
  assert.match(prompt, /without changing files/);
  assert.match(prompt, /human explicitly approves/);
  assert.match(prompt, /\/workspace\/app/);
});

test('revision and execution prompts preserve the human authority boundary', () => {
  assert.match(buildRevisionPrompt('Add accessibility verification'), /Remain in Plan mode/);
  assert.match(buildRevisionPrompt('Add accessibility verification'), /accessibility verification/);
  assert.match(buildExecutionPrompt(), /human approved/);
  assert.match(buildExecutionPrompt(), /permission, credential, or irreversible decision/);
});

test('plan tasks are ordered and revisions change the plan signature', () => {
  const tasks = [
    {
      id: '2',
      conversation_id: 'c1',
      content: 'Verify',
      status: 'pending',
      priority: 'medium',
      order_index: 2,
      created_at: '2026-01-01',
      updated_at: '2026-01-01',
    },
    {
      id: '1',
      conversation_id: 'c1',
      content: 'Inspect',
      status: 'pending',
      priority: 'high',
      order_index: 1,
      created_at: '2026-01-01',
      updated_at: '2026-01-01',
    },
  ];

  assert.deepEqual(orderedPlanTasks(tasks).map((task) => task.id), ['1', '2']);
  const signature = planTaskSignature(tasks);
  assert.match(signature, /^sha256:[a-f0-9]{64}$/);
  assert.doesNotMatch(signature, /Verify|Implement/);
  assert.notEqual(
    signature,
    planTaskSignature([{ ...tasks[0], content: 'Verify and publish' }, tasks[1]]),
  );
  assert.notEqual(
    signature,
    planTaskSignature([{ ...tasks[0], id: 'replacement-task' }, tasks[1]]),
  );
});

test('review draft preserves authoritative order and records explicit human changes', () => {
  const tasks = [
    {
      id: '2',
      conversation_id: 'c1',
      content: 'Verify',
      status: 'pending',
      priority: 'medium',
      order_index: 2,
      created_at: '2026-01-01',
      updated_at: '2026-01-01',
    },
    {
      id: '1',
      conversation_id: 'c1',
      content: 'Inspect',
      status: 'pending',
      priority: 'high',
      order_index: 1,
      created_at: '2026-01-01',
      updated_at: '2026-01-01',
    },
  ];

  const draft = createReviewPlanDraft(tasks);
  assert.deepEqual(draft.map((step) => step.content), ['Inspect', 'Verify']);
  assert.equal(hasReviewPlanChanges(tasks, draft), false);

  const changed = [
    { ...draft[0], content: 'Inspect the current boundary' },
    { ...draft[1], enabled: false },
    {
      id: 'human-step-3',
      content: 'Document residual risk',
      priority: 'low',
      enabled: true,
      sourceTaskId: null,
    },
  ];
  assert.equal(hasReviewPlanChanges(tasks, changed), true);
  assert.deepEqual(
    enabledReviewPlanSteps(changed).map((step) => step.content),
    ['Inspect the current boundary', 'Document residual risk'],
  );
});

test('plan replacement prompt carries only enabled human-reviewed steps', () => {
  const steps = [
    {
      id: 'step-1',
      content: 'Inspect the current boundary',
      priority: 'high',
      enabled: true,
      sourceTaskId: 'task-1',
    },
    {
      id: 'step-2',
      content: 'Remove this step',
      priority: 'medium',
      enabled: false,
      sourceTaskId: 'task-2',
    },
  ];
  const prompt = buildPlanReplacementPrompt(steps);
  const payloads = buildPlanReplacementPayloads(steps);

  assert.match(prompt, /Remain in Plan mode/);
  assert.match(prompt, /Inspect the current boundary/);
  assert.doesNotMatch(prompt, /Remove this step/);
  assert.match(prompt, /structured task-list tool/);
  assert.deepEqual(payloads.cloud, {
    action: 'replace',
    todos: [{ content: 'Inspect the current boundary', priority: 'high' }],
  });
  assert.deepEqual(payloads.local, {
    tasks: [{ content: 'Inspect the current boundary', priority: 'high' }],
  });
  assert.match(prompt, /"action":"replace"/);
  assert.match(prompt, /"todos":/);
  assert.match(prompt, /"tasks":/);
});

test('cloud planning never falls back to the local REST conversation endpoint', () => {
  assert.equal(newTaskAgentTurnTransport('cloud', true), 'socket');
  assert.equal(newTaskAgentTurnTransport('cloud', false), 'live_socket_required');
  assert.equal(newTaskAgentTurnTransport('local', false), 'local_http');
});

test('agent turn acknowledgment stays bound to the exact conversation and message when supplied', () => {
  assert.equal(
    newTaskAgentTurnResolution(
      { conversationId: 'c1', status: 'acknowledged' },
      'c1',
      'message-1',
    ),
    null,
  );
  assert.equal(
    newTaskAgentTurnResolution(
      { conversationId: 'c1', messageId: 'message-2', status: 'acknowledged' },
      'c1',
      'message-1',
    ),
    null,
  );
  assert.equal(
    newTaskAgentTurnResolution(
      { conversationId: 'c2', messageId: 'message-1', status: 'failed' },
      'c1',
      'message-1',
    ),
    null,
  );
  assert.equal(
    newTaskAgentTurnResolution(
      { conversationId: 'c1', messageId: 'message-1', status: 'failed' },
      'c1',
      'message-1',
    ),
    'failed',
  );
  assert.equal(
    newTaskAgentTurnResolution(
      { conversationId: 'c1', status: 'failed' },
      'c1',
      'message-1',
    ),
    null,
  );
});

test('delayed planning and priority presentation use structural protocol values', () => {
  assert.equal(shouldOfferPlanRetry(7), false);
  assert.equal(shouldOfferPlanRetry(8), true);
  assert.equal(planPriorityTranslationKey('high'), 'task.priorityHigh');
  assert.equal(planPriorityTranslationKey('unexpected'), 'task.priorityUnknown');
});

test('task-session signatures distinguish persisted briefs while ignoring planning-only context', () => {
  const definition = {
    title: 'Repair session UX',
    objective: 'Make plan recovery durable',
    kind: 'programming',
    workspaceRoot: ' /workspace/app ',
    contextSources: ['project_files', 'project_memory'],
  };
  const signature = newTaskDefinitionSignature(definition, 'workspace-1');

  assert.equal(
    signature,
    newTaskDefinitionSignature(
      { ...definition, contextSources: ['project_memory', 'project_files'] },
      'workspace-1',
    ),
  );
  assert.equal(
    signature,
    newTaskDefinitionSignature(
      {
        ...definition,
        workspaceRoot: '/workspace/another-root',
        contextSources: ['web_research'],
      },
      'workspace-1',
    ),
  );
  assert.notEqual(
    signature,
    newTaskDefinitionSignature({ ...definition, objective: 'Use the old brief' }, 'workspace-1'),
  );
  assert.notEqual(signature, newTaskDefinitionSignature(definition, 'workspace-2'));
});

test('same planning intent reuses its message id while a new intent allocates another', () => {
  let sequence = 0;
  const createId = () => `message-${++sequence}`;
  const first = planningTurnAttempt(null, 'conversation-1:brief-a', createId);
  const retry = planningTurnAttempt(first, 'conversation-1:brief-a', createId);
  const revised = planningTurnAttempt(retry, 'conversation-1:brief-b', createId);

  assert.equal(retry, first);
  assert.equal(retry.messageId, 'message-1');
  assert.equal(revised.messageId, 'message-2');
});

test('polling accepts only a non-empty plan newer than the attempt baseline', () => {
  assert.equal(isFreshPlanningPlan([], '', '', false), false);
  assert.equal(isFreshPlanningPlan([{ id: 'task-1' }], 'plan-a', 'plan-a', false), false);
  assert.equal(isFreshPlanningPlan([{ id: 'task-1' }], 'plan-b', 'plan-a', false), true);
  assert.equal(isFreshPlanningPlan([{ id: 'task-1' }], 'plan-a', 'plan-a', true), true);
});

test('session activation requires workspace binding but tolerates an unknown delivery outcome', () => {
  assert.equal(
    canActivateNewTaskSession('workspace-1', 'workspace-1', 'acknowledged'),
    true,
  );
  assert.equal(
    canActivateNewTaskSession('workspace-1', 'workspace-1', 'unknown_outcome'),
    true,
  );
  assert.equal(canActivateNewTaskSession('workspace-1', null, 'acknowledged'), false);
  assert.equal(
    canActivateNewTaskSession('workspace-1', 'workspace-2', 'unknown_outcome'),
    false,
  );
});

test('legacy approval recovery persists one exact message id and plan signature', () => {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
  const runtimeScope = legacyPlanApprovalRuntimeScope({
    apiBaseUrl: 'http://127.0.0.1:8000',
    mode: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
  });
  const planSignature = `sha256:${'a'.repeat(64)}`;
  const changedPlanSignature = `sha256:${'b'.repeat(64)}`;
  const createdAt = 1_000;
  const recovery = createLegacyPlanApprovalRecovery(
    'conversation-1',
    planSignature,
    'desktop-build-request-1',
    runtimeScope,
    createdAt,
  );

  assert.equal(writeLegacyPlanApprovalRecovery(storage, recovery), true);
  assert.deepEqual(
    readLegacyPlanApprovalRecovery(
      storage,
      'conversation-1',
      planSignature,
      runtimeScope,
      createdAt + 1,
    ),
    recovery,
  );
  assert.equal(
    readLegacyPlanApprovalRecovery(
      storage,
      'conversation-1',
      changedPlanSignature,
      runtimeScope,
      createdAt + 1,
    ),
    null,
  );
  assert.equal(values.size, 0, 'a mismatched authoritative plan removes stale recovery');

  assert.equal(writeLegacyPlanApprovalRecovery(storage, recovery), true);
  assert.equal(
    readLegacyPlanApprovalRecovery(
      storage,
      'conversation-1',
      planSignature,
      runtimeScope,
      createdAt + LEGACY_PLAN_APPROVAL_TTL_MS,
    ),
    null,
  );
  assert.equal(values.size, 0, 'an expired recovery record is removed');

  assert.equal(writeLegacyPlanApprovalRecovery(storage, recovery), true);
  assert.equal(clearLegacyPlanApprovalRecovery(storage, 'conversation-1'), true);
  assert.equal(values.size, 0);

  const oversizedMessageId = createLegacyPlanApprovalRecovery(
    'conversation-1',
    planSignature,
    'm'.repeat(256),
    runtimeScope,
    createdAt,
  );
  assert.equal(writeLegacyPlanApprovalRecovery(storage, oversizedMessageId), false);
});

test('legacy approval recovery scope is opaque and isolates runtime authority', () => {
  const base = {
    apiBaseUrl: 'http://127.0.0.1:8000/',
    mode: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
  };
  const scope = legacyPlanApprovalRuntimeScope(base);

  assert.match(scope, /^sha256:[a-f0-9]{64}$/);
  assert.doesNotMatch(scope, /tenant-1|project-1|127\.0\.0\.1/);
  assert.equal(
    legacyPlanApprovalRuntimeScope({ ...base, apiBaseUrl: 'http://127.0.0.1:8000' }),
    scope,
  );
  assert.notEqual(legacyPlanApprovalRuntimeScope({ ...base, tenantId: 'tenant-2' }), scope);
  assert.notEqual(
    legacyPlanApprovalRuntimeScope({ ...base, apiBaseUrl: 'http://127.0.0.1:8088' }),
    scope,
  );
  assert.equal(legacyPlanApprovalRuntimeScope({ ...base, apiBaseUrl: 'file:///tmp/runtime' }), '');
});

test('build-mode legacy recovery requires the exact durable intent and no accepted attempt', () => {
  const planSignature = `sha256:${'a'.repeat(64)}`;
  const recovery = createLegacyPlanApprovalRecovery(
    'conversation-1',
    planSignature,
    'desktop-build-request-1',
    `sha256:${'b'.repeat(64)}`,
  );

  assert.equal(canResumeLegacyPlanApproval('plan', false, planSignature, null), true);
  assert.equal(canResumeLegacyPlanApproval('build', false, planSignature, recovery), true);
  assert.equal(canResumeLegacyPlanApproval('build', true, planSignature, recovery), false);
  assert.equal(
    canResumeLegacyPlanApproval('build', false, `sha256:${'c'.repeat(64)}`, recovery),
    false,
  );
  assert.equal(canResumeLegacyPlanApproval('build', false, planSignature, null), false);
});
