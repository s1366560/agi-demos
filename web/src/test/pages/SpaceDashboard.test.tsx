import { BrowserRouter } from 'react-router-dom';

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { SpaceDashboard } from '../../pages/SpaceDashboard';
import { tenantAPI } from '../../services/api';
import { useProjectStore } from '../../stores/project';
import { useTenantStore } from '../../stores/tenant';

// Mock tenantAPI
vi.mock('../../services/api', () => ({
  tenantAPI: {
    getStats: vi.fn(),
  },
}));

// Mock AppLayout to render navigation items so we can switch tabs
vi.mock('../../components/AppLayout', () => ({
  AppLayout: ({ children, title, navigationGroups }: any) => (
    <div data-testid="app-layout">
      <h1>{title}</h1>
      <nav>
        {navigationGroups?.map((group: any) => (
          <div key={group.title}>
            {group.items.map((item: any) => (
              <button key={item.id} onClick={item.onClick}>
                {item.label}
              </button>
            ))}
          </div>
        ))}
      </nav>
      {children}
    </div>
  ),
}));

// Mock ProjectCreateModal - correct path after component reorganization
vi.mock('../../components/tenant/ProjectCreateModal', () => ({
  ProjectCreateModal: ({ isOpen, onClose }: any) =>
    isOpen ? (
      <div data-testid="create-project-modal">
        <button onClick={onClose}>Close</button>
      </div>
    ) : null,
}));

// Mock stores
vi.mock('../../stores/tenant', () => ({
  useTenantStore: vi.fn(),
}));
vi.mock('../../stores/project', () => ({
  useProjectStore: vi.fn(),
}));

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () => ({ spaceId: '123' }),
  };
});

describe('SpaceDashboard', () => {
  const mockGetTenant = vi.fn();
  const mockListProjects = vi.fn();
  const mockSetCurrentProject = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    (useTenantStore as any).mockReturnValue({
      currentTenant: { id: '123', name: 'Test Tenant' },
      getTenant: mockGetTenant,
    });
    (useProjectStore as any).mockReturnValue({
      projects: [],
      listProjects: mockListProjects,
      setCurrentProject: mockSetCurrentProject,
    });
    (tenantAPI.getStats as any).mockResolvedValue({
      storage: { used: 0, total: 100, percentage: 0 },
      projects: { active: 0, new_this_week: 0, list: [] },
      members: { total: 0, new_added: 0 },
      memory_history: [],
      tenant_info: {
        organization_id: 'org',
        plan: 'free',
        region: 'us',
        next_billing_date: '2023-01-01',
      },
    });
  });

  it('should load initial data', async () => {
    render(
      <BrowserRouter>
        <SpaceDashboard />
      </BrowserRouter>
    );

    await waitFor(() => {
      expect(mockGetTenant).toHaveBeenCalledWith('123');
      expect(mockListProjects).toHaveBeenCalledWith('123');
    });
  });

  it('should render project list', async () => {
    const mockProjects = [
      { id: 'p1', name: 'Project 1', created_at: new Date().toISOString() },
      { id: 'p2', name: 'Project 2', created_at: new Date().toISOString() },
    ];

    (useProjectStore as any).mockReturnValue({
      projects: mockProjects,
      listProjects: mockListProjects,
      setCurrentProject: mockSetCurrentProject,
    });

    render(
      <BrowserRouter>
        <SpaceDashboard />
      </BrowserRouter>
    );

    // Switch to Projects tab
    fireEvent.click(screen.getByText('Projects'));

    await waitFor(() => {
      expect(screen.getByText('Project 1')).toBeInTheDocument();
      expect(screen.getByText('Project 2')).toBeInTheDocument();
    });
  });

  it('should navigate to project dashboard', () => {
    const mockProject = { id: 'p1', name: 'Project 1', created_at: new Date().toISOString() };
    (useProjectStore as any).mockReturnValue({
      projects: [mockProject],
      listProjects: mockListProjects,
      setCurrentProject: mockSetCurrentProject,
    });

    render(
      <BrowserRouter>
        <SpaceDashboard />
      </BrowserRouter>
    );

    // Switch to Projects tab
    fireEvent.click(screen.getByText('Projects'));

    fireEvent.click(screen.getByText('Project 1'));
    expect(mockSetCurrentProject).toHaveBeenCalledWith(mockProject);
    expect(mockNavigate).toHaveBeenCalledWith('/space/123/project/p1');
  });

  it('should open create project modal', () => {
    render(
      <BrowserRouter>
        <SpaceDashboard />
      </BrowserRouter>
    );

    // Switch to Projects tab (New Project button is in Projects tab)
    fireEvent.click(screen.getByText('Projects'));

    // In the Projects tab, there is a "New Project" button, not "新建项目" (English in SpaceDashboard.tsx)
    // Looking at SpaceDashboard.tsx: <span>New Project</span>
    fireEvent.click(screen.getByText('New Project'));
    expect(screen.getByTestId('create-project-modal')).toBeInTheDocument();
  });
});
