import { describe, it, expect, vi, beforeEach } from 'vitest';
import { Route, Routes, useLocation } from 'react-router-dom';

import { fireEvent, render, screen, waitFor } from '../../utils';

import { AgentWorkspace } from '../../../pages/tenant/AgentWorkspace';
import { WorkspaceBlackboardRedirect } from '../../../pages/project/WorkspaceBlackboardRedirect';
import { buildAgentWorkspacePath } from '../../../utils/agentWorkspacePath';

const agentChatContentProps = vi.fn();
const localStorageMock = vi.hoisted(() => ({
  values: new Map<string, string | null>(),
  setValue: vi.fn(),
}));

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
  useLocalStorage: <T,>(key: string, initialValue: T) => ({
    value: (localStorageMock.values.has(key)
      ? localStorageMock.values.get(key)
      : initialValue) as T,
    setValue: localStorageMock.setValue,
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

vi.mock('../../../stores/workspace', () => {
  const buildState = () => ({
    currentWorkspace: workspaceState.currentWorkspace,
    isLoading: workspaceState.isLoading,
    actions: workspaceState.actions,
    posts: [],
    repliesByPostId: {},
    loadedReplyPostIds: [],
    tasks: [],
    objectives: [],
    genes: [],
    agents: [],
    topologyNodes: [],
    topologyEdges: [],
    error: null,
    clearPresence: vi.fn(),
    subscribeWorkspaceEvents: vi.fn(),
    unsubscribeWorkspaceEvents: vi.fn(),
  });
  const useWorkspaceStoreMock: any = (selector?: (state: any) => unknown) => {
    const state = buildState();
    return selector ? selector(state) : state;
  };
  useWorkspaceStoreMock.getState = () => buildState();
  useWorkspaceStoreMock.setState = vi.fn();
  useWorkspaceStoreMock.subscribe = vi.fn(() => vi.fn());
  return {
    useCurrentWorkspace: () => workspaceState.currentWorkspace,
    useWorkspaceLoading: () => workspaceState.isLoading,
    useWorkspaceActions: () => workspaceState.actions,
    useWorkspaceStore: useWorkspaceStoreMock,
  };
});

describe('workspace/agent workspace bridge', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageMock.values.clear();
    localStorageMock.setValue.mockReset();

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
      getProject: vi.fn().mockResolvedValue({
        id: 'project-2',
        tenant_id: 'tenant-1',
        name: 'Project 2',
      }),
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

  it('restores saved workspace context on base agent workspace URLs', () => {
    localStorageMock.values.set('agent:tenant-1:lastWorkspaceId', 'ws-remembered');

    render(<AgentWorkspace />, {
      route: '/tenant/tenant-1/agent-workspace?projectId=project-1',
    });

    return waitFor(() => {
      expect(screen.getByTestId('agent-chat-content')).toBeInTheDocument();
      expect(agentChatContentProps).toHaveBeenCalledWith(
        expect.objectContaining({
          navigationQuery: 'projectId=project-1&workspaceId=ws-remembered',
        })
      );
    });
  });

  it('does not restore saved workspace context on conversation URLs without workspace query', () => {
    localStorageMock.values.set('agent:tenant-1:lastWorkspaceId', 'ws-remembered');

    render(
      <Routes>
        <Route
          path="/tenant/:tenantId/agent-workspace/:conversation"
          element={<AgentWorkspace />}
        />
      </Routes>,
      {
        route: '/tenant/tenant-1/agent-workspace/conv-plain?projectId=project-1',
      }
    );

    return waitFor(() => {
      expect(screen.getByTestId('agent-chat-content')).toBeInTheDocument();
      expect(agentChatContentProps).toHaveBeenLastCalledWith(
        expect.objectContaining({
          navigationQuery: 'projectId=project-1',
        })
      );
    });
  });

  it('uses a URL project id instead of showing the empty-project state before the project list loads', () => {
    projectState.projects = [];
    projectState.currentProject = null;

    render(<AgentWorkspace />, {
      route: '/tenant/tenant-1/agent-workspace?projectId=project-2',
    });

    return waitFor(() => {
      expect(screen.getByTestId('agent-chat-content')).toBeInTheDocument();
      expect(screen.queryByText("You haven't created any projects yet")).not.toBeInTheDocument();
      expect(agentChatContentProps).toHaveBeenCalledWith(
        expect.objectContaining({
          externalProjectId: 'project-2',
        })
      );
    });
  });

  it('shows a retryable error when tenant projects fail to load', async () => {
    projectState.projects = [];
    projectState.currentProject = null;
    projectState.listProjects = vi
      .fn()
      .mockRejectedValueOnce(new Error('Tenant projects unavailable'))
      .mockResolvedValueOnce(undefined);

    render(<AgentWorkspace />, {
      route: '/tenant/tenant-1/agent-workspace',
    });

    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to load projects');
    expect(screen.getByRole('alert')).toHaveTextContent('Tenant projects unavailable');

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(projectState.listProjects).toHaveBeenCalledTimes(2);
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
        <Route path="/tenant/:tenantId/project/:projectId/blackboard" element={<LocationProbe />} />
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
