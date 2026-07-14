import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildPlanReplacementPayloads,
  buildPlanReplacementPrompt,
  buildExecutionPrompt,
  buildPlanningPrompt,
  buildRevisionPrompt,
  createReviewPlanDraft,
  enabledReviewPlanSteps,
  hasReviewPlanChanges,
  newTaskAgentTurnResolution,
  newTaskAgentTurnTransport,
  orderedPlanTasks,
  planPriorityTranslationKey,
  planTaskSignature,
  shouldOfferPlanRetry,
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
  assert.notEqual(
    signature,
    planTaskSignature([{ ...tasks[0], content: 'Verify and publish' }, tasks[1]]),
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
