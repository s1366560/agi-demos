import { describe, it, expect, vi, beforeEach } from 'vitest';

import { TenantLayoutView } from '../../layouts/TenantLayoutView';
import { render, waitFor } from '../utils';

const mockNavigate = vi.fn();
let mockRouteParams: Record<string, string | undefined> = {};
let mockLocationPathname = '/tenant';

const tenantState = {
  tenants: [{ id: 't1', name: 'Test Tenant' }],
  currentTenant: { id: 't1', name: 'Test Tenant' },
  isLoading: false,
  error: null,
  listTenants: vi.fn(),
  setCurrentTenant: vi.fn(),
  getTenant: vi.fn(),
};
const projectState = {
  currentProject: null,
  projects: [],
  setCurrentProject: vi.fn(),
  getProject: vi.fn(),
  clearProjects: vi.fn(),
};
const authState = {
  user: { name: 'Test User', email: 'test@example.com' },
  logout: vi.fn(),
  isAuthenticated: true,
  token: 'test-token',
};

// vi.mock factories run before module constants exist, so each store hook reads
// its state lazily and is only invoked after this module has been evaluated.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

vi.mock('../../stores/auth', () => {
  const hook = ((selector?: any) => (selector ? selector(authState) : authState)) as any;
  hook.getState = () => authState;
  hook.setState = vi.fn();
  hook.subscribe = vi.fn();
  return {
    useAuthStore: hook,
    useUser: () => authState.user,
    useAuthActions: () => ({ login: vi.fn(), logout: authState.logout }),
  };
});

vi.mock('../../stores/project', () => {
  const hook = ((selector?: any) => (selector ? selector(projectState) : projectState)) as any;
  hook.getState = () => projectState;
  hook.setState = vi.fn();
  hook.subscribe = vi.fn();
  return { useProjectStore: hook };
});

vi.mock('../../stores/tenant', () => {
  const hook = ((selector?: any) => (selector ? selector(tenantState) : tenantState)) as any;
  hook.getState = () => tenantState;
  hook.setState = vi.fn();
  hook.subscribe = vi.fn();
  return { useTenantStore: hook };
});

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () => mockRouteParams,
    useLocation: () => ({ pathname: mockLocationPathname, search: '' }),
    Outlet: () => <div data-testid="outlet">Page Content</div>,
  };
});

vi.mock('../../components/agent/chat/MobileSidebarDrawer', () => ({
  MobileSidebarDrawer: () => null,
}));

vi.mock('../../components/common/RouteErrorBoundary', () => ({
  RouteErrorBoundary: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock('../../pages/tenant/TenantCreate', () => ({
  TenantCreateModal: () => null,
}));

describe('TenantLayoutView landing section', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRouteParams = {};
    mockLocationPathname = '/tenant';
  });

  it('opens the landing section chosen by the host when the tenant entry is bare', async () => {
    render(
      <TenantLayoutView
        landing="projects"
        Sidebar={() => null}
        Header={() => null}
        Palette={() => null}
      />,
      { route: '/tenant' }
    );

    await waitFor(() =>
      expect(mockNavigate).toHaveBeenCalledWith('/tenant/t1/projects', { replace: true })
    );
  });

  it('hands the landing section to the host header', () => {
    mockRouteParams = { tenantId: 't1' };
    mockLocationPathname = '/tenant/t1/projects';
    const received: Array<string | undefined> = [];

    render(
      <TenantLayoutView
        landing="projects"
        Sidebar={() => null}
        Palette={() => null}
        Header={(props) => {
          received.push(props.landing);
          return null;
        }}
      />,
      { route: '/tenant/t1/projects' }
    );

    expect(received).toContain('projects');
  });
});
