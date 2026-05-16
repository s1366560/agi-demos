import { Route, Routes, MemoryRouter } from 'react-router-dom';

import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { AgentLayout } from '@/layouts/AgentLayout';

vi.mock('@/stores/project', () => {
  const state = {
    currentProject: { id: 'proj-123', name: 'Test Project' },
    projects: [],
    setCurrentProject: vi.fn(),
    getProject: vi.fn(),
  };
  const hook = ((selector?: any) => (selector ? selector(state) : state)) as any;
  hook.getState = () => state;
  hook.setState = vi.fn();
  hook.subscribe = vi.fn();
  return { useProjectStore: hook };
});

vi.mock('@/stores/tenant', () => {
  const state = { currentTenant: { id: 'tenant-123', name: 'Test Tenant' } };
  const hook = ((selector?: any) => (selector ? selector(state) : state)) as any;
  hook.getState = () => state;
  hook.setState = vi.fn();
  hook.subscribe = vi.fn();
  return { useTenantStore: hook };
});

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    user: { name: 'Test User', email: 'test@example.com' },
    logout: vi.fn(),
  }),
}));

vi.mock('@/components/common/RouteErrorBoundary', () => ({
  RouteErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('@/components/layout/AppSidebar', () => ({
  AgentSidebar: ({ collapsed }: any) => (
    <aside data-testid="agent-sidebar" data-collapsed={collapsed}>
      <nav>Sidebar Navigation</nav>
    </aside>
  ),
}));

vi.mock('@/components/mcp-app/AppLauncher', () => ({
  AppLauncher: () => <div data-testid="app-launcher">AppLauncher</div>,
}));

vi.mock('@/components/ui/lazyAntd', () => ({
  LazyTooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('@/hooks/useProjectBasePath', () => ({
  useProjectBasePath: () => ({ projectBasePath: '/tenant/tenant-123/project/proj-123' }),
}));

function renderWithRouter(
  ui: React.ReactElement,
  initialEntries = ['/tenant/tenant-123/project/proj-123/agent']
) {
  return render(<MemoryRouter initialEntries={initialEntries}>{ui}</MemoryRouter>);
}

describe('AgentLayout', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('Rendering', () => {
    it('should render the layout with sidebar and main content', () => {
      renderWithRouter(
        <Routes>
          <Route path="/tenant/:tenantId/project/:projectId/agent" element={<AgentLayout />}>
            <Route path="" element={<div>Agent Content</div>} />
          </Route>
        </Routes>
      );

      expect(screen.getByText('Agent Content')).toBeInTheDocument();
    });

    it('should render the sidebar', () => {
      renderWithRouter(
        <Routes>
          <Route path="/tenant/:tenantId/project/:projectId/agent" element={<AgentLayout />}>
            <Route path="" element={<div>Content</div>} />
          </Route>
        </Routes>
      );

      expect(screen.getByTestId('agent-sidebar')).toBeInTheDocument();
    });

    it('should render breadcrumb navigation', () => {
      renderWithRouter(
        <Routes>
          <Route path="/tenant/:tenantId/project/:projectId/agent" element={<AgentLayout />}>
            <Route path="" element={<div>Content</div>} />
          </Route>
        </Routes>,
        ['/tenant/tenant-123/project/proj-123/agent']
      );

      expect(screen.getByText('Test Project')).toBeInTheDocument();
      expect(screen.getByText('Agent')).toBeInTheDocument();
    });

    it('should render the top tabs', () => {
      renderWithRouter(
        <Routes>
          <Route path="/tenant/:tenantId/project/:projectId/agent" element={<AgentLayout />}>
            <Route path="" element={<div>Content</div>} />
          </Route>
        </Routes>
      );

      expect(screen.getByText('Dashboard')).toBeInTheDocument();
      expect(screen.getByText('Activity Logs')).toBeInTheDocument();
      expect(screen.getByText('Patterns')).toBeInTheDocument();
    });
  });

  describe('Sidebar', () => {
    it('should render the agent sidebar component', () => {
      renderWithRouter(
        <Routes>
          <Route path="/tenant/:tenantId/project/:projectId/agent" element={<AgentLayout />}>
            <Route path="" element={<div>Content</div>} />
          </Route>
        </Routes>
      );

      expect(screen.getByTestId('agent-sidebar')).toBeInTheDocument();
    });
  });

  describe('Agent Status', () => {
    it('should display online status badge', () => {
      renderWithRouter(
        <Routes>
          <Route path="/tenant/:tenantId/project/:projectId/agent" element={<AgentLayout />}>
            <Route path="" element={<div>Content</div>} />
          </Route>
        </Routes>
      );

      expect(screen.getByText('Agent Online')).toBeInTheDocument();
    });
  });
});
