import { describe, it, expect, vi, beforeEach } from 'vitest';

import { TenantLayout } from '../../layouts/TenantLayout';
import { screen, render, waitFor, act, fireEvent } from '../utils';

let mockTenantState: any = {
  tenants: [{ id: 't1', name: 'Test Tenant' }],
  currentTenant: { id: 't1', name: 'Test Tenant' },
  isLoading: false,
  error: null,
  total: 0,
  page: 1,
  pageSize: 20,
  listTenants: vi.fn().mockResolvedValue(undefined),
  getTenant: vi.fn().mockResolvedValue(undefined),
  createTenant: vi.fn().mockResolvedValue(undefined),
  updateTenant: vi.fn().mockResolvedValue(undefined),
  deleteTenant: vi.fn().mockResolvedValue(undefined),
  setCurrentTenant: vi.fn(),
  addMember: vi.fn().mockResolvedValue(undefined),
  removeMember: vi.fn().mockResolvedValue(undefined),
  listMembers: vi.fn().mockResolvedValue([]),
  clearError: vi.fn(),
};

let mockProjectState: any = {
  currentProject: null,
  projects: [],
  setCurrentProject: vi.fn(),
  getProject: vi.fn(),
  clearProjects: vi.fn(),
};

let mockRouteParams: Record<string, string | undefined> = { tenantId: 't1' };
const mockRouteParamListeners = new Set<() => void>();
let mockLocationPathname = '/tenant/t1/overview';
let mockLocationSearch = '';
const mockNavigate = vi.fn();
const {
  mockAgentV3SetState,
  mockConversationReset,
  mockTimelineReset,
  mockStreamingReset,
  mockExecutionReset,
  mockHITLSyncFromConversation,
  mockSandboxUnsubscribeSSE,
  mockSandboxReset,
  mockAgentDisconnect,
  mockUnifiedDisconnect,
} = vi.hoisted(() => ({
  mockAgentV3SetState: vi.fn(),
  mockConversationReset: vi.fn(),
  mockTimelineReset: vi.fn(),
  mockStreamingReset: vi.fn(),
  mockExecutionReset: vi.fn(),
  mockHITLSyncFromConversation: vi.fn(),
  mockSandboxUnsubscribeSSE: vi.fn(),
  mockSandboxReset: vi.fn(),
  mockAgentDisconnect: vi.fn(),
  mockUnifiedDisconnect: vi.fn(),
}));

function setMockRouteParams(params: Record<string, string | undefined>) {
  mockRouteParams = params;
  mockRouteParamListeners.forEach((listener) => {
    listener();
  });
}

const createDeferred = <T,>() => {
  let resolvePromise: (value: T | PromiseLike<T>) => void = () => {};
  let rejectPromise: (reason?: unknown) => void = () => {};
  const promise = new Promise<T>((resolve, reject) => {
    resolvePromise = resolve;
    rejectPromise = reject;
  });

  return {
    promise,
    resolve: resolvePromise,
    reject: rejectPromise,
  };
};

function createMockStore() {
  const getState = () => mockTenantState;
  const setState = (partial: any) => {
    mockTenantState =
      typeof partial === 'function' ? partial(mockTenantState) : { ...mockTenantState, ...partial };
  };
  const subscribe = vi.fn();

  const storeHook = ((selector?: any) =>
    selector ? selector(mockTenantState) : mockTenantState) as any;

  storeHook.getState = getState;
  storeHook.setState = setState;
  storeHook.subscribe = subscribe;

  return storeHook;
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        'nav.overview': 'Overview',
        'nav.projects': 'Projects',
        'nav.users': 'Users',
        'nav.analytics': 'Analytics',
        'nav.tasks': 'Tasks',
        'nav.agents': 'Agents',
        'nav.agentConfiguration': 'Agent Configuration',
        'nav.subagents': 'Subagents',
        'nav.skills': 'Skills',
        'nav.plugins': 'Plugins',
        'nav.mcpServers': 'MCP Servers',
        'nav.providers': 'Providers',
        'nav.administration': 'Administration',
        'nav.billing': 'Billing',
        'nav.settings': 'Settings',
        'tenant.welcome': 'Welcome',
        'tenant.noTenantDescription': 'Create a workspace to get started',
        'tenant.entry.loadingTitle': 'Checking tenant access',
        'tenant.entry.loadingDescription': 'Loading tenant spaces',
        'tenant.entry.errorTitle': 'Tenant spaces unavailable',
        'tenant.entry.errorDescription': 'Retry before creating a new tenant',
        'tenant.create': 'Create Workspace',
        'common.logout': 'Logout',
        'common.retry': 'Retry',
        'common.search': 'Search',
      };
      return translations[key] || key;
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

vi.mock('../../stores/auth', () => {
  const state = {
    user: { name: 'Test User', email: 'test@example.com' },
    logout: vi.fn(),
    isAuthenticated: true,
    token: 'test-token',
  };
  const hook = ((selector?: any) => (selector ? selector(state) : state)) as any;
  hook.getState = () => state;
  hook.setState = vi.fn();
  hook.subscribe = vi.fn();
  return {
    useAuthStore: hook,
    useUser: () => state.user,
    useAuthActions: () => ({ login: vi.fn(), logout: state.logout }),
  };
});

vi.mock('../../stores/project', () => {
  const hook = ((selector?: any) =>
    selector ? selector(mockProjectState) : mockProjectState) as any;
  hook.getState = () => mockProjectState;
  hook.setState = vi.fn();
  hook.subscribe = vi.fn();
  return { useProjectStore: hook };
});

vi.mock('../../stores/tenant', () => ({
  useTenantStore: createMockStore(),
}));

vi.mock('@/stores/agent/conversationsStore', () => ({
  useConversationsStore: {
    getState: () => ({
      reset: mockConversationReset,
    }),
  },
}));

vi.mock('@/stores/agent/executionStore', () => ({
  useExecutionStore: {
    getState: () => ({
      reset: mockExecutionReset,
    }),
  },
}));

vi.mock('@/stores/agent/hitlStore', () => ({
  useAgentHITLStore: {
    getState: () => ({
      syncFromConversation: mockHITLSyncFromConversation,
    }),
  },
}));

vi.mock('@/stores/agent/streamingStore', () => ({
  useStreamingStore: {
    getState: () => ({
      reset: mockStreamingReset,
    }),
  },
}));

vi.mock('@/stores/agent/timelineStore', () => ({
  useTimelineStore: {
    getState: () => ({
      reset: mockTimelineReset,
    }),
  },
}));

vi.mock('@/stores/agentV3', () => ({
  useAgentV3Store: {
    setState: mockAgentV3SetState,
  },
}));

vi.mock('@/stores/sandbox', () => ({
  useSandboxStore: {
    getState: () => ({
      unsubscribeSSE: mockSandboxUnsubscribeSSE,
      reset: mockSandboxReset,
    }),
  },
}));

vi.mock('@/services/agentService', () => ({
  agentService: {
    disconnect: mockAgentDisconnect,
  },
}));

vi.mock('@/services/unifiedEventService', () => ({
  unifiedEventService: {
    disconnect: mockUnifiedDisconnect,
  },
}));

vi.mock('@/components/layout/TenantChatSidebar', () => ({
  TenantChatSidebar: () => <div data-testid="tenant-sidebar">MemStack</div>,
}));

vi.mock('@/components/layout/TenantHeader', () => ({
  __esModule: true,
  default: () => (
    <header data-testid="tenant-header">
      <div data-testid="theme-toggle">Theme</div>
      <div data-testid="lang-toggle">Lang</div>
      <div data-testid="workspace-switcher">MockSwitcher</div>
      <span>Overview</span>
      <span>Projects</span>
    </header>
  ),
}));

vi.mock('@/components/agent/BackgroundSubAgentPanel', () => ({
  BackgroundSubAgentPanel: () => null,
}));

vi.mock('@/components/agent/chat/MobileSidebarDrawer', () => ({
  MobileSidebarDrawer: () => null,
}));

vi.mock('@/components/common/RouteErrorBoundary', () => ({
  RouteErrorBoundary: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock('@/pages/tenant/TenantCreate', () => ({
  TenantCreateModal: () => null,
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  const React = await vi.importActual<typeof import('react')>('react');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () =>
      React.useSyncExternalStore(
        (listener) => {
          mockRouteParamListeners.add(listener);
          return () => {
            mockRouteParamListeners.delete(listener);
          };
        },
        () => mockRouteParams,
        () => mockRouteParams
      ),
    useLocation: () => ({ pathname: mockLocationPathname, search: mockLocationSearch }),
    Outlet: () => <div data-testid="outlet">Page Content</div>,
  };
});

describe('TenantLayout', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    // Reset to default state with a tenant
    mockTenantState = {
      tenants: [{ id: 't1', name: 'Test Tenant' }],
      currentTenant: { id: 't1', name: 'Test Tenant' },
      isLoading: false,
      error: null,
      total: 0,
      page: 1,
      pageSize: 20,
      listTenants: vi.fn().mockResolvedValue(undefined),
      getTenant: vi.fn().mockResolvedValue(undefined),
      createTenant: vi.fn().mockResolvedValue(undefined),
      updateTenant: vi.fn().mockResolvedValue(undefined),
      deleteTenant: vi.fn().mockResolvedValue(undefined),
      setCurrentTenant: vi.fn(),
      addMember: vi.fn().mockResolvedValue(undefined),
      removeMember: vi.fn().mockResolvedValue(undefined),
      listMembers: vi.fn().mockResolvedValue([]),
      clearError: vi.fn(),
    };
    mockProjectState = {
      currentProject: null,
      projects: [],
      setCurrentProject: vi.fn((project) => {
        mockProjectState.currentProject = project;
      }),
      getProject: vi.fn(),
      clearProjects: vi.fn(() => {
        mockProjectState.currentProject = null;
        mockProjectState.projects = [];
      }),
    };
    setMockRouteParams({ tenantId: 't1' });
    mockLocationPathname = '/tenant/t1/overview';
    mockLocationSearch = '';
  });

  it('renders layout elements', async () => {
    render(<TenantLayout />);

    await waitFor(() => {
      expect(screen.getByText('MemStack')).toBeInTheDocument();
    });
    expect(screen.getByText('Overview')).toBeInTheDocument();
    expect(screen.getByText('Projects')).toBeInTheDocument();
  });

  it('renders header components', async () => {
    render(<TenantLayout />);

    await waitFor(() => {
      expect(screen.getByTestId('theme-toggle')).toBeInTheDocument();
    });
    expect(screen.getByTestId('lang-toggle')).toBeInTheDocument();
    expect(screen.getByTestId('workspace-switcher')).toBeInTheDocument();
  });

  it('toggles sidebar', async () => {
    render(<TenantLayout />);

    await waitFor(() => {
      expect(screen.getByText('MemStack')).toBeInTheDocument();
    });
    expect(screen.getByText('Overview')).toBeVisible();
  });

  it('syncs tenant from URL', async () => {
    // Set state without tenant
    mockTenantState.currentTenant = null;
    mockTenantState.tenants = [];

    render(<TenantLayout />);

    // Component renders even without tenant
    await waitFor(() => {
      expect(screen.getByText('MemStack')).toBeInTheDocument();
    });
  });

  it('redirects bare tenant entry to the selected tenant already in state', async () => {
    const tenant = { id: 'existing-tenant', name: 'Existing Tenant' };
    setMockRouteParams({});
    mockLocationPathname = '/tenant';
    mockTenantState.currentTenant = null;
    mockTenantState.tenants = [tenant];

    render(<TenantLayout />);

    await waitFor(() => {
      expect(mockTenantState.setCurrentTenant).toHaveBeenCalledWith(tenant);
    });
    expect(mockNavigate).toHaveBeenCalledWith('/tenant/existing-tenant/overview', {
      replace: true,
    });
    expect(screen.queryByText('Welcome')).not.toBeInTheDocument();
  });

  it('redirects bare tenant entry with current tenant directly to overview', async () => {
    const tenant = { id: 'current-tenant', name: 'Current Tenant' };
    setMockRouteParams({});
    mockLocationPathname = '/tenant';
    mockTenantState.currentTenant = tenant;
    mockTenantState.tenants = [tenant];

    render(<TenantLayout />);

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/tenant/current-tenant/overview', {
        replace: true,
      });
    });
    expect(mockTenantState.getTenant).not.toHaveBeenCalled();
    expect(screen.queryByText('Welcome')).not.toBeInTheDocument();
  });

  it('redirects bare tenant entry after loading accessible tenants', async () => {
    const tenant = { id: 'loaded-tenant', name: 'Loaded Tenant' };
    setMockRouteParams({});
    mockLocationPathname = '/tenant';
    mockTenantState.currentTenant = null;
    mockTenantState.tenants = [];
    mockTenantState.listTenants = vi.fn().mockImplementation(async () => {
      mockTenantState.tenants = [tenant];
    });

    render(<TenantLayout />);

    await waitFor(() => {
      expect(mockTenantState.listTenants).toHaveBeenCalled();
    });
    expect(mockTenantState.setCurrentTenant).toHaveBeenCalledWith(tenant);
    expect(mockNavigate).toHaveBeenCalledWith('/tenant/loaded-tenant/overview', {
      replace: true,
    });
    expect(screen.queryByText('Welcome')).not.toBeInTheDocument();
  });

  it('shows the create-tenant empty state only when no accessible tenants exist', async () => {
    setMockRouteParams({});
    mockLocationPathname = '/tenant';
    mockTenantState.currentTenant = null;
    mockTenantState.tenants = [];
    mockTenantState.listTenants = vi.fn().mockResolvedValue(undefined);

    render(<TenantLayout />);

    await waitFor(() => {
      expect(screen.getByText('Welcome')).toBeInTheDocument();
    });
    expect(mockTenantState.createTenant).not.toHaveBeenCalled();
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it('shows a retryable error instead of the empty state when tenant loading fails', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    setMockRouteParams({});
    mockLocationPathname = '/tenant';
    mockTenantState.currentTenant = null;
    mockTenantState.tenants = [];
    mockTenantState.listTenants = vi.fn().mockRejectedValue(new Error('network unavailable'));

    render(<TenantLayout />);

    await waitFor(() => {
      expect(screen.getByText('Tenant spaces unavailable')).toBeInTheDocument();
    });
    expect(screen.queryByText('Welcome')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(mockNavigate).not.toHaveBeenCalled();
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      'Failed to list accessible tenants:',
      expect.any(Error)
    );
    consoleErrorSpy.mockRestore();
  });

  it('activates an existing tenant after retrying a failed tenant entry load', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const tenant = { id: 'retry-tenant', name: 'Retry Tenant' };
    setMockRouteParams({});
    mockLocationPathname = '/tenant';
    mockTenantState.currentTenant = null;
    mockTenantState.tenants = [];
    mockTenantState.listTenants = vi
      .fn()
      .mockRejectedValueOnce(new Error('network unavailable'))
      .mockImplementationOnce(async () => {
        mockTenantState.tenants = [tenant];
      });

    render(<TenantLayout />);

    await waitFor(() => {
      expect(screen.getByText('Tenant spaces unavailable')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(mockTenantState.setCurrentTenant).toHaveBeenCalledWith(tenant);
    });
    expect(mockNavigate).toHaveBeenCalledWith('/tenant/retry-tenant/overview', {
      replace: true,
    });
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      'Failed to list accessible tenants:',
      expect.any(Error)
    );
    consoleErrorSpy.mockRestore();
  });

  it('falls back when a route tenant fetch is superseded by post-auth tenant recovery', async () => {
    const tenant = { id: 'current-tenant', name: 'Current Tenant' };
    setMockRouteParams({ tenantId: 'stale-tenant' });
    mockLocationPathname = '/tenant/stale-tenant/overview';
    mockTenantState.currentTenant = tenant;
    mockTenantState.tenants = [tenant];
    mockTenantState.getTenant = vi.fn().mockResolvedValue(undefined);
    mockTenantState.listTenants = vi.fn().mockResolvedValue(undefined);

    render(<TenantLayout />);

    await waitFor(() => {
      expect(mockTenantState.getTenant).toHaveBeenCalledWith('stale-tenant');
    });
    await waitFor(() => {
      expect(mockTenantState.listTenants).toHaveBeenCalled();
    });
    expect(mockTenantState.setCurrentTenant).toHaveBeenCalledWith(tenant);
    expect(mockNavigate).toHaveBeenCalledWith('/tenant/current-tenant/overview', {
      replace: true,
    });
    expect(screen.queryByText('Welcome')).not.toBeInTheDocument();
  });

  it('activates tenants that arrive after an initially stale tenant list read', async () => {
    const tenant = { id: 'late-tenant', name: 'Late Tenant' };
    setMockRouteParams({});
    mockLocationPathname = '/tenant';
    mockTenantState.currentTenant = null;
    mockTenantState.tenants = [];
    mockTenantState.listTenants = vi.fn().mockResolvedValue(undefined);

    const { rerender } = render(<TenantLayout />);

    await waitFor(() => {
      expect(screen.getByText('Welcome')).toBeInTheDocument();
    });

    mockTenantState.tenants = [tenant];
    rerender(<TenantLayout />);

    await waitFor(() => {
      expect(mockTenantState.setCurrentTenant).toHaveBeenCalledWith(tenant);
    });
    expect(mockNavigate).toHaveBeenCalledWith('/tenant/late-tenant/overview', {
      replace: true,
    });
  });

  it('ignores stale project fetches after route project changes', async () => {
    const oldProject = createDeferred<{ id: string; name: string }>();
    const newProject = createDeferred<{ id: string; name: string }>();
    setMockRouteParams({ tenantId: 't1', projectId: 'old-project' });
    mockProjectState.getProject.mockImplementation((_tenantId: string, projectId: string) =>
      projectId === 'old-project' ? oldProject.promise : newProject.promise
    );

    render(<TenantLayout />);

    await waitFor(() => {
      expect(mockProjectState.getProject).toHaveBeenCalledWith('t1', 'old-project');
    });

    await act(async () => {
      setMockRouteParams({ tenantId: 't1', projectId: 'new-project' });
    });

    await waitFor(() => {
      expect(mockProjectState.getProject).toHaveBeenCalledWith('t1', 'new-project');
    });

    await act(async () => {
      newProject.resolve({ id: 'new-project', name: 'New Project' });
    });

    await waitFor(() => {
      expect(mockProjectState.setCurrentProject).toHaveBeenLastCalledWith({
        id: 'new-project',
        name: 'New Project',
      });
    });

    await act(async () => {
      oldProject.resolve({ id: 'old-project', name: 'Old Project' });
    });

    await waitFor(() => {
      expect(mockProjectState.setCurrentProject).not.toHaveBeenCalledWith({
        id: 'old-project',
        name: 'Old Project',
      });
      expect(mockProjectState.currentProject).toEqual({
        id: 'new-project',
        name: 'New Project',
      });
    });
  });

  it('fetches a route project with the route tenant while the tenant store is stale', async () => {
    setMockRouteParams({ tenantId: 'tenant-new', projectId: 'project-new' });
    mockLocationPathname = '/tenant/tenant-new/project/project-new';
    mockTenantState.currentTenant = { id: 'tenant-old', name: 'Old Tenant' };
    mockProjectState.currentProject = null;
    mockProjectState.getProject.mockResolvedValue({
      id: 'project-new',
      tenant_id: 'tenant-new',
      name: 'New Tenant Project',
    });

    render(<TenantLayout />);

    await waitFor(() => {
      expect(mockProjectState.getProject).toHaveBeenCalledWith('tenant-new', 'project-new');
    });
    expect(mockProjectState.getProject).not.toHaveBeenCalledWith('tenant-old', 'project-new');
  });

  it('syncs project state from agent workspace project query parameter', async () => {
    const queryProject = { id: 'query-project', tenant_id: 't1', name: 'Query Project' };
    setMockRouteParams({ tenantId: 't1' });
    mockLocationPathname = '/tenant/t1/agent-workspace';
    mockLocationSearch = '?projectId=query-project';
    mockProjectState.projects = [queryProject];
    mockProjectState.currentProject = null;

    render(<TenantLayout />);

    await waitFor(() => {
      expect(mockProjectState.setCurrentProject).toHaveBeenCalledWith(queryProject);
    });
    expect(mockProjectState.setCurrentProject).not.toHaveBeenCalledWith(null);
    expect(mockProjectState.getProject).not.toHaveBeenCalled();
  });

  it('keeps workspace-selected project on base agent workspace routes', async () => {
    const currentProject = { id: 'workspace-project', tenant_id: 't1', name: 'Workspace Project' };
    setMockRouteParams({ tenantId: 't1' });
    mockLocationPathname = '/tenant/t1/agent-workspace';
    mockProjectState.currentProject = currentProject;

    render(<TenantLayout />);

    await waitFor(() => {
      expect(screen.getByText('MemStack')).toBeInTheDocument();
    });
    expect(mockProjectState.setCurrentProject).not.toHaveBeenCalledWith(null);
    expect(mockProjectState.currentProject).toEqual(currentProject);
  });

  it('clears project state when tenant scope changes', async () => {
    mockProjectState.projects = [{ id: 'project-1', name: 'Old Tenant Project' }];
    mockProjectState.currentProject = { id: 'project-1', name: 'Old Tenant Project' };

    render(<TenantLayout />);

    await waitFor(() => {
      expect(screen.getByText('MemStack')).toBeInTheDocument();
    });
    expect(mockProjectState.clearProjects).not.toHaveBeenCalled();
    expect(mockAgentV3SetState).not.toHaveBeenCalled();
    expect(mockAgentDisconnect).not.toHaveBeenCalled();
    expect(mockUnifiedDisconnect).not.toHaveBeenCalled();

    await act(async () => {
      mockTenantState.currentTenant = { id: 't2', name: 'Second Tenant' };
      setMockRouteParams({ tenantId: 't2' });
    });

    await waitFor(() => {
      expect(mockProjectState.clearProjects).toHaveBeenCalledTimes(1);
    });
    expect(mockProjectState.projects).toEqual([]);
    expect(mockProjectState.currentProject).toBeNull();
    expect(mockAgentV3SetState).toHaveBeenCalledWith({
      conversations: [],
      activeConversationId: null,
      isCreatingConversation: false,
      hasMoreConversations: false,
      conversationsTotal: 0,
      conversationStates: expect.any(Map),
    });
    expect(mockConversationReset).toHaveBeenCalledTimes(1);
    expect(mockTimelineReset).toHaveBeenCalledTimes(1);
    expect(mockStreamingReset).toHaveBeenCalledTimes(1);
    expect(mockExecutionReset).toHaveBeenCalledTimes(1);
    expect(mockHITLSyncFromConversation).toHaveBeenCalledWith({
      pendingClarification: null,
      pendingDecision: null,
      pendingEnvVarRequest: null,
      pendingPermission: null,
      doomLoopDetected: null,
      costTracking: null,
      suggestions: [],
      pinnedEventIds: expect.any(Set),
    });
    expect(mockSandboxUnsubscribeSSE).toHaveBeenCalledTimes(1);
    expect(mockSandboxReset).toHaveBeenCalledTimes(1);
    expect(mockAgentDisconnect).toHaveBeenCalledTimes(1);
    expect(mockUnifiedDisconnect).toHaveBeenCalledTimes(1);
  });
});
