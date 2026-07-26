import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { workPlanTimelinePresentation } = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/workPlanTimelineModel.js',
);

test('normalizes direct persisted work-plan steps', () => {
  const plan = workPlanTimelinePresentation({
    id: 'direct-plan',
    type: 'work_plan',
    status: 'completed',
    steps: [
      {
        step_number: 1,
        description: ' Inspect the structured event. ',
        expected_output: ' Evidence ',
      },
      {
        step_number: 2,
        description: 'Verify replay.',
        expected_output: '',
      },
    ],
  });

  assert.deepEqual(plan, {
    steps: [
      {
        stepNumber: 1,
        description: 'Inspect the structured event.',
        expectedOutput: 'Evidence',
      },
      {
        stepNumber: 2,
        description: 'Verify replay.',
        expectedOutput: null,
      },
    ],
    totalSteps: 2,
    currentStep: null,
    status: 'completed',
  });
});

test('normalizes live payload steps and filters malformed entries', () => {
  const plan = workPlanTimelinePresentation({
    id: 'payload-plan',
    type: 'work_plan',
    content: 'This semantic text must not become plan data.',
    payload: {
      total_steps: 4,
      current_step: 2,
      status: 'running',
      steps: [
        {
          step_number: 1,
          description: 'Read the state.',
          expected_output: 'Facts',
        },
        {
          stepNumber: 2,
          description: 'Render the plan.',
          expectedOutput: 'A card',
        },
        {
          step_number: 2,
          description: 'Reject the duplicate step number.',
        },
        { step_number: 0, description: 'Reject zero.' },
        { step_number: -1, description: 'Reject negative step numbers.' },
        { step_number: '3', description: 'Reject the string step number.' },
        { step_number: 4, description: '   ' },
      ],
    },
  });

  assert.deepEqual(plan, {
    steps: [
      {
        stepNumber: 1,
        description: 'Read the state.',
        expectedOutput: 'Facts',
      },
      {
        stepNumber: 2,
        description: 'Render the plan.',
        expectedOutput: 'A card',
      },
    ],
    totalSteps: 4,
    currentStep: 2,
    status: 'running',
  });
});

test('normalizes a durable task-list snapshot into ordered work-plan steps', () => {
  const plan = workPlanTimelinePresentation({
    id: 'task-list-plan',
    type: 'task_list_updated',
    payload: {
      tasks: [
        {
          id: 'task-3',
          content: ' Output the conclusion. ',
          status: 'pending',
          order_index: 2,
        },
        {
          id: 'task-1',
          content: 'Inspect the input.',
          status: 'completed',
          order_index: 0,
        },
        {
          id: 'task-2',
          title: 'A shorter Desktop-only title must not replace Web content.',
          content: 'Summarize the evidence.',
          status: 'in_progress',
          order_index: 1,
        },
        {
          id: 'task-invalid',
          content: '   ',
          status: 'pending',
          order_index: 3,
        },
      ],
    },
  });

  assert.deepEqual(plan, {
    steps: [
      {
        stepNumber: 1,
        description: 'Inspect the input.',
        expectedOutput: null,
      },
      {
        stepNumber: 2,
        description: 'Summarize the evidence.',
        expectedOutput: null,
      },
      {
        stepNumber: 3,
        description: 'Output the conclusion.',
        expectedOutput: null,
      },
    ],
    totalSteps: 3,
    currentStep: 2,
    status: 'in_progress',
  });
});

test('prefers direct history steps and rejects plans without valid structured steps', () => {
  assert.deepEqual(
    workPlanTimelinePresentation({
      id: 'precedence-plan',
      type: 'work_plan',
      steps: [{ step_number: 7, description: 'Persisted step.' }],
      payload: {
        steps: [{ step_number: 1, description: 'Stale live step.' }],
      },
    })?.steps,
    [{ stepNumber: 7, description: 'Persisted step.', expectedOutput: null }],
  );

  assert.equal(
    workPlanTimelinePresentation({
      id: 'invalid-plan',
      type: 'work_plan',
      content: 'Plan: guess this from text.',
      payload: { steps: [{ description: 'Missing step number.' }] },
    }),
    null,
  );
});
