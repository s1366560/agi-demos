import { Route, Routes, MemoryRouter, useNavigate } from 'react-router-dom';

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { OPEN_AGENT_CHAT_SEARCH_EVENT } from '@/components/agent/chat/searchEvents';
import { AgentLayout } from '@/layouts/AgentLayout';

const mockProjectStoreState = vi.hoisted(() => ({
  currentProject: { id: 'proj-123', name: 'Test Project' } as any,
  projects: [] as any[],
  setCurrentProject: vi.fn(),
  getProject: vi.fn(),
}));

const mockTenantStoreState = vi.hoisted(() => ({
  currentTenant: { id: 'tenant-123', name: 'Test Tenant' },
}));

vi.mock('@/stores/project', () => {
  const hook = ((selector?: any) =>
    selector ? selector(mockProjectStoreState) : mockProjectStoreState) as any;
  hook.getState = () => mockProjectStoreState;
  hook.setState = vi.fn();
  hook.subscribe = vi.fn();
  return { useProjectStore: hook };
});

vi.mock('@/stores/tenant', () => {
  const hook = ((selector?: any) =>
    selector ? selector(mockTenantStoreState) : mockTenantStoreState) as any;
  hook.getState = () => mockTenantStoreState;
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

const ProjectRouteSwitcher = () => {
  const navigate = useNavigate();

  return (
    <button
      type="button"
      onClick={() => {
        void navigate('/tenant/tenant-123/project/new-project/agent');
      }}
    >
      Switch project
    </button>
  );
};

describe('AgentLayout', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockProjectStoreState.currentProject = { id: 'proj-123', name: 'Test Project' };
    mockProjectStoreState.projects = [];
    mockProjectStoreState.getProject.mockResolvedValue({ id: 'proj-123', name: 'Test Project' });
    mockTenantStoreState.currentTenant = { id: 'tenant-123', name: 'Test Tenant' };
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

    it('should expose accessible names for header controls', () => {
      renderWithRouter(
        <Routes>
          <Route path="/tenant/:tenantId/project/:projectId/agent" element={<AgentLayout />}>
            <Route path="" element={<div>Content</div>} />
          </Route>
        </Routes>
      );

      expect(
        screen.getByRole('button', { name: /search current conversation/i })
      ).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /view execution history/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /view workflow patterns/i })).toBeInTheDocument();
    });

    it('dispatches a chat search request from the header search action', () => {
      const dispatchSpy = vi.spyOn(window, 'dispatchEvent');

      renderWithRouter(
        <Routes>
          <Route
            path="/tenant/:tenantId/project/:projectId/agent/:conversationId"
            element={<AgentLayout />}
          >
            <Route path="" element={<div>Content</div>} />
          </Route>
        </Routes>,
        ['/tenant/tenant-123/project/proj-123/agent/conv-1']
      );

      fireEvent.click(screen.getByRole('button', { name: /search current conversation/i }));

      expect(dispatchSpy).toHaveBeenCalledWith(
        expect.objectContaining({ type: OPEN_AGENT_CHAT_SEARCH_EVENT })
      );
    });

    it('ignores stale project fetches after the agent route project changes', async () => {
      mockProjectStoreState.currentProject = null;
      mockProjectStoreState.projects = [];
      const staleProject = createDeferred<any>();
      const currentProject = createDeferred<any>();
      mockProjectStoreState.getProject.mockImplementation((_tenantId: string, projectId: string) =>
        projectId === 'old-project' ? staleProject.promise : currentProject.promise
      );

      renderWithRouter(
        <>
          <ProjectRouteSwitcher />
          <Routes>
            <Route path="/tenant/:tenantId/project/:projectId/agent" element={<AgentLayout />}>
              <Route path="" element={<div>Content</div>} />
            </Route>
          </Routes>
        </>,
        ['/tenant/tenant-123/project/old-project/agent']
      );

      await waitFor(() => {
        expect(mockProjectStoreState.getProject).toHaveBeenCalledWith('tenant-123', 'old-project');
      });

      fireEvent.click(screen.getByRole('button', { name: 'Switch project' }));

      await waitFor(() => {
        expect(mockProjectStoreState.getProject).toHaveBeenCalledWith('tenant-123', 'new-project');
      });

      currentProject.resolve({ id: 'new-project', name: 'Current Project' });
      await currentProject.promise;

      await waitFor(() => {
        expect(mockProjectStoreState.setCurrentProject).toHaveBeenCalledWith({
          id: 'new-project',
          name: 'Current Project',
        });
      });

      staleProject.resolve({ id: 'old-project', name: 'Stale Project' });
      await staleProject.promise;
      await Promise.resolve();

      expect(mockProjectStoreState.setCurrentProject).toHaveBeenCalledTimes(1);
      expect(mockProjectStoreState.setCurrentProject).not.toHaveBeenCalledWith({
        id: 'old-project',
        name: 'Stale Project',
      });
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
