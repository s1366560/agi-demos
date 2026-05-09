import { describe, expect, it } from 'vitest';

import {
  buildIterationRuns,
  iterationCarryover,
  iterationInteractionStats,
  iterationNodeIndex,
  iterationOutputs,
} from '@/components/blackboard/tabs/planRunSnapshotModel';

import type {
  WorkspacePlanEvent,
  WorkspacePlanNode,
  WorkspacePlanOutboxItem,
  WorkspacePlanSnapshot,
} from '@/types/workspace';

function node(overrides: Partial<WorkspacePlanNode>): WorkspacePlanNode {
  return {
    id: 'node-1',
    parent_id: 'goal-1',
    kind: 'task',
    title: 'Task',
    description: '',
    depends_on: [],
    acceptance_criteria: [],
    recommended_capabilities: [],
    intent: 'todo',
    execution: 'idle',
    progress: { percent: 0, confidence: 0.5, note: '' },
    assignee_agent_id: null,
    current_attempt_id: null,
    workspace_task_id: null,
    priority: 1,
    metadata: {},
    created_at: '2026-05-01T00:00:00Z',
    ...overrides,
  };
}

function event(overrides: Partial<WorkspacePlanEvent>): WorkspacePlanEvent {
  return {
    id: 'event-1',
    plan_id: 'plan-1',
    workspace_id: 'ws-1',
    node_id: null,
    attempt_id: null,
    event_type: 'worker_report_terminal',
    source: 'workspace_worker',
    actor_id: null,
    payload: {},
    created_at: '2026-05-01T00:00:00Z',
    ...overrides,
  };
}

function outbox(overrides: Partial<WorkspacePlanOutboxItem>): WorkspacePlanOutboxItem {
  return {
    id: 'outbox-1',
    plan_id: 'plan-1',
    workspace_id: 'ws-1',
    event_type: 'supervisor_tick',
    payload: {},
    status: 'completed',
    attempt_count: 1,
    max_attempts: 3,
    metadata: {},
    created_at: '2026-05-01T00:00:00Z',
    ...overrides,
  };
}

describe('planRunSnapshotModel iteration ledger', () => {
  it('groups nodes, outputs, activity, and carry-over by iteration', () => {
    const first = node({
      id: 'node-1',
      title: 'Land iteration ledger model',
      intent: 'done',
      execution: 'reported',
      current_attempt_id: 'attempt-1',
      workspace_task_id: 'task-1',
      metadata: { iteration_index: 1, commit_ref: 'abc1234' },
      completed_at: '2026-05-01T01:00:00Z',
      evidence_bundle: {
        artifacts: ['artifact.ledger'],
        evidence_refs: ['pytest:unit'],
        changed_files: ['web/src/model.ts'],
        pipeline_refs: ['pipeline:green'],
        verification_summary: 'unit tests passed',
        review_summary: 'accepted',
      },
    });
    const second = node({
      id: 'node-2',
      title: 'Render iteration table',
      intent: 'in_progress',
      execution: 'running',
      current_attempt_id: 'attempt-2',
      metadata: { iteration_index: '2', iteration_phase: 'implement' },
    });
    const snapshot: WorkspacePlanSnapshot = {
      workspace_id: 'ws-1',
      plan: {
        id: 'plan-1',
        workspace_id: 'ws-1',
        goal_id: 'goal-1',
        status: 'active',
        created_at: '2026-05-01T00:00:00Z',
        nodes: [first, second],
        counts: {},
      },
      blackboard: [
        {
          plan_id: 'plan-1',
          key: 'artifact.ledger',
          value: {},
          published_by: 'planner',
          version: 1,
          metadata: {},
        },
      ],
      outbox: [
        outbox({ id: 'outbox-1', payload: { node_id: 'node-2' }, attempt_count: 2 }),
        outbox({
          id: 'outbox-2',
          payload: { node_id: 'node-2' },
          status: 'failed',
          attempt_count: 3,
        }),
      ],
      events: [
        event({ id: 'event-1', node_id: 'node-1', attempt_id: 'attempt-1' }),
        event({
          id: 'event-2',
          node_id: 'node-1',
          event_type: 'verification_completed',
          source: 'workspace_plan_verifier',
        }),
        event({
          id: 'event-3',
          node_id: 'node-2',
          event_type: 'operator_node_reopened',
          source: 'operator',
        }),
      ],
      iteration: {
        current_iteration: 2,
        loop_label: 'Scrum feedback loop',
        cadence: 'research -> plan -> implement -> test -> deploy -> review',
        loop_status: 'active',
        max_iterations: 3,
        completed_iterations: [1],
        current_sprint_goal: 'Render the iteration UI',
        review_summary: 'Current review',
        stop_reason: '',
        active_phase: 'implement',
        active_phase_label: 'Implement',
        next_action: 'Keep going',
        task_count: 1,
        task_budget: 6,
        phases: [],
        deliverables: [],
        feedback_items: [],
        history: [
          {
            iteration_index: 1,
            verdict: 'accepted',
            summary: 'Model landed',
            confidence: 0.9,
            next_sprint_goal: 'Render the iteration UI',
            created_at: '2026-05-01T01:00:00Z',
          },
        ],
        actions: {},
      },
    };

    const runs = buildIterationRuns(snapshot, [
      {
        id: 'task-1',
        workspace_id: 'ws-1',
        title: 'Land model',
        status: 'done',
        metadata: {},
        created_at: '2026-05-01T00:00:00Z',
      },
    ]);

    expect(runs).toHaveLength(2);
    expect(runs[0]).toMatchObject({
      index: 1,
      status: 'completed',
      reviewSummary: 'Model landed',
      counts: { total: 1, done: 1 },
    });
    expect(runs[0].outputs.commitRefs).toEqual(['abc1234']);
    expect(runs[0].outputs.total).toBeGreaterThanOrEqual(5);
    expect(runs[0].interactions).toMatchObject({ worker: 1, verifier: 1, total: 2 });
    expect(runs[0].linkedTasks.map((task) => task.id)).toEqual(['task-1']);
    expect(runs[1]).toMatchObject({
      index: 2,
      status: 'active',
      sprintGoal: 'Render the iteration UI',
      counts: { total: 1, running: 1 },
    });
    expect(runs[1].interactions).toMatchObject({ operator: 1, retries: 3, failed: 1 });
    expect(runs[1].carryoverNodeIds).toEqual(['node-2']);
  });

  it('uses stable fallbacks and keeps failed queue items out of output counts', () => {
    const fallbackNode = node({ id: 'node-fallback', metadata: {}, intent: 'blocked' });
    const failedQueue = outbox({
      payload: { node_id: 'node-fallback' },
      status: 'dead_letter',
      attempt_count: 4,
    });

    expect(iterationNodeIndex(fallbackNode)).toBe(1);
    expect(iterationCarryover([fallbackNode])).toEqual(['node-fallback']);
    expect(iterationOutputs([fallbackNode], [], null).total).toBe(0);
    expect(iterationInteractionStats([], [failedQueue], [fallbackNode])).toMatchObject({
      total: 1,
      retries: 3,
      failed: 1,
    });
  });
});
