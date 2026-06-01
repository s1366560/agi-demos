import { describe, expect, it } from 'vitest';

import { buildWorkspaceTaskPlanRows } from '@/components/agent/workspace/WorkspaceTaskPlanPanelModel';

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
      order: 1,
    });
  });

  it('uses the linked plan node as the canonical runtime status for task rows', () => {
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
      null
    );

    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      entityId: 'task-done-in-plan',
      status: 'done',
      attemptId: 'canonical-plan-attempt',
      progressPercent: 100,
    });
  });
});
