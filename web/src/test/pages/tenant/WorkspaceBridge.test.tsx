import { describe, it, expect, vi, beforeEach } from 'vitest';
import { Route, Routes, useLocation } from 'react-router-dom';

import { render, screen, waitFor } from '../../utils';

import { AgentWorkspace } from '../../../pages/tenant/AgentWorkspace';
import { WorkspaceBlackboardRedirect } from '../../../pages/project/WorkspaceBlackboardRedirect';
import { buildAgentWorkspacePath } from '../../../utils/agentWorkspacePath';

const agentChatContentProps = vi.fn();

let projectState: any;
let tenantState: any;
let authState: any;
let workspaceState: any;

vi.mock('../../../components/agent/AgentChatContent', () => ({
  AgentChatContent: (props: unknown) => {
    agentChatContentProps(props);
    return <div data-testid="agent-chat-content" />;
  },
}));

vi.mock('../../../components/agent/context/ContextDetailPanel', () => ({
  ContextDetailPanel: () => <div data-testid="context-detail-panel" />,
}));

vi.mock('../../../components/workspace/BlackboardPanel', () => ({
  BlackboardPanel: () => <div data-testid="blackboard-panel" />,
}));

vi.mock('../../../components/workspace/TaskBoard', () => ({
  TaskBoard: () => <div data-testid="task-board" />,
}));

vi.mock('../../../components/workspace/MemberPanel', () => ({
  MemberPanel: () => <div data-testid="member-panel" />,
}));

vi.mock('../../../components/workspace/TopologyBoard', () => ({
  TopologyBoard: () => <div data-testid="topology-board" />,
}));

vi.mock('../../../hooks/useLocalStorage', () => ({
  useLocalStorage: () => ({
    value: null,
    setValue: vi.fn(),
  }),
}));

vi.mock('../../../stores/auth', () => ({
  useAuthStore: (selector: (state: any) => unknown) => selector(authState),
}));

vi.mock('../../../stores/tenant', () => ({
  useTenantStore: (selector: (state: any) => unknown) => selector(tenantState),
  useCurrentTenant: () => tenantState.currentTenant,
}));

vi.mock('../../../stores/project', () => ({
  useProjectStore: (selector: (state: any) => unknown) => selector(projectState),
  useCurrentProject: () => projectState.currentProject,
}));

vi.mock('../../../stores/agentV3', () => ({
  useAgentV3Store: (selector: (state: any) => unknown) =>
    selector({
      loadConversations: vi.fn(),
    }),
}));

vi.mock('../../../stores/workspace', () => ({
  useCurrentWorkspace: () => workspaceState.currentWorkspace,
  useWorkspaceLoading: () => workspaceState.isLoading,
  useWorkspaceActions: () => workspaceState.actions,
}));

describe('workspace/agent workspace bridge', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    authState = {
      user: { tenant_id: 'tenant-1' },
    };

    tenantState = {
      currentTenant: { id: 'tenant-1', name: 'Tenant One' },
    };

    projectState = {
      projects: [
        { id: 'project-1', tenant_id: 'tenant-1', name: 'Project 1' },
        { id: 'project-2', tenant_id: 'tenant-1', name: 'Project 2' },
      ],
      currentProject: { id: 'project-1', tenant_id: 'tenant-1', name: 'Project 1' },
      setCurrentProject: vi.fn(),
      listProjects: vi.fn().mockResolvedValue(undefined),
    };

    workspaceState = {
      currentWorkspace: { id: 'ws-1', name: 'Workspace One' },
      isLoading: false,
      actions: {
        loadWorkspaceSurface: vi.fn().mockResolvedValue(undefined),
      },
    };
  });

  it('passes workspace/project query context into AgentChatContent', () => {
    render(<AgentWorkspace />, {
      route: '/tenant/tenant-1/agent-workspace?projectId=project-2&workspaceId=ws-9',
    });

    return waitFor(() => {
      expect(screen.getByTestId('agent-chat-content')).toBeInTheDocument();
      expect(agentChatContentProps).toHaveBeenCalledWith(
        expect.objectContaining({
          externalProjectId: 'project-2',
          navigationQuery: 'projectId=project-2&workspaceId=ws-9',
        })
      );
    });
  });

  it('redirects legacy workspace detail routes to the project blackboard with workspace context', async () => {
    const LocationProbe = () => {
      const location = useLocation();
      return <div data-testid="location-probe">{`${location.pathname}${location.search}`}</div>;
    };

    render(
      <Routes>
        <Route
          path="/tenant/:tenantId/project/:projectId/workspaces/:workspaceId"
          element={<WorkspaceBlackboardRedirect />}
        />
        <Route
          path="/tenant/:tenantId/project/:projectId/blackboard"
          element={<LocationProbe />}
        />
      </Routes>,
      {
        route: '/tenant/tenant-1/project/project-1/workspaces/ws-1',
      }
    );

    await waitFor(() => {
      expect(screen.getByTestId('location-probe')).toHaveTextContent(
        '/tenant/tenant-1/project/project-1/blackboard?workspaceId=ws-1'
      );
    });
  });

  it('waits for tenant context instead of redirecting to an invalid tenant-less path', async () => {
    tenantState = {
      currentTenant: null,
    };
    authState = {
      user: null,
    };

    const LocationProbe = () => {
      const location = useLocation();
      return <div data-testid="location-probe">{`${location.pathname}${location.search}`}</div>;
    };

    render(
      <>
        <LocationProbe />
        <Routes>
          <Route
            path="/project/:projectId/workspaces/:workspaceId"
            element={<WorkspaceBlackboardRedirect />}
          />
        </Routes>
      </>,
      {
        route: '/project/project-1/workspaces/ws-1',
      }
    );

    await waitFor(() => {
      expect(screen.getByTestId('location-probe')).toHaveTextContent(
        '/project/project-1/workspaces/ws-1'
      );
    });
  });

  it('preserves workspaceId in conversation navigation URLs', () => {
    expect(
      buildAgentWorkspacePath({
        tenantId: 'tenant-1',
        conversationId: 'conv-1',
        projectId: 'project-1',
        workspaceId: 'ws-1',
      })
    ).toBe('/tenant/tenant-1/agent-workspace/conv-1?projectId=project-1&workspaceId=ws-1');
  });

  it('preserves workspaceId in base agent workspace URL', () => {
    expect(
      buildAgentWorkspacePath({
        tenantId: 'tenant-1',
        projectId: 'project-1',
        workspaceId: 'ws-1',
      })
    ).toBe('/tenant/tenant-1/agent-workspace?projectId=project-1&workspaceId=ws-1');
  });
});
