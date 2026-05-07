import { act, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { GoalsTab } from '@/components/blackboard/tabs/GoalsTab';
import { render, screen } from '@/test/utils';

vi.mock('@/components/workspace/objectives/ObjectiveList', () => ({
  ObjectiveList: () => <div>Objective list</div>,
}));

vi.mock('@/components/workspace/TaskBoard', () => ({
  TaskBoard: ({ showAutonomyAction }: { showAutonomyAction?: boolean }) => (
    <div data-testid="task-board" data-show-autonomy-action={String(showAutonomyAction)}>
      Task board
    </div>
  ),
}));

describe('GoalsTab', () => {
  it('shows pending orchestration feedback before a root task exists', () => {
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
        tasks={[]}
        agents={[]}
        completionRatio={0}
        workspaceId="ws-1"
        onDeleteObjective={vi.fn()}
        onProjectObjective={vi.fn()}
        onCreateObjective={vi.fn()}
      />
    );

    expect(screen.getByText('blackboard.executionFeedback.title')).toBeInTheDocument();
    expect(screen.getByText('blackboard.executionFeedback.stage.waitingRoot')).toBeInTheDocument();
    expect(screen.getByText('blackboard.executionFeedback.helper.waitingRoot')).toBeInTheDocument();
    expect(screen.getByText('blackboard.executionFeedback.timeline.objective')).toBeInTheDocument();
    expect(screen.getByText('blackboard.executionFeedback.timeline.root')).toBeInTheDocument();
    expect(screen.getByText('blackboard.executionFeedback.eventLogTitle')).toBeInTheDocument();
    expect(screen.getByTestId('task-board')).toHaveAttribute('data-show-autonomy-action', 'false');
    const boundaryBadge = screen
      .getByText('blackboard.executionFeedbackSurfaceHint')
      .closest('div');
    expect(boundaryBadge).toHaveAttribute('data-blackboard-boundary', 'hosted');
    expect(boundaryBadge).toHaveAttribute('data-blackboard-authority', 'non-authoritative');
  });

  it('shows live child-task execution counts once orchestration is underway', async () => {
    vi.useFakeTimers();
    const scrollIntoView = vi.fn();
    const clipboardWriteText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue();
    const taskBoardTarget = document.createElement('article');
    taskBoardTarget.id = 'workspace-task-child-2';
    taskBoardTarget.scrollIntoView = scrollIntoView;
    document.body.appendChild(taskBoardTarget);

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
              updated_at: '2026-04-17T05:02:00Z',
              metadata: {
                task_role: 'goal_root',
                objective_id: 'objective-1',
                goal_progress_summary:
                  '1/2 child tasks done; 1 in progress; 0 blocked; 2/2 assigned',
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
            {
              id: 'child-2',
              workspace_id: 'ws-1',
              title: 'Run collaboration test',
              status: 'in_progress',
              assignee_agent_id: 'worker-b',
              workspace_agent_id: 'binding-b',
              created_at: '2026-04-17T05:00:30Z',
              updated_at: '2026-04-17T05:02:30Z',
              metadata: {
                task_role: 'execution_task',
                root_goal_task_id: 'root-1',
              },
            },
          ] as never
        }
        agents={
          [
            { id: 'binding-a', agent_id: 'worker-a', display_name: 'Worker A' },
            { id: 'binding-b', agent_id: 'worker-b', display_name: 'Worker B' },
          ] as never
        }
        completionRatio={0.5}
        workspaceId="ws-1"
        onDeleteObjective={vi.fn()}
        onProjectObjective={vi.fn()}
        onCreateObjective={vi.fn()}
      />
    );

    expect(screen.getByText('blackboard.executionFeedback.stage.running')).toBeInTheDocument();
    expect(screen.getByText('blackboard.executionFeedback.helper.running')).toBeInTheDocument();
    expect(screen.getByText(/root: in_progress/i)).toBeInTheDocument();
    expect(screen.getByText(/assigned 2/i)).toBeInTheDocument();
    expect(screen.getByText(/running 1/i)).toBeInTheDocument();
    expect(screen.getByText(/done 1/i)).toBeInTheDocument();
    expect(screen.getByText(/1\/2 child tasks done; 1 in progress/i)).toBeInTheDocument();
    expect(screen.getByText('blackboard.executionFeedback.timeline.children')).toBeInTheDocument();
    expect(
      screen.getByText('blackboard.executionFeedback.timeline.assignment')
    ).toBeInTheDocument();
    expect(
      screen.getByText('blackboard.executionFeedback.timeline.executionProgress')
    ).toBeInTheDocument();
    expect(screen.getByText('blackboard.executionFeedback.events.rootCreated')).toBeInTheDocument();
    expect(
      screen.getByText('blackboard.executionFeedback.events.childrenCreated')
    ).toBeInTheDocument();
    expect(screen.getByText('blackboard.executionFeedback.events.assigned')).toBeInTheDocument();
    expect(screen.getByText('blackboard.executionFeedback.events.running')).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(
        screen.getByRole('button', {
          name: /blackboard\.executionFeedback\.controls\.expandLog/i,
        })
      );
    });

    expect(screen.getByText('Create fixture')).toBeInTheDocument();
    expect(screen.getByText('Run collaboration test')).toBeInTheDocument();
    expect(
      screen.getAllByText('blackboard.executionFeedback.events.latest').length
    ).toBeGreaterThan(0);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /create fixture/i }));
    });
    expect(
      screen.getAllByText('blackboard.executionFeedback.events.latest').length
    ).toBeGreaterThan(0);
    await act(async () => {
      fireEvent.click(
        screen.getByRole('button', {
          name: 'blackboard.executionFeedback.controls.viewAll',
        })
      );
    });
    expect(
      screen.getAllByText('blackboard.executionFeedback.events.latest').length
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText('blackboard.executionFeedback.child.created').length
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText('blackboard.executionFeedback.child.assignedTo').length
    ).toBeGreaterThan(0);
    await act(async () => {
      fireEvent.click(
        screen.getAllByRole('button', {
          name: /blackboard\.executionFeedback\.controls\.copySnapshot/i,
        })[0]
      );
    });
    expect(clipboardWriteText).toHaveBeenCalled();
    expect(clipboardWriteText.mock.calls[0]?.[0]).toContain('task_id: child-1');
    expect(clipboardWriteText.mock.calls[0]?.[0]).toContain('assignee: Worker A');
    expect(clipboardWriteText.mock.calls[0]?.[0]).toContain('status: done');
    expect(screen.getByText('blackboard.executionFeedback.controls.copied')).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(
        screen.getAllByRole('button', {
          name: /blackboard\.executionFeedback\.controls\.jumpToTaskBoard/i,
        })[1]
      );
    });
    expect(scrollIntoView).toHaveBeenCalled();
    expect(taskBoardTarget.className).toContain('ring-2');
    await act(async () => {
      vi.runAllTimers();
    });
    expect(taskBoardTarget.className).not.toContain('ring-2');

    taskBoardTarget.remove();
    clipboardWriteText.mockRestore();
    vi.useRealTimers();
  });

  it('surfaces pending adjudication summary in child task logs', async () => {
    render(
      <GoalsTab
        objectives={[
          {
            id: 'objective-2',
            workspace_id: 'ws-1',
            title: 'Close review loop',
            obj_type: 'objective',
            progress: 0,
            created_at: '2026-04-17T05:00:00Z',
          },
        ]}
        tasks={
          [
            {
              id: 'root-2',
              workspace_id: 'ws-1',
              title: 'Close review loop',
              status: 'in_progress',
              created_at: '2026-04-17T05:00:10Z',
              metadata: {
                task_role: 'goal_root',
                objective_id: 'objective-2',
              },
            },
            {
              id: 'child-9',
              workspace_id: 'ws-1',
              title: 'Summarize review findings',
              status: 'done',
              assignee_agent_id: 'worker-z',
              workspace_agent_id: 'binding-z',
              current_attempt_number: 4,
              current_attempt_conversation_id: 'conv-9',
              current_attempt_worker_binding_id: 'binding-z',
              pending_leader_adjudication: true,
              last_worker_report_type: 'needs_review',
              created_at: '2026-04-17T05:00:20Z',
              updated_at: '2026-04-17T05:03:20Z',
              completed_at: '2026-04-17T05:03:20Z',
              metadata: {
                task_role: 'execution_task',
                root_goal_task_id: 'root-2',
              },
            },
          ] as never
        }
        agents={[{ id: 'binding-z', agent_id: 'worker-z', display_name: 'Worker Z' }] as never}
        completionRatio={1}
        workspaceId="ws-1"
        tenantId="t-1"
        projectId="p-1"
        onDeleteObjective={vi.fn()}
        onProjectObjective={vi.fn()}
        onCreateObjective={vi.fn()}
      />
    );

    await act(async () => {
      fireEvent.click(
        screen.getByRole('button', {
          name: /blackboard\.executionFeedback\.controls\.expandLog/i,
        })
      );
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /summarize review findings/i }));
    });

    expect(
      screen.getByText(/blackboard\.executionFeedback\.child\.pendingAdjudication · needs review/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/blackboard\.executionFeedback\.controls\.jumpToConversation #4/i)
    ).toBeInTheDocument();
  });
});
