import { act } from 'react';

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { TaskBoard } from '@/components/workspace/TaskBoard';
import { workspaceAutonomyService, workspaceTaskService } from '@/services/workspaceService';
import { render, screen, fireEvent } from '@/test/utils';

vi.mock('@/stores/workspace', () => ({
  useWorkspaceTasks: vi.fn(),
  useWorkspaceAgents: vi.fn(),
}));

vi.mock('@/services/workspaceService', () => ({
  workspaceAutonomyService: {
    tick: vi.fn(),
  },
  workspaceTaskService: {
    create: vi.fn(),
    update: vi.fn(),
    assignToAgent: vi.fn(),
    unassignAgent: vi.fn(),
  },
}));

describe('TaskBoard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders workspace tasks and triggers create action', async () => {
    const { useWorkspaceTasks, useWorkspaceAgents } = await import('@/stores/workspace');

    vi.mocked(useWorkspaceTasks).mockReturnValue([
      { id: 'task-1', title: 'Define scope', status: 'todo', workspace_id: 'ws-1' },
      { id: 'task-2', title: 'Ignore me', status: 'todo', workspace_id: 'ws-2' },
    ] as any);
    vi.mocked(useWorkspaceAgents).mockReturnValue([] as any);
    vi.mocked(workspaceTaskService.create).mockResolvedValue({ id: 'task-3' } as any);

    render(<TaskBoard workspaceId="ws-1" />);

    expect(screen.getByText('Define scope')).toBeInTheDocument();
    expect(screen.queryByText('Ignore me')).not.toBeInTheDocument();

    // Open the add form first (hidden by default in kanban view)
    const addButtons = screen.getAllByRole('button', { name: 'workspaceDetail.taskBoard.add' });
    await act(async () => {
      fireEvent.click(addButtons[0]);
    });

    await act(async () => {
      fireEvent.change(screen.getByLabelText('workspaceDetail.taskBoard.taskTitle'), {
        target: { value: 'Build MVP' },
      });
      const submitButtons = screen.getAllByRole('button', { name: 'workspaceDetail.taskBoard.add' });
      fireEvent.click(submitButtons[submitButtons.length - 1]);
    });

    expect(workspaceTaskService.create).toHaveBeenCalledWith('ws-1', { title: 'Build MVP' });
  });

  it('renders root goal health, remediation, and evidence grade badges', async () => {
    const { useWorkspaceTasks, useWorkspaceAgents } = await import('@/stores/workspace');

    vi.mocked(useWorkspaceTasks).mockReturnValue([
      {
        id: 'task-root-1',
        title: 'Prepare rollback checklist',
        status: 'blocked',
        workspace_id: 'ws-1',
        metadata: {
          task_role: 'goal_root',
          goal_health: 'blocked',
          remediation_status: 'replan_required',
          goal_evidence: { verification_grade: 'warn' },
        },
      },
    ] as any);
    vi.mocked(useWorkspaceAgents).mockReturnValue([] as any);

    render(<TaskBoard workspaceId="ws-1" />);

    expect(screen.getByText('Prepare rollback checklist')).toBeInTheDocument();
    expect(screen.getByText(/Root goal/i)).toBeInTheDocument();
    expect(screen.getAllByText(/blocked/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Evidence warn/i)).toBeInTheDocument();
    expect(screen.getByText(/replan required/i)).toBeInTheDocument();
  });

  it('renders pending leader adjudication details for worker-reported tasks', async () => {
    const { useWorkspaceTasks, useWorkspaceAgents } = await import('@/stores/workspace');

    vi.mocked(useWorkspaceTasks).mockReturnValue([
      {
        id: 'task-child-1',
        title: 'Draft checklist',
        status: 'in_progress',
        workspace_id: 'ws-1',
        metadata: {
          pending_leader_adjudication: true,
          last_worker_report_type: 'completed',
          last_worker_report_summary: 'Checklist drafted successfully',
          last_worker_report_artifacts: ['artifact:checklist'],
          last_worker_report_verifications: ['worker_report:completed'],
        },
      },
    ] as any);
    vi.mocked(useWorkspaceAgents).mockReturnValue([] as any);

    render(<TaskBoard workspaceId="ws-1" />);

    expect(screen.getByText(/Pending adjudication/i)).toBeInTheDocument();
    expect(screen.getByText(/workspaceDetail\.taskBoard\.pendingLeaderAdjudication/i)).toBeInTheDocument();
    expect(screen.getByText(/workspaceDetail\.taskBoard\.workerReportType: completed/i)).toBeInTheDocument();
    expect(screen.getByText(/Checklist drafted successfully/i)).toBeInTheDocument();
    expect(screen.getByText(/workspaceDetail\.taskBoard\.reportArtifacts: artifact:checklist/i)).toBeInTheDocument();
    expect(
      screen.getByText(/workspaceDetail\.taskBoard\.reportVerifications: worker_report:completed/i)
    ).toBeInTheDocument();
  });

  it('triggers forced autonomy tick from the task board header', async () => {
    const { useWorkspaceTasks, useWorkspaceAgents } = await import('@/stores/workspace');

    vi.mocked(useWorkspaceTasks).mockReturnValue([] as any);
    vi.mocked(useWorkspaceAgents).mockReturnValue([] as any);
    vi.mocked(workspaceAutonomyService.tick).mockResolvedValue({
      triggered: true,
      root_task_id: 'root-1',
      reason: 'triggered',
    });

    render(<TaskBoard workspaceId="ws-1" />);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'workspaceDetail.taskBoard.forceAutonomy' }));
    });

    expect(workspaceAutonomyService.tick).toHaveBeenCalledWith('ws-1', { force: true });
  });
});
