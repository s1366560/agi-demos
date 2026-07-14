import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildExecutionPrompt,
  buildPlanningPrompt,
  buildRevisionPrompt,
  orderedPlanTasks,
  planTaskSignature,
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
