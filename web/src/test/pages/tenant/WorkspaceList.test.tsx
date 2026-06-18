import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router-dom';

import { act, render, screen, waitFor } from '../../utils';

import { WorkspaceList } from '../../../pages/tenant/WorkspaceList';
// eslint-disable-next-line no-restricted-imports
import { workspacePlanService, workspaceTaskService } from '../../../services/workspaceService';

let projectState: any;
let tenantState: any;
let workspaceState: any;

vi.mock('../../../stores/tenant', () => ({
  useCurrentTenant: () => tenantState.currentTenant,
}));

vi.mock('../../../stores/project', () => ({
  useCurrentProject: () => projectState.currentProject,
  useProjectStore: (selector: (state: any) => unknown) =>
    selector({
      projects: projectState.projects,
      listProjects: projectState.listProjects,
    }),
}));

vi.mock('../../../stores/workspace', () => ({
  useWorkspaces: () => workspaceState.workspaces,
  useWorkspaceLoading: () => workspaceState.isLoading,
  useWorkspaceActions: () => workspaceState.actions,
}));

vi.mock('../../../services/workspaceService', () => ({
  workspaceObjectiveService: {
    list: vi.fn().mockResolvedValue([]),
  },
  workspacePlanService: {
    getSnapshot: vi.fn().mockResolvedValue(null),
  },
  workspaceTaskService: {
    list: vi.fn().mockResolvedValue([]),
  },
}));

describe('WorkspaceList', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    tenantState = {
      currentTenant: { id: 'tenant-1', name: 'Tenant One' },
    };

    projectState = {
      projects: [{ id: 'project-1', name: 'Project One', tenant_id: 'tenant-1' }],
      currentProject: { id: 'project-1', name: 'Project One', tenant_id: 'tenant-1' },
      listProjects: vi.fn().mockResolvedValue(undefined),
    };

    workspaceState = {
      workspaces: [{ id: 'ws-1', name: 'Workspace One' }],
      isLoading: false,
      actions: {
        loadWorkspaces: vi.fn().mockResolvedValue(undefined),
      },
    };
  });

  it('does not load workspaces from a stale project outside the active tenant', async () => {
    projectState.projects = [{ id: 'project-stale', name: 'Stale Project', tenant_id: 'tenant-2' }];
    projectState.currentProject = {
      id: 'project-stale',
      name: 'Stale Project',
      tenant_id: 'tenant-2',
    };

    render(
      <Routes>
        <Route path="/tenant/:tenantId/workspaces" element={<WorkspaceList />} />
      </Routes>,
      { route: '/tenant/tenant-1/workspaces' }
    );

    expect(await screen.findByText('Pick a tenant and project')).toBeInTheDocument();
    await waitFor(() => {
      expect(projectState.listProjects).toHaveBeenCalledWith('tenant-1');
    });
    expect(workspaceState.actions.loadWorkspaces).not.toHaveBeenCalled();
  });

  it('loads and renders workspaces using store tenant/project context', async () => {
    render(
      <Routes>
        <Route path="/tenant/workspaces" element={<WorkspaceList />} />
      </Routes>,
      { route: '/tenant/workspaces' }
    );

    await waitFor(() => {
      expect(workspaceState.actions.loadWorkspaces).toHaveBeenCalledWith('tenant-1', 'project-1');
    });

    expect(screen.getByRole('heading', { name: 'Workspaces' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Workspace One/i })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/project/project-1/blackboard?workspaceId=ws-1'
    );
    expect(screen.getByRole('link', { name: /Create Workspace/i })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/project/project-1/workspaces/new'
    );
  });

  it('keeps long code roots constrained inside workspace cards', async () => {
    const longCodeRoot =
      '/workspace/8800f9fc-484e-4bb5-8151-8e1a213dd0b2/some/really/long/project/path';
    workspaceState.workspaces = [
      {
        id: 'ws-long-root',
        name: 'Workspace With Long Code Root',
        description:
          'A workspace with a long description and an even longer sandbox path that should not stretch the card grid.',
        metadata: {
          workspace_use_case: 'programming',
          collaboration_mode: 'autonomous',
          sandbox_code_root: longCodeRoot,
        },
        created_at: '2026-04-29T00:00:00Z',
      },
    ];

    render(
      <Routes>
        <Route path="/tenant/workspaces" element={<WorkspaceList />} />
      </Routes>,
      { route: '/tenant/workspaces' }
    );

    await waitFor(() => {
      expect(workspaceState.actions.loadWorkspaces).toHaveBeenCalledWith('tenant-1', 'project-1');
    });

    const card = screen.getByRole('link', { name: 'Workspace With Long Code Root' });
    const codeRootTag = screen.getByText(longCodeRoot);

    expect(card).toHaveClass('min-w-0', 'overflow-hidden');
    expect(codeRootTag).toHaveClass('min-w-0', 'max-w-full', 'truncate');
    expect(codeRootTag).toHaveAttribute('title', longCodeRoot);
  });

  it('uses current plan nodes for workspace card task counts before task projections', async () => {
    vi.mocked(workspacePlanService.getSnapshot).mockResolvedValueOnce({
      workspace_id: 'ws-1',
      plan: {
        id: 'plan-1',
        workspace_id: 'ws-1',
        goal_id: 'goal-1',
        status: 'active',
        created_at: '2026-05-01T00:00:00Z',
        counts: {},
        nodes: Array.from({ length: 52 }, (_, index) => ({
          id: `node-${String(index + 1)}`,
          parent_id: index === 51 ? null : 'goal-1',
          kind: index === 51 ? 'goal' : 'task',
          title: `Plan node ${String(index + 1)}`,
          description: '',
          depends_on: [],
          acceptance_criteria: [],
          recommended_capabilities: [],
          intent: index === 51 ? 'todo' : 'done',
          execution: index === 51 ? 'idle' : 'completed',
          progress: { percent: index === 51 ? 0 : 100, confidence: 1, note: '' },
          assignee_agent_id: null,
          current_attempt_id: null,
          workspace_task_id: index === 51 ? null : `task-${String(index + 1)}`,
          priority: index,
          metadata: {},
          created_at: '2026-05-01T00:00:00Z',
        })),
      },
      root_goal: {
        id: 'goal-1',
        workspace_id: 'ws-1',
        title: 'Root goal',
        status: 'done',
        created_at: '2026-05-01T00:00:00Z',
        updated_at: '2026-05-01T00:00:00Z',
      },
      blackboard: [],
      outbox: [],
      events: [],
    } as any);
    vi.mocked(workspaceTaskService.list).mockResolvedValueOnce(
      Array.from({ length: 69 }, (_, index) => ({
        id: `historical-task-${String(index + 1)}`,
        workspace_id: 'ws-1',
        title: `Historical task ${String(index + 1)}`,
        description: '',
        status: index < 65 ? 'done' : 'in_progress',
        priority: '',
        metadata: {},
        created_at: '2026-05-01T00:00:00Z',
      })) as any
    );

    render(
      <Routes>
        <Route path="/tenant/workspaces" element={<WorkspaceList />} />
      </Routes>,
      { route: '/tenant/workspaces' }
    );

    expect(await screen.findByText('52 tasks')).toBeInTheDocument();
    expect(screen.getByText('100%')).toBeInTheDocument();
    expect(screen.getByText('52 of 52 complete')).toBeInTheDocument();
    expect(screen.queryByText('69 tasks')).not.toBeInTheDocument();
    expect(workspacePlanService.getSnapshot).toHaveBeenCalledWith('ws-1', {
      outboxLimit: 0,
      eventLimit: 0,
      includeDetails: false,
      recoverStaleAttempts: false,
    });
    expect(workspaceTaskService.list).not.toHaveBeenCalled();
  });

  it('loads workspace summaries in bounded batches', async () => {
    workspaceState.workspaces = Array.from({ length: 8 }, (_, index) => ({
      id: `ws-${String(index + 1)}`,
      name: `Workspace ${String(index + 1)}`,
      description: 'Workspace description',
      created_at: '2026-05-01T00:00:00Z',
    }));

    const planResolvers: Array<(value: null) => void> = [];
    vi.mocked(workspacePlanService.getSnapshot).mockImplementation(
      () =>
        new Promise((resolve) => {
          planResolvers.push(resolve);
        })
    );
    vi.mocked(workspaceTaskService.list).mockResolvedValue([]);

    render(
      <Routes>
        <Route path="/tenant/workspaces" element={<WorkspaceList />} />
      </Routes>,
      { route: '/tenant/workspaces' }
    );

    await waitFor(() => {
      expect(workspacePlanService.getSnapshot).toHaveBeenCalledTimes(6);
    });
    expect(workspaceTaskService.list).not.toHaveBeenCalled();

    await act(async () => {
      for (const resolve of planResolvers.splice(0)) {
        resolve(null);
      }
    });

    await waitFor(() => {
      expect(workspacePlanService.getSnapshot).toHaveBeenCalledTimes(8);
    });
  });
});
