import { describe, expect, it } from 'vitest';

import {
  buildWorkspaceExecutionDag,
  resolveWorkspaceAgentLabel,
  workspaceDagDimmedNodeIds,
} from '@/components/executionDag/workspaceExecutionDagModel';

import type { WorkspaceAgent, WorkspacePlanNode, WorkspacePlanSnapshot } from '@/types/workspace';

function node(overrides: Partial<WorkspacePlanNode>): WorkspacePlanNode {
  return {
    id: 'node-1',
    parent_id: 'goal-1',
    kind: 'task',
    title: 'Implement graph',
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

function snapshot(nodes: WorkspacePlanNode[]): WorkspacePlanSnapshot {
  return {
    workspace_id: 'ws-1',
    plan: {
      id: 'plan-1',
      workspace_id: 'ws-1',
      goal_id: 'goal-1',
      status: 'active',
      created_at: '2026-05-01T00:00:00Z',
      nodes,
      counts: {},
    },
    blackboard: [],
    outbox: [],
    events: [],
  };
}

const agents: WorkspaceAgent[] = [
  {
    id: 'binding-1',
    workspace_id: 'ws-1',
    agent_id: 'agent-1',
    display_name: 'Implementer',
    is_active: true,
    created_at: '2026-05-01T00:00:00Z',
  },
];

describe('workspaceExecutionDagModel', () => {
  it('uses a synthetic root when the backend root goal is absent', () => {
    const model = buildWorkspaceExecutionDag(
      snapshot([node({ id: 'task-1', title: 'Build projection' })]),
      agents
    );

    expect(model?.rootId).toBe('root:plan-1');
    expect(model?.nodes[0]).toMatchObject({
      id: 'root:plan-1',
      kind: 'root',
      title: 'Build projection',
    });
    expect(model?.edges).toContainEqual({
      id: 'hierarchy:root:plan-1:task-1',
      sourceId: 'root:plan-1',
      targetId: 'task-1',
      kind: 'hierarchy',
    });
  });

  it('keeps explicit dependencies as solid dependency edges', () => {
    const model = buildWorkspaceExecutionDag(
      snapshot([
        node({ id: 'task-a', title: 'Plan API' }),
        node({ id: 'task-b', title: 'Render graph', depends_on: ['task-a'] }),
      ]),
      agents
    );

    expect(model?.edges).toContainEqual({
      id: 'dependency:task-a:task-b',
      sourceId: 'task-a',
      targetId: 'task-b',
      kind: 'dependency',
    });
  });

  it('resolves workspace agent labels by binding id or agent id', () => {
    expect(resolveWorkspaceAgentLabel('binding-1', agents)).toBe('Implementer');
    expect(resolveWorkspaceAgentLabel('agent-1', agents)).toBe('Implementer');
    expect(resolveWorkspaceAgentLabel('agent-x', agents)).toBe('agent-x');
  });

  it('carries workspace task linkage for current-session highlighting', () => {
    const model = buildWorkspaceExecutionDag(
      snapshot([
        node({
          id: 'task-a',
          title: 'Run workspace task',
          workspace_task_id: 'workspace-task-1',
        }),
      ]),
      agents
    );

    expect(model?.nodes.find((item) => item.id === 'task-a')).toMatchObject({
      workspaceTaskId: 'workspace-task-1',
    });
  });

  it('dims filtered nodes while preserving graph topology', () => {
    const planSnapshot = snapshot([
      node({ id: 'task-a', title: 'Research graph model', intent: 'done' }),
      node({
        id: 'task-b',
        title: 'Implement renderer',
        intent: 'in_progress',
        execution: 'running',
      }),
    ]);
    const model = buildWorkspaceExecutionDag(planSnapshot, agents);

    const dimmed = workspaceDagDimmedNodeIds(model, planSnapshot, 'running', 'renderer');

    expect(dimmed.has('task-a')).toBe(true);
    expect(dimmed.has('task-b')).toBe(false);
    expect(dimmed.has(model?.rootId ?? '')).toBe(false);
  });
});
