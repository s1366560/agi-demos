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
});
