import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router-dom';

import { render, screen, waitFor } from '../../utils';

import { WorkspaceList } from '../../../pages/tenant/WorkspaceList';

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
      projects: [{ id: 'project-1', name: 'Project One' }],
      currentProject: { id: 'project-1', name: 'Project One' },
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
});
