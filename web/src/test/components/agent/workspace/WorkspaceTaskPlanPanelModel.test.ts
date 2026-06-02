import { describe, expect, it } from 'vitest';

import {
  buildWorkspaceTaskPlanIterationGroups,
  buildWorkspaceTaskPlanRows,
} from '@/components/agent/workspace/WorkspaceTaskPlanPanelModel';

import type { WorkspacePlanNode, WorkspacePlanSnapshot, WorkspaceTask } from '@/types/workspace';

function planNode(overrides: Partial<WorkspacePlanNode>): WorkspacePlanNode {
  return {
    id: 'node-1',
    parent_id: null,
    kind: 'task',
    title: 'Plan task',
    description: '',
    depends_on: [],
    acceptance_criteria: [],
    recommended_capabilities: [],
    intent: 'todo',
    execution: 'idle',
    progress: { percent: 0, confidence: 1, note: '' },
    assignee_agent_id: null,
    current_attempt_id: null,
    workspace_task_id: null,
    priority: 1,
    metadata: {},
    created_at: '2026-05-23T00:00:00Z',
    ...overrides,
  };
}

function snapshot(nodes: WorkspacePlanNode[]): WorkspacePlanSnapshot {
  return {
    workspace_id: 'workspace-1',
    plan: {
      id: 'plan-1',
      workspace_id: 'workspace-1',
      goal_id: 'goal-1',
      status: 'active',
      created_at: '2026-05-23T00:00:00Z',
      nodes,
      counts: {},
    },
    blackboard: [],
    outbox: [],
    events: [],
  };
}

function workspaceTask(overrides: Partial<WorkspaceTask>): WorkspaceTask {
  return {
    id: 'task-1',
    workspace_id: 'workspace-1',
    title: 'Task title',
    description: '',
    status: 'in_progress',
    priority: '',
    metadata: {},
    created_at: '2026-05-23T00:00:00Z',
    ...overrides,
  };
}

describe('buildWorkspaceTaskPlanRows', () => {
  it('handles plan nodes missing optional runtime fields without losing stable order', () => {
    const rows = buildWorkspaceTaskPlanRows(
      [],
      snapshot([
        planNode({
          id: 'node-a-without-runtime-fields',
          title: 'A missing runtime fields',
          progress: undefined,
          priority: undefined,
        } as Partial<WorkspacePlanNode>),
        planNode({
          id: 'node-b-without-priority',
          title: 'B missing priority',
          priority: undefined,
          progress: { percent: 42, confidence: 1, note: 'running' },
        } as Partial<WorkspacePlanNode>),
      ]),
      null
    );

    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({
      entityId: 'node-a-without-runtime-fields',
      progressPercent: undefined,
      order: 0,
    });
    expect(rows[1]).toMatchObject({
      entityId: 'node-b-without-priority',
      progressPercent: 42,
      iterationIndex: null,
      order: 1,
    });
  });

  it('uses the linked plan node as the canonical runtime status for plan rows', () => {
    const rows = buildWorkspaceTaskPlanRows(
      [
        workspaceTask({
          id: 'task-done-in-plan',
          status: 'in_progress',
          current_attempt_id: 'stale-task-attempt',
        }),
      ],
      snapshot([
        planNode({
          id: 'node-done',
          title: 'Done in plan',
          intent: 'done',
          execution: 'idle',
          workspace_task_id: 'task-done-in-plan',
          current_attempt_id: 'canonical-plan-attempt',
          progress: { percent: 100, confidence: 1, note: 'accepted' },
        }),
      ]),
      'task-done-in-plan'
    );

    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      entityId: 'node-done',
      status: 'done',
      attemptId: 'canonical-plan-attempt',
      progressPercent: 100,
      source: 'plan',
      isCurrent: true,
      iterationIndex: null,
    });
  });

  it('does not render stale workspace task projections when a plan snapshot is present', () => {
    const rows = buildWorkspaceTaskPlanRows(
      [
        workspaceTask({
          id: 'stale-running-task',
          title: 'Stale running task',
          status: 'in_progress',
        }),
        workspaceTask({
          id: 'current-plan-task',
          title: 'Projected title',
          status: 'in_progress',
        }),
      ],
      snapshot([
        planNode({
          id: 'current-plan-node',
          title: 'Current plan title',
          intent: 'done',
          execution: 'idle',
          workspace_task_id: 'current-plan-task',
          progress: { percent: 100, confidence: 1, note: 'accepted' },
        }),
      ]),
      null
    );

    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      entityId: 'current-plan-node',
      title: 'Current plan title',
      status: 'done',
      source: 'plan',
    });
    expect(rows.some((row) => row.title === 'Stale running task')).toBe(false);
  });

  it('preserves plan-node iteration metadata and groups rows by iteration before status', () => {
    const rows = buildWorkspaceTaskPlanRows(
      [],
      snapshot([
        planNode({
          id: 'iteration-2-done',
          title: 'Second iteration done',
          intent: 'done',
          priority: 1,
          metadata: { iteration_index: 2 },
        }),
        planNode({
          id: 'iteration-1-todo',
          title: 'First iteration todo',
          intent: 'todo',
          priority: 2,
          metadata: { iteration_index: '1' },
        }),
        planNode({
          id: 'iteration-1-running',
          title: 'First iteration running',
          intent: 'in_progress',
          priority: 1,
          metadata: { iteration_index: 1 },
        }),
      ]),
      null
    );

    expect(rows.map((row) => row.entityId)).toEqual([
      'iteration-1-running',
      'iteration-1-todo',
      'iteration-2-done',
    ]);

    const groups = buildWorkspaceTaskPlanIterationGroups(rows);
    expect(groups).toEqual([
      {
        id: 'iteration:1',
        iterationIndex: 1,
        rows: [rows[0], rows[1]],
      },
      {
        id: 'iteration:2',
        iterationIndex: 2,
        rows: [rows[2]],
      },
    ]);
  });

  it('places task-only rows without iteration metadata in an unassigned group', () => {
    const rows = buildWorkspaceTaskPlanRows(
      [
        workspaceTask({
          id: 'task-with-iteration',
          title: 'Task with iteration',
          status: 'done',
          metadata: { iteration_index: 3 },
        }),
        workspaceTask({
          id: 'task-without-iteration',
          title: 'Task without iteration',
          status: 'todo',
        }),
      ],
      null,
      null
    );

    const groups = buildWorkspaceTaskPlanIterationGroups(rows);

    expect(groups.map((group) => group.id)).toEqual(['iteration:3', 'iteration:unassigned']);
    expect(groups[0].rows[0]).toMatchObject({
      entityId: 'task-with-iteration',
      iterationIndex: 3,
    });
    expect(groups[1].rows[0]).toMatchObject({
      entityId: 'task-without-iteration',
      iterationIndex: null,
    });
  });
});
