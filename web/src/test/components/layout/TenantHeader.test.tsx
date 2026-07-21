import { beforeEach, describe, expect, it, vi } from 'vitest';

import TenantHeader from '@/components/layout/TenantHeader';

import { fireEvent, render, screen } from '../../utils';

const setPanel = vi.fn();
const setTheme = vi.fn();
const logout = vi.fn();
const listTenants = vi.fn().mockResolvedValue(undefined);
const setCurrentTenant = vi.fn();
const clearProjects = vi.fn();
const mockNavigate = vi.fn();
const fetchNotifications = vi.fn().mockResolvedValue(undefined);
const markAsRead = vi.fn().mockResolvedValue(undefined);
const markAllAsRead = vi.fn().mockResolvedValue(undefined);
const deleteNotification = vi.fn().mockResolvedValue(undefined);

const tenantState = {
  currentTenant: { id: 'tenant-1', name: 'Tenant One' },
  tenants: [
    { id: 'tenant-1', name: 'Tenant One' },
    { id: 'tenant-2', name: 'Tenant Two' },
  ],
  listTenants,
  setCurrentTenant,
};

const projectState: {
  currentProject: { id: string; name: string; tenant_id: string } | null;
  clearProjects: typeof clearProjects;
} = {
  currentProject: { id: 'project-1', name: 'Project One', tenant_id: 'tenant-1' },
  clearProjects,
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
  useBackgroundStore: (selector: (state: { setPanel: typeof setPanel }) => unknown) =>
    selector({ setPanel }),
}));

vi.mock('@/stores/theme', () => ({
  useThemeStore: (selector: (state: { theme: 'light'; setTheme: typeof setTheme }) => unknown) =>
    selector({ theme: 'light', setTheme }),
}));

vi.mock('@/stores/project', () => ({
  useProjectStore: (
    selector: (state: {
      currentProject: typeof projectState.currentProject | null;
      clearProjects: typeof clearProjects;
    }) => unknown
  ) => selector(projectState),
}));

vi.mock('@/stores/tenant', () => ({
  useTenantStore: (selector: (state: typeof tenantState) => unknown) => selector(tenantState),
}));

vi.mock('@/stores/workspace', () => ({
  useCurrentWorkspace: () => ({ id: 'ws-current', tenant_id: 'tenant-1', project_id: 'project-1' }),
  useWorkspaces: () => [{ id: 'ws-current', tenant_id: 'tenant-1', project_id: 'project-1' }],
}));

vi.mock('@/stores/notification', () => ({
  useNotificationStore: (
    selector: (state: {
      notifications: unknown[];
      unreadCount: number;
      isLoading: boolean;
      fetchNotifications: typeof fetchNotifications;
      markAsRead: typeof markAsRead;
      markAllAsRead: typeof markAllAsRead;
      deleteNotification: typeof deleteNotification;
    }) => unknown
  ) =>
    selector({
      notifications: [],
      unreadCount: 0,
      isLoading: false,
      fetchNotifications,
      markAsRead,
      markAllAsRead,
      deleteNotification,
    }),
}));

describe('TenantHeader', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    tenantState.currentTenant = { id: 'tenant-1', name: 'Tenant One' };
    tenantState.tenants = [
      { id: 'tenant-1', name: 'Tenant One' },
      { id: 'tenant-2', name: 'Tenant Two' },
    ];
    projectState.currentProject = { id: 'project-1', name: 'Project One', tenant_id: 'tenant-1' };
    projectState.clearProjects = clearProjects;
  });

  it('renders tenant-level navigation as grouped dropdowns from derived tenant config', () => {
    render(
      <TenantHeader
        tenantId="tenant-1"
        sidebarCollapsed={false}
        onSidebarToggle={vi.fn()}
        onMobileMenuOpen={vi.fn()}
      />
    );

    expect(screen.getByRole('button', { name: 'Core Operations' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Agent Building' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Extensions & Integrations' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Core Operations' }));
    expect(screen.getByRole('link', { name: 'Projects' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/projects'
    );

    fireEvent.click(screen.getByRole('button', { name: 'Agent Building' }));
    expect(screen.getByRole('link', { name: 'Agent Configuration' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/agents'
    );
  });

  it('keeps desktop navigation visually bounded from header actions', () => {
    const { container } = render(
      <TenantHeader
        tenantId="tenant-1"
        sidebarCollapsed={false}
        onSidebarToggle={vi.fn()}
        onMobileMenuOpen={vi.fn()}
      />
    );

    expect(container.querySelector('nav')).toHaveClass(
      'hidden',
      'xl:flex',
      'overflow-hidden',
      'mr-2'
    );
    expect(screen.getByRole('link', { name: 'Search' }).parentElement).toHaveClass('flex-none');
  });

  it('keeps contextual navigation reachable in the tablet header range', () => {
    render(
      <TenantHeader
        tenantId="tenant-1"
        sidebarCollapsed={false}
        onSidebarToggle={vi.fn()}
        onMobileMenuOpen={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Navigation' }));

    expect(screen.getAllByText('Core Operations').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Agent Building').length).toBeGreaterThan(0);

    expect(screen.getByRole('link', { name: 'Projects' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/projects'
    );
  });

  it('exposes the dead letter queue in contextual navigation', () => {
    render(
      <TenantHeader
        tenantId="tenant-1"
        sidebarCollapsed={false}
        onSidebarToggle={vi.fn()}
        onMobileMenuOpen={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Navigation' }));

    expect(screen.getAllByText('Governance & Management').length).toBeGreaterThan(0);

    expect(screen.getByRole('link', { name: 'Dead Letter Queue' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/dead-letter-queue'
    );
  });

  it('closes a navigation menu with Escape and returns focus to the trigger', () => {
    render(
      <TenantHeader
        tenantId="tenant-1"
        sidebarCollapsed={false}
        onSidebarToggle={vi.fn()}
        onMobileMenuOpen={vi.fn()}
      />
    );

    const trigger = screen.getByRole('button', { name: 'Core Operations' });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu');

    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('link', { name: 'Projects' })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('link', { name: 'Projects' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('routes tenant-level search to the project discovery view', () => {
    render(
      <TenantHeader
        tenantId="tenant-1"
        sidebarCollapsed={false}
        onSidebarToggle={vi.fn()}
        onMobileMenuOpen={vi.fn()}
      />
    );

    expect(screen.getByRole('link', { name: 'Search' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/projects'
    );
  });

  it('routes project-level search to the deep search view', () => {
    render(
      <TenantHeader
        tenantId="tenant-1"
        projectId="project-1"
        sidebarCollapsed={false}
        onSidebarToggle={vi.fn()}
        onMobileMenuOpen={vi.fn()}
      />
    );

    expect(screen.getByRole('link', { name: 'Search' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/project/project-1/advanced-search'
    );
  });

  it('does not derive project navigation from another tenant project', () => {
    projectState.currentProject = {
      id: 'project-2',
      name: 'Project Two',
      tenant_id: 'tenant-2',
    };

    render(
      <TenantHeader
        tenantId="tenant-1"
        sidebarCollapsed={false}
        onSidebarToggle={vi.fn()}
        onMobileMenuOpen={vi.fn()}
      />,
      { route: '/tenant/tenant-1/project/project-1/settings' }
    );

    expect(screen.queryByRole('button', { name: 'Knowledge Base' })).not.toBeInTheDocument();

    expect(screen.getByRole('link', { name: 'Search' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/projects'
    );
  });

  it('opens the background tasks panel from the header action', () => {
    render(
      <TenantHeader
        tenantId="tenant-1"
        sidebarCollapsed={false}
        onSidebarToggle={vi.fn()}
        onMobileMenuOpen={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Background tasks' }));

    expect(setPanel).toHaveBeenCalledWith(true);
  });

  it('opens the notification dropdown from the header action', () => {
    render(
      <TenantHeader
        tenantId="tenant-1"
        sidebarCollapsed={false}
        onSidebarToggle={vi.fn()}
        onMobileMenuOpen={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Notifications' }));

    expect(screen.getByRole('dialog', { name: 'Notifications' })).toBeInTheDocument();
    expect(screen.getByText('No notifications')).toBeInTheDocument();
  });

  it('renders project-level contextual navigation groups instead of tenant destinations', () => {
    render(
      <TenantHeader
        tenantId="tenant-1"
        projectId="project-1"
        sidebarCollapsed={false}
        onSidebarToggle={vi.fn()}
        onMobileMenuOpen={vi.fn()}
      />
    );

    expect(screen.getByRole('button', { name: 'Project Workspace' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Knowledge Base' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Core Operations' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Project Workspace' }));
    expect(screen.getByRole('link', { name: 'Workspaces' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/project/project-1/workspaces'
    );

    fireEvent.click(screen.getByRole('button', { name: 'Knowledge Base' }));
    expect(screen.getByRole('link', { name: 'Memories' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/project/project-1/memories'
    );
  });

  it('groups project contextual navigation in the overflow menu', () => {
    render(
      <TenantHeader
        tenantId="tenant-1"
        projectId="project-1"
        sidebarCollapsed={false}
        onSidebarToggle={vi.fn()}
        onMobileMenuOpen={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Navigation' }));

    expect(screen.getAllByText('Project Workspace').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Knowledge Base').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Configuration').length).toBeGreaterThan(0);
  });

  it('keeps blackboard reachable from derived project nav', () => {
    render(
      <TenantHeader
        tenantId="tenant-1"
        projectId="project-1"
        sidebarCollapsed={false}
        onSidebarToggle={vi.fn()}
        onMobileMenuOpen={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Project Workspace' }));

    expect(screen.getByRole('link', { name: 'Blackboard' })).toHaveAttribute(
      'href',
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

    expect(setCurrentTenant).not.toHaveBeenCalled();
    expect(clearProjects).toHaveBeenCalledTimes(1);
    expect(mockNavigate).toHaveBeenCalledWith('/tenant/tenant-2/overview');
  });

  it('does not reload the current tenant from the user dropdown', () => {
    render(
      <TenantHeader
        tenantId="tenant-1"
        sidebarCollapsed={false}
        onSidebarToggle={vi.fn()}
        onMobileMenuOpen={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'User menu' }));
    fireEvent.click(screen.getByRole('button', { name: 'Tenant One' }));

    expect(setCurrentTenant).not.toHaveBeenCalled();
    expect(clearProjects).not.toHaveBeenCalled();
    expect(mockNavigate).not.toHaveBeenCalled();
    expect(screen.queryByText('Tenant')).not.toBeInTheDocument();
  });

  it('uses the route tenant as the selected dropdown tenant while currentTenant is stale', () => {
    tenantState.currentTenant = { id: 'tenant-1', name: 'Tenant One' };

    render(
      <TenantHeader
        tenantId="tenant-2"
        sidebarCollapsed={false}
        onSidebarToggle={vi.fn()}
        onMobileMenuOpen={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'User menu' }));
    fireEvent.click(screen.getByRole('button', { name: 'Tenant Two' }));

    expect(setCurrentTenant).not.toHaveBeenCalled();
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it('exposes profile, settings and billing as links in the user menu', () => {
    render(
      <TenantHeader
        tenantId="tenant-1"
        sidebarCollapsed={false}
        onSidebarToggle={vi.fn()}
        onMobileMenuOpen={vi.fn()}
      />
    );

    const trigger = screen.getByRole('button', { name: 'User menu' });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu');

    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('link', { name: 'Profile' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/profile'
    );
    expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/settings'
    );
    expect(screen.getByRole('link', { name: 'Billing' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/billing'
    );

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('link', { name: 'Profile' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
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

    fireEvent.click(screen.getByRole('button', { name: 'Core Operations' }));
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
