import { describe, expect, it, vi } from 'vitest';

import { GoalsTab } from '@/components/blackboard/tabs/GoalsTab';
import { render, screen } from '@/test/utils';

vi.mock('@/components/workspace/objectives/ObjectiveList', () => ({
  ObjectiveList: () => <div>Objective list</div>,
}));

vi.mock('@/components/workspace/TaskBoard', () => ({
  TaskBoard: ({
    showAutonomyAction,
    tasks,
  }: {
    showAutonomyAction?: boolean;
    tasks: Array<{ status: string }>;
  }) => (
    <div
      data-testid="task-board"
      data-show-autonomy-action={String(showAutonomyAction)}
      data-task-count={String(tasks.length)}
      data-task-statuses={tasks.map((task) => task.status).join(',')}
    >
      Task board
    </div>
  ),
}));

describe('GoalsTab', () => {
  it('omits the orchestration feedback projection from the goals tab', () => {
    render(
      <GoalsTab
        objectives={[
          {
            id: 'objective-1',
            workspace_id: 'ws-1',
            title: 'Ship agent collaboration flow',
            obj_type: 'objective',
            progress: 0,
            created_at: '2026-04-17T05:00:00Z',
          },
        ]}
        tasks={
          [
            {
              id: 'root-1',
              workspace_id: 'ws-1',
              title: 'Ship agent collaboration flow',
              status: 'in_progress',
              created_at: '2026-04-17T05:00:10Z',
              metadata: {
                task_role: 'goal_root',
                objective_id: 'objective-1',
              },
            },
            {
              id: 'child-1',
              workspace_id: 'ws-1',
              title: 'Create fixture',
              status: 'done',
              assignee_agent_id: 'worker-a',
              workspace_agent_id: 'binding-a',
              created_at: '2026-04-17T05:00:20Z',
              updated_at: '2026-04-17T05:01:20Z',
              completed_at: '2026-04-17T05:01:20Z',
              metadata: {
                task_role: 'execution_task',
                root_goal_task_id: 'root-1',
              },
            },
          ] as never
        }
        agents={[{ id: 'binding-a', agent_id: 'worker-a', display_name: 'Worker A' }] as never}
        completionRatio={0.5}
        workspaceId="ws-1"
        tenantId="t-1"
        projectId="p-1"
        onDeleteObjective={vi.fn()}
        onProjectObjective={vi.fn()}
        onCreateObjective={vi.fn()}
      />
    );

    expect(screen.getByText('Objective list')).toBeInTheDocument();
    expect(screen.getByTestId('task-board')).toHaveAttribute('data-show-autonomy-action', 'false');
    expect(screen.queryByText('blackboard.executionFeedback.title')).not.toBeInTheDocument();
    expect(screen.queryByText('blackboard.executionFeedbackSurfaceHint')).not.toBeInTheDocument();
  });

  it('passes current plan nodes to the task board when a plan snapshot is available', () => {
    render(
      <GoalsTab
        objectives={[]}
        tasks={
          [
            { id: 'old-1', workspace_id: 'ws-1', title: 'Old done', status: 'done', metadata: {} },
            {
              id: 'old-2',
              workspace_id: 'ws-1',
              title: 'Old running',
              status: 'in_progress',
              metadata: {},
            },
            {
              id: 'old-3',
              workspace_id: 'ws-1',
              title: 'Extra running',
              status: 'in_progress',
              metadata: {},
            },
          ] as never
        }
        agents={[]}
        completionRatio={1}
        workspaceId="ws-1"
        plan={
          {
            id: 'plan-current',
            workspace_id: 'ws-1',
            goal_id: 'goal-current',
            status: 'active',
            created_at: '2026-04-17T05:00:00Z',
            counts: {},
            nodes: [
              {
                id: 'node-root',
                parent_id: null,
                kind: 'goal',
                title: 'Root',
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
                priority: 0,
                metadata: {},
                created_at: '2026-04-17T05:00:00Z',
              },
              ...Array.from({ length: 51 }, (_, index) => ({
                id: `node-${String(index)}`,
                parent_id: 'node-root',
                kind: 'task' as const,
                title: `Task ${String(index)}`,
                description: '',
                depends_on: [],
                acceptance_criteria: [],
                recommended_capabilities: [],
                intent: 'done' as const,
                execution: 'idle' as const,
                progress: { percent: 100, confidence: 1, note: '' },
                assignee_agent_id: null,
                current_attempt_id: null,
                workspace_task_id: `task-${String(index)}`,
                priority: index + 1,
                metadata: {},
                created_at: '2026-04-17T05:00:00Z',
              })),
            ],
          } as never
        }
        rootGoal={{ id: 'root-task', title: 'Root', status: 'done' } as never}
        onDeleteObjective={vi.fn()}
        onProjectObjective={vi.fn()}
        onCreateObjective={vi.fn()}
      />
    );

    expect(screen.getByTestId('task-board')).toHaveAttribute('data-task-count', '52');
    expect(screen.getByTestId('task-board')).toHaveAttribute(
      'data-task-statuses',
      Array.from({ length: 52 }, () => 'done').join(',')
    );
  });
});
