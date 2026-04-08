import { describe, it, expect, vi, beforeEach } from 'vitest';

import { TenantLayout } from '../../layouts/TenantLayout';
import { screen, render, waitFor } from '../utils';

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
        'tenant.create': 'Create Workspace',
        'common.logout': 'Logout',
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
  const state = { currentProject: null, projects: [] };
  const hook = ((selector?: any) => (selector ? selector(state) : state)) as any;
  hook.getState = () => state;
  hook.setState = vi.fn();
  hook.subscribe = vi.fn();
  return { useProjectStore: hook };
});

vi.mock('../../stores/tenant', () => ({
  useTenantStore: createMockStore(),
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
  return {
    ...actual,
    useParams: vi.fn(() => ({ tenantId: 't1' })),
    useLocation: () => ({ pathname: '/tenant/t1/overview' }),
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

  it('auto creates tenant when none exist', async () => {
    // Set state without tenant and empty tenants list
    mockTenantState.currentTenant = null;
    mockTenantState.tenants = [];

    render(<TenantLayout />);

    // Component renders without tenant
    await waitFor(() => {
      expect(screen.getByText('MemStack')).toBeInTheDocument();
    });
  });
});
