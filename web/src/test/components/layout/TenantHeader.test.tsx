import { beforeEach, describe, expect, it, vi } from 'vitest';

import TenantHeader from '@/components/layout/TenantHeader';

import { fireEvent, render, screen } from '../../utils';

const togglePanel = vi.fn();
const setTheme = vi.fn();
const logout = vi.fn();
const listTenants = vi.fn().mockResolvedValue(undefined);
const setCurrentTenant = vi.fn();
const mockNavigate = vi.fn();

const tenantState = {
  currentTenant: { id: 'tenant-1', name: 'Tenant One' },
  tenants: [
    { id: 'tenant-1', name: 'Tenant One' },
    { id: 'tenant-2', name: 'Tenant Two' },
  ],
  listTenants,
  setCurrentTenant,
};

const projectState = {
  currentProject: { id: 'project-1', name: 'Project One' },
};

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback || _key,
    i18n: {
      language: 'en-US',
      changeLanguage: vi.fn(),
    },
  }),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('@/stores/auth', () => ({
  useUser: () => ({
    name: 'Test User',
    email: 'test@example.com',
    profile: {},
  }),
  useAuthActions: () => ({ logout }),
}));

vi.mock('@/stores/backgroundStore', () => ({
  useRunningCount: () => 0,
  useBackgroundStore: (selector: (state: { togglePanel: typeof togglePanel }) => unknown) =>
    selector({ togglePanel }),
}));

vi.mock('@/stores/theme', () => ({
  useThemeStore: (
    selector: (state: { theme: 'light'; setTheme: typeof setTheme }) => unknown
  ) => selector({ theme: 'light', setTheme }),
}));

vi.mock('@/stores/project', () => ({
  useProjectStore: (
    selector: (state: { currentProject: typeof projectState.currentProject | null }) => unknown
  ) => selector(projectState),
}));

vi.mock('@/stores/tenant', () => ({
  useTenantStore: (selector: (state: typeof tenantState) => unknown) => selector(tenantState),
}));

vi.mock('@/stores/workspace', () => ({
  useCurrentWorkspace: () => ({ id: 'ws-current' }),
  useWorkspaces: () => [{ id: 'ws-current' }],
}));

describe('TenantHeader', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    tenantState.currentTenant = { id: 'tenant-1', name: 'Tenant One' };
    tenantState.tenants = [
      { id: 'tenant-1', name: 'Tenant One' },
      { id: 'tenant-2', name: 'Tenant Two' },
    ];
    projectState.currentProject = { id: 'project-1', name: 'Project One' };
  });

  it('renders tenant-level navigation from derived tenant config', () => {
    render(
      <TenantHeader
        tenantId="tenant-1"
        sidebarCollapsed={false}
        onSidebarToggle={vi.fn()}
        onMobileMenuOpen={vi.fn()}
      />
    );

    expect(screen.getByRole('link', { name: 'Agent Workspace' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/agent-workspace'
    );
    expect(screen.getByRole('link', { name: 'Projects' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/projects'
    );
    expect(screen.getByRole('link', { name: 'Agent Configuration' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/agents'
    );
    expect(screen.getByRole('link', { name: 'Workspaces' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/workspaces'
    );
  });

  it('renders project-level contextual navigation instead of tenant destinations', () => {
    render(
      <TenantHeader
        tenantId="tenant-1"
        projectId="project-1"
        sidebarCollapsed={false}
        onSidebarToggle={vi.fn()}
        onMobileMenuOpen={vi.fn()}
      />
    );

    expect(screen.getByRole('link', { name: 'Overview' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/project/project-1'
    );
    expect(screen.getByRole('link', { name: 'Workspaces' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/project/project-1/workspaces'
    );
    expect(screen.getByRole('link', { name: 'Memories' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/project/project-1/memories'
    );
    expect(screen.queryByRole('link', { name: 'Agent Workspace' })).not.toBeInTheDocument();
  });

  it('keeps overflow destinations reachable from derived project nav', () => {
    render(
      <TenantHeader
        tenantId="tenant-1"
        projectId="project-1"
        sidebarCollapsed={false}
        onSidebarToggle={vi.fn()}
        onMobileMenuOpen={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /more/i }));

    expect(screen.getByRole('button', { name: 'Blackboard' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Blackboard' }));

    expect(mockNavigate).toHaveBeenCalledWith(
      '/tenant/tenant-1/project/project-1/blackboard?workspaceId=ws-current'
    );
  });

  it('renders tenant switching inside the user dropdown', () => {
    render(
      <TenantHeader
        tenantId="tenant-1"
        sidebarCollapsed={false}
        onSidebarToggle={vi.fn()}
        onMobileMenuOpen={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'User menu' }));

    expect(screen.getByText('Tenant')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Tenant Two' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Tenant Two' }));

    expect(setCurrentTenant).toHaveBeenCalledWith({ id: 'tenant-2', name: 'Tenant Two' });
    expect(mockNavigate).toHaveBeenCalledWith('/tenant/tenant-2');
  });

  it('falls back to /tenant base path when tenantId is empty', () => {
    tenantState.currentTenant = null;
    tenantState.tenants = [];

    render(
      <TenantHeader
        tenantId=""
        sidebarCollapsed={false}
        onSidebarToggle={vi.fn()}
        onMobileMenuOpen={vi.fn()}
      />
    );

    expect(screen.getByRole('link', { name: 'Agent Workspace' })).toHaveAttribute(
      'href',
      '/tenant/agent-workspace'
    );
    expect(screen.getByRole('link', { name: 'Projects' })).toHaveAttribute(
      'href',
      '/tenant/projects'
    );
  });
});
