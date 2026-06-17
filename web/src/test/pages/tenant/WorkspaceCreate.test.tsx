import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router-dom';

import { act, fireEvent, render, screen, waitFor } from '../../utils';

import { WorkspaceCreate } from '../../../pages/tenant/WorkspaceCreate';
import { ApiError, ApiErrorType } from '../../../services/client/ApiError';

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
  useWorkspaceActions: () => workspaceState.actions,
}));

describe('WorkspaceCreate', () => {
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
      actions: {
        createWorkspace: vi.fn().mockResolvedValue({ id: 'ws-created', name: 'My Evo delivery' }),
      },
    };
  });

  it('does not create a workspace from a stale project outside the active tenant', async () => {
    projectState.projects = [{ id: 'project-stale', name: 'Stale Project', tenant_id: 'tenant-2' }];
    projectState.currentProject = {
      id: 'project-stale',
      name: 'Stale Project',
      tenant_id: 'tenant-2',
    };

    render(
      <Routes>
        <Route path="/tenant/:tenantId/workspaces/new" element={<WorkspaceCreate />} />
      </Routes>,
      { route: '/tenant/tenant-1/workspaces/new' }
    );

    expect(await screen.findByText('Pick a tenant and project')).toBeInTheDocument();
    await waitFor(() => {
      expect(projectState.listProjects).toHaveBeenCalledWith('tenant-1');
    });
    expect(screen.queryByRole('button', { name: /Create Workspace/i })).not.toBeInTheDocument();
    expect(workspaceState.actions.createWorkspace).not.toHaveBeenCalled();
  });

  it('creates programming workspaces without source control or Drone setup', async () => {
    render(
      <Routes>
        <Route
          path="/tenant/:tenantId/project/:projectId/workspaces/new"
          element={<WorkspaceCreate />}
        />
        <Route
          path="/tenant/:tenantId/project/:projectId/blackboard"
          element={<div>Blackboard destination</div>}
        />
      </Routes>,
      { route: '/tenant/tenant-1/project/project-1/workspaces/new' }
    );

    await act(async () => {
      fireEvent.change(screen.getByLabelText('Workspace name'), {
        target: { value: 'My Evo delivery' },
      });
      fireEvent.change(screen.getByLabelText('Objective'), {
        target: { value: 'Ship the My Evo workspace automation plan' },
      });
      fireEvent.click(screen.getByText('Programming'));
      fireEvent.click(screen.getByText('Autonomous'));
    });

    await waitFor(() => {
      expect(screen.getByLabelText('Sandbox code root')).toBeInTheDocument();
    });
    expect(screen.queryByText('Source control')).not.toBeInTheDocument();
    expect(screen.queryByText('Drone environment')).not.toBeInTheDocument();

    await act(async () => {
      fireEvent.change(screen.getByLabelText('Sandbox code root'), {
        target: { value: '/workspace/my-evo' },
      });
      fireEvent.click(screen.getByRole('button', { name: /Create Workspace/i }));
    });

    await waitFor(() => {
      expect(workspaceState.actions.createWorkspace).toHaveBeenCalledWith('tenant-1', 'project-1', {
        name: 'My Evo delivery',
        description: 'Ship the My Evo workspace automation plan',
        use_case: 'programming',
        collaboration_mode: 'autonomous',
        sandbox_code_root: '/workspace/my-evo',
        metadata: {
          workspace_use_case: 'programming',
          workspace_type: 'software_development',
          collaboration_mode: 'autonomous',
          agent_conversation_mode: 'autonomous',
          autonomy_profile: { workspace_type: 'software_development' },
          sandbox_code_root: '/workspace/my-evo',
          code_context: { sandbox_code_root: '/workspace/my-evo' },
        },
      });
    });
    expect(await screen.findByText('Blackboard destination')).toBeInTheDocument();
  });

  it('requires the creation brief before creating a workspace', async () => {
    render(
      <Routes>
        <Route
          path="/tenant/:tenantId/project/:projectId/workspaces/new"
          element={<WorkspaceCreate />}
        />
      </Routes>,
      { route: '/tenant/tenant-1/project/project-1/workspaces/new' }
    );

    await act(async () => {
      fireEvent.change(screen.getByLabelText('Workspace name'), {
        target: { value: 'Name only' },
      });
    });

    expect(screen.getByRole('button', { name: /Create Workspace/i })).toBeDisabled();
    expect(workspaceState.actions.createWorkspace).not.toHaveBeenCalled();
  });

  it('shows a duplicate-name message when the API returns a conflict', async () => {
    workspaceState.actions.createWorkspace = vi
      .fn()
      .mockRejectedValue(
        new ApiError(ApiErrorType.CONFLICT, 'CONFLICT', 'Workspace already exists', 409)
      );

    render(
      <Routes>
        <Route
          path="/tenant/:tenantId/project/:projectId/workspaces/new"
          element={<WorkspaceCreate />}
        />
      </Routes>,
      { route: '/tenant/tenant-1/project/project-1/workspaces/new' }
    );

    await act(async () => {
      fireEvent.change(screen.getByLabelText('Workspace name'), {
        target: { value: 'My Evo delivery' },
      });
      fireEvent.change(screen.getByLabelText('Objective'), {
        target: { value: 'Ship the My Evo workspace automation plan' },
      });
      fireEvent.click(screen.getByText('Programming'));
      fireEvent.click(screen.getByText('Autonomous'));
    });

    await act(async () => {
      fireEvent.change(screen.getByLabelText('Sandbox code root'), {
        target: { value: '/workspace/my-evo' },
      });
      fireEvent.click(screen.getByRole('button', { name: /Create Workspace/i }));
    });

    expect(
      await screen.findByText('A workspace with this name already exists.')
    ).toBeInTheDocument();
  });
});
