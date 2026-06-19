import {
  StrictMode,
  useEffect,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
} from 'react';

import { render as rtlRender } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';

import { TenantChatSidebar } from '@/components/layout/TenantChatSidebar';
import { projectAPI } from '@/services/api';

import { act, fireEvent, render, screen, waitFor } from '../../utils';

const { formatDistanceToNowMock, loadWorkspaceSurfaceMock, modalConfirm } = vi.hoisted(() => ({
  formatDistanceToNowMock: vi.fn(() => 'just now'),
  loadWorkspaceSurfaceMock: vi.fn(),
  modalConfirm: vi.fn(),
}));

const agentState = {
  activeConversationId: 'conv-1',
  setActiveConversation: vi.fn(),
  loadConversations: vi.fn(),
  loadMoreConversations: vi.fn(),
  createNewConversation: vi.fn(),
  deleteConversation: vi.fn(),
  renameConversation: vi.fn(),
};

const conversationsState = {
  conversations: [
    {
      id: 'conv-1',
      title: 'Conversation One',
      created_at: '2026-04-17T00:00:00.000Z',
      status: 'idle',
    },
  ],
  conversationsLoading: false,
  hasMoreConversations: false,
  reset: vi.fn(),
};

const projectState = {
  projects: [{ id: 'project-1', name: 'Project One', tenant_id: 'tenant-1' }],
  currentProject: { id: 'project-1', name: 'Project One', tenant_id: 'tenant-1' },
  listProjects: vi.fn(),
  setCurrentProject: vi.fn(),
};

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string | Record<string, unknown>) => {
      if (typeof fallback === 'string') {
        return fallback || key;
      }
      if (fallback && typeof fallback.defaultValue === 'string') {
        return fallback.defaultValue.replace(/{{(.*?)}}/g, (_match, rawKey: string) => {
          const value = fallback[rawKey.trim()];
          return value === undefined || value === null ? '' : String(value);
        });
      }
      return key;
    },
  }),
}));

vi.mock('@/stores/agentV3', () => ({
  useAgentV3Store: (selector: (state: typeof agentState) => unknown) => selector(agentState),
}));

vi.mock('@/stores/agent/conversationsStore', () => ({
  useConversationsStore: (selector: (state: typeof conversationsState) => unknown) =>
    selector(conversationsState),
}));

vi.mock('@/stores/project', () => ({
  useProjectStore: (selector?: (state: typeof projectState) => unknown) =>
    selector ? selector(projectState) : projectState,
}));

vi.mock('@/services/api', () => ({
  projectAPI: {
    list: vi.fn(),
  },
}));

vi.mock('@/stores/workspace', () => ({
  useCurrentWorkspace: () => ({ id: 'ws-current', name: 'Workspace Alpha' }),
  useWorkspaceActions: () => ({
    loadWorkspaceSurface: loadWorkspaceSurfaceMock,
  }),
  useWorkspaceTasks: () => [
    {
      id: 'node-b2768f4c07e7',
      workspace_id: 'ws-current',
      title: 'Fix Drone deploy pipeline',
      status: 'in_progress',
      metadata: {},
      created_at: '2026-04-17T00:00:00.000Z',
    },
  ],
  useWorkspaces: () => [{ id: 'ws-current', name: 'Workspace Alpha' }],
}));

vi.mock('@/utils/agentWorkspacePath', () => ({
  buildAgentWorkspacePath: ({
    tenantId,
    projectId,
    conversationId,
    workspaceId,
  }: {
    tenantId?: string;
    projectId?: string;
    conversationId?: string;
    workspaceId?: string | null;
  }) => {
    const basePath = tenantId ? `/tenant/${tenantId}/agent-workspace` : '/tenant/agent-workspace';
    const conversationPath = conversationId ? `${basePath}/${conversationId}` : basePath;
    const params = new URLSearchParams();
    if (projectId) params.set('projectId', projectId);
    if (workspaceId) params.set('workspaceId', workspaceId);
    const query = params.toString();
    return query ? `${conversationPath}?${query}` : conversationPath;
  },
}));

vi.mock('@/utils/date', () => ({
  formatDistanceToNow: (value: string) => formatDistanceToNowMock(value),
}));

vi.mock('antd', () => ({
  Modal: Object.assign(
    ({ children, open }: { children: ReactNode; open?: boolean }) =>
      open ? <div>{children}</div> : null,
    {
      confirm: modalConfirm,
    }
  ),
}));

vi.mock('@/components/agent/Resizer', () => ({
  Resizer: () => null,
}));

vi.mock('@/components/ui/lazyAntd', () => ({
  LazyButton: ({
    children,
    icon,
    ...props
  }: ButtonHTMLAttributes<HTMLButtonElement> & { icon?: ReactNode }) => (
    <button type="button" {...props}>
      {icon}
      {children}
    </button>
  ),
  LazyBadge: () => <span>processing</span>,
  LazyDropdown: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  LazySelect: ({
    value,
    onChange,
    options = [],
    disabled,
    loading,
    notFoundContent,
    onSearch,
    searchValue,
    showSearch,
    popupRender,
  }: {
    value?: string;
    onChange?: (value: string) => void;
    onSearch?: (value: string) => void;
    options?: Array<{ value: string; label: ReactNode }>;
    disabled?: boolean;
    loading?: boolean;
    notFoundContent?: ReactNode;
    searchValue?: string;
    showSearch?:
      | boolean
      | {
          onSearch?: ((value: string) => void) | undefined;
          searchValue?: string | undefined;
        };
    popupRender?: (menu: ReactNode) => ReactNode;
  }) => {
    const searchHandler =
      onSearch ??
      (typeof showSearch === 'object' && showSearch !== null ? showSearch.onSearch : undefined);
    const resolvedSearchValue =
      searchValue ??
      (typeof showSearch === 'object' && showSearch !== null ? showSearch.searchValue : undefined);
    const menu = (
      <select
        aria-label="Project switcher"
        value={value ?? ''}
        disabled={disabled}
        onChange={(event) => {
          onChange?.(event.target.value);
        }}
      >
        {options.length > 0 ? (
          options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.value}
            </option>
          ))
        ) : (
          <option value="" disabled>
            {notFoundContent}
          </option>
        )}
      </select>
    );

    return (
      <div>
        {showSearch ? (
          <input
            aria-label="Project switcher search"
            value={resolvedSearchValue ?? ''}
            disabled={disabled}
            onChange={(event) => {
              searchHandler?.(event.target.value);
            }}
          />
        ) : null}
        {loading ? <span>Searching projects...</span> : null}
        {popupRender ? popupRender(menu) : menu}
      </div>
    );
  },
  LazyInput: (props: InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
}));

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{`${location.pathname}${location.search}`}</div>;
}

function TenantChatSidebarRouteHarness({ route, tenantId }: { route: string; tenantId: string }) {
  const navigate = useNavigate();

  useEffect(() => {
    void navigate(route, { replace: true });
  }, [navigate, route]);

  return <TenantChatSidebar tenantId={tenantId} mobile />;
}

describe('TenantChatSidebar', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (projectAPI.list as any).mockReset();
    formatDistanceToNowMock.mockReturnValue('just now');
    agentState.activeConversationId = 'conv-1';
    agentState.setActiveConversation.mockReset();
    agentState.createNewConversation.mockResolvedValue('conv-new');
    conversationsState.conversations = [
      {
        id: 'conv-1',
        title: 'Conversation One',
        created_at: '2026-04-17T00:00:00.000Z',
        status: 'idle',
      },
    ];
    conversationsState.conversationsLoading = false;
    conversationsState.hasMoreConversations = false;
    conversationsState.reset.mockReset();
    projectState.projects = [
      { id: 'project-1', name: 'Project One', tenant_id: 'tenant-1' },
      { id: 'project-2', name: 'Project Two', tenant_id: 'tenant-1' },
    ];
    projectState.currentProject = { id: 'project-1', name: 'Project One', tenant_id: 'tenant-1' };
  });

  it('shows tenant-context functional nav in the mobile drawer', () => {
    render(<TenantChatSidebar tenantId="tenant-1" mobile />, {
      route: '/tenant/tenant-1/agent-workspace',
    });

    expect(screen.getByRole('link', { name: 'Agent Workspace' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/agent-workspace'
    );
    expect(screen.getByRole('link', { name: 'Projects' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/projects'
    );
    expect(screen.getByRole('link', { name: 'Workspaces' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/workspaces'
    );
    expect(screen.getByRole('link', { name: 'Agent Configuration' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/agents'
    );
  });

  it('switches mobile navigation to project-context destinations on project routes', () => {
    render(<TenantChatSidebar tenantId="tenant-1" mobile />, {
      route: '/tenant/tenant-1/project/project-1/memories',
    });

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

  it('does not derive project navigation from a stale project in another tenant', () => {
    projectState.currentProject = {
      id: 'project-1',
      name: 'Project One',
      tenant_id: 'tenant-1',
    };

    render(<TenantChatSidebar tenantId="tenant-2" mobile />, {
      route: '/tenant/tenant-2/project/project-2/memories',
    });

    expect(screen.queryByRole('link', { name: 'Memories' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Agent Workspace' })).toHaveAttribute(
      'href',
      '/tenant/tenant-2/agent-workspace'
    );
  });

  it('does not load or persist a route project from another tenant', async () => {
    localStorage.removeItem('agent:tenant-2:lastProjectId');
    localStorage.removeItem('agent:tenant-2:lastProjectSelectionSource');
    projectState.projects = [
      { id: 'project-1', name: 'Project One', tenant_id: 'tenant-1' },
      { id: 'project-2', name: 'Project Two', tenant_id: 'tenant-2' },
    ];
    projectState.currentProject = {
      id: 'project-2',
      name: 'Project Two',
      tenant_id: 'tenant-2',
    };

    render(<TenantChatSidebar tenantId="tenant-2" mobile />, {
      route: '/tenant/tenant-2/agent-workspace?projectId=project-1',
    });

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    });

    expect(screen.getByRole('combobox', { name: 'Project switcher' })).toHaveValue('');
    expect(agentState.loadConversations).not.toHaveBeenCalled();
    expect(projectState.setCurrentProject).not.toHaveBeenCalled();
    expect(localStorage.getItem('agent:tenant-2:lastProjectId')).toBeNull();
    expect(localStorage.getItem('agent:tenant-2:lastProjectSelectionSource')).toBeNull();
  });

  it('keeps the project switcher above conversation history', () => {
    render(<TenantChatSidebar tenantId="tenant-1" mobile />, {
      route: '/tenant/tenant-1/agent-workspace',
    });

    const projectSwitcher = screen.getByRole('combobox', { name: 'Project switcher' });
    const conversation = screen.getByText('Conversation One');

    expect(
      projectSwitcher.compareDocumentPosition(conversation) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it('does not auto-load the first project on non-agent tenant pages', () => {
    render(<TenantChatSidebar tenantId="tenant-1" mobile />, {
      route: '/tenant/tenant-1/genes/genomes/genome-1',
    });

    expect(screen.getByRole('combobox', { name: 'Project switcher' })).toHaveValue('');
    expect(agentState.loadConversations).not.toHaveBeenCalled();
    expect(screen.queryByText('Conversation One')).not.toBeInTheDocument();
    expect(screen.getByText('Select a project to view conversations')).toBeInTheDocument();
  });

  it('does not preload project options on non-agent tenant pages', async () => {
    projectState.projects = [];
    projectState.currentProject = null;

    render(<TenantChatSidebar tenantId="tenant-1" mobile />, {
      route: '/tenant/tenant-1/overview',
    });

    await act(async () => {
      await Promise.resolve();
    });

    expect(projectState.listProjects).not.toHaveBeenCalled();
    expect(agentState.loadConversations).not.toHaveBeenCalled();
    expect(screen.getByRole('combobox', { name: 'Project switcher' })).toHaveValue('');
    expect(screen.getByRole('option', { name: 'Search to select a project' })).toBeInTheDocument();
  });

  it('clears workspace conversations after leaving the agent workspace route', async () => {
    const { rerender } = rtlRender(
      <MemoryRouter initialEntries={['/tenant/tenant-1/agent-workspace']}>
        <TenantChatSidebarRouteHarness
          tenantId="tenant-1"
          route="/tenant/tenant-1/agent-workspace"
        />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(agentState.loadConversations).toHaveBeenCalledWith(
        'project-1',
        expect.any(AbortSignal)
      );
      expect(screen.getByText('Conversation One')).toBeInTheDocument();
    });

    agentState.loadConversations.mockClear();
    conversationsState.reset.mockClear();
    agentState.setActiveConversation.mockClear();

    rerender(
      <MemoryRouter initialEntries={['/tenant/tenant-1/agent-workspace']}>
        <TenantChatSidebarRouteHarness tenantId="tenant-1" route="/tenant/tenant-1/overview" />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: 'Project switcher' })).toHaveValue('');
      expect(screen.queryByText('Conversation One')).not.toBeInTheDocument();
    });
    expect(agentState.loadConversations).not.toHaveBeenCalled();
    expect(conversationsState.reset).toHaveBeenCalled();
    expect(agentState.setActiveConversation).toHaveBeenCalledWith(null);
  });

  it('clears project search state after leaving the agent workspace route', async () => {
    const hiddenProject = {
      id: 'project-hidden',
      name: 'Hidden Authorized Project',
      tenant_id: 'tenant-1',
    };
    (projectAPI.list as any).mockResolvedValue({
      projects: [hiddenProject],
      total: 1,
      page: 1,
      page_size: 100,
    });

    const { rerender } = rtlRender(
      <MemoryRouter initialEntries={['/tenant/tenant-1/agent-workspace']}>
        <TenantChatSidebarRouteHarness
          tenantId="tenant-1"
          route="/tenant/tenant-1/agent-workspace"
        />
      </MemoryRouter>
    );

    fireEvent.change(screen.getByRole('textbox', { name: 'Search projects' }), {
      target: { value: 'Hidden Authorized' },
    });

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 300));
    });

    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'Hidden Authorized Project' })).toBeInTheDocument();
    });

    rerender(
      <MemoryRouter initialEntries={['/tenant/tenant-1/agent-workspace']}>
        <TenantChatSidebarRouteHarness tenantId="tenant-1" route="/tenant/tenant-1/overview" />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByRole('textbox', { name: 'Search projects' })).toHaveValue('');
      expect(
        screen.queryByRole('option', { name: 'Hidden Authorized Project' })
      ).not.toBeInTheDocument();
    });
  });

  it('keeps a searched project selectable after the search query is cleared', async () => {
    const hiddenProject = {
      id: 'project-hidden',
      name: 'Hidden Authorized Project',
      tenant_id: 'tenant-1',
    };
    (projectAPI.list as any).mockResolvedValue({
      projects: [hiddenProject],
      total: 1,
      page: 1,
      page_size: 100,
    });

    render(<TenantChatSidebar tenantId="tenant-1" mobile />, {
      route: '/tenant/tenant-1/agent-workspace',
    });

    fireEvent.change(screen.getByRole('textbox', { name: 'Search projects' }), {
      target: { value: 'Hidden Authorized' },
    });

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 300));
    });

    const hiddenOption = await screen.findByRole('option', {
      name: 'Hidden Authorized Project',
    });
    expect(hiddenOption).toBeInTheDocument();

    fireEvent.change(screen.getByRole('combobox', { name: 'Project switcher' }), {
      target: { value: 'project-hidden' },
    });

    await waitFor(() => {
      expect(screen.getByRole('textbox', { name: 'Search projects' })).toHaveValue('');
      expect(screen.getByRole('combobox', { name: 'Project switcher' })).toHaveValue(
        'project-hidden'
      );
      expect(screen.getByRole('option', { name: 'Hidden Authorized Project' })).toBeInTheDocument();
    });
    expect(projectState.setCurrentProject).toHaveBeenCalledWith(hiddenProject);
    expect(screen.getAllByText('Hidden Authorized Project').length).toBeGreaterThanOrEqual(2);
  });

  it('preloads the project switcher window on agent workspace pages', async () => {
    projectState.projects = [];
    projectState.currentProject = null;

    render(<TenantChatSidebar tenantId="tenant-1" mobile />, {
      route: '/tenant/tenant-1/agent-workspace',
    });

    await waitFor(() => {
      expect(projectState.listProjects).toHaveBeenCalledWith('tenant-1', {
        page: 1,
        page_size: 25,
      });
    });
  });

  it('deduplicates project switcher options by project id', () => {
    projectState.projects = [
      { id: 'Project Aurora', name: 'Project Aurora', tenant_id: 'tenant-1' },
      { id: 'Project Aurora', name: 'Project Aurora', tenant_id: 'tenant-1' },
    ];
    projectState.currentProject = {
      id: 'Project Aurora',
      name: 'Project Aurora',
      tenant_id: 'tenant-1',
    };

    render(<TenantChatSidebar tenantId="tenant-1" mobile />, {
      route: '/tenant/tenant-1/agent-workspace',
    });

    const options = screen.getAllByRole('option');

    expect(options).toHaveLength(1);
    expect(options[0]).toHaveValue('Project Aurora');
  });

  it('limits default project options while preserving the active project', () => {
    const projects = Array.from({ length: 60 }, (_, index) => ({
      id: `project-${String(index + 1)}`,
      name: `Project ${String(index + 1)}`,
      tenant_id: 'tenant-1',
    }));
    const activeProject = projects[59];
    if (!activeProject) throw new Error('Expected active project fixture');

    projectState.projects = projects;
    projectState.currentProject = activeProject;

    render(<TenantChatSidebar tenantId="tenant-1" mobile />, {
      route: '/tenant/tenant-1/agent-workspace',
    });

    const options = screen.getAllByRole('option');

    expect(options).toHaveLength(25);
    expect(options[0]).toHaveValue('project-60');
    expect(screen.getByRole('option', { name: 'Project 60' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Project 59' })).not.toBeInTheDocument();
  });

  it('searches authorized projects that are not in the loaded switcher list', async () => {
    const hiddenProject = {
      id: 'project-hidden',
      name: 'Hidden Authorized Project',
      tenant_id: 'tenant-1',
    };
    projectState.projects = [{ id: 'project-1', name: 'Project One', tenant_id: 'tenant-1' }];
    projectState.currentProject = {
      id: 'project-1',
      name: 'Project One',
      tenant_id: 'tenant-1',
    };
    (projectAPI.list as any).mockResolvedValue({
      projects: [hiddenProject],
      total: 1,
      page: 1,
      page_size: 100,
    });

    render(<TenantChatSidebar tenantId="tenant-1" mobile />, {
      route: '/tenant/tenant-1/agent-workspace',
    });

    fireEvent.change(screen.getByRole('textbox', { name: 'Search projects' }), {
      target: { value: 'Hidden Authorized' },
    });

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 300));
    });

    await waitFor(() => {
      expect(projectAPI.list).toHaveBeenCalledWith('tenant-1', {
        page: 1,
        page_size: 100,
        search: 'Hidden Authorized',
      });
    });
    expect(screen.getByRole('option', { name: 'Hidden Authorized Project' })).toBeInTheDocument();

    fireEvent.change(screen.getByRole('combobox', { name: 'Project switcher' }), {
      target: { value: 'project-hidden' },
    });

    expect(projectState.setCurrentProject).toHaveBeenCalledWith(hiddenProject);
    expect(localStorage.getItem('agent:tenant-1:lastProjectId')).toBe(
      JSON.stringify('project-hidden')
    );
  });

  it('opens the agent workspace when selecting a searched project from a tenant page', async () => {
    const hiddenProject = {
      id: 'project-hidden',
      name: 'Hidden Authorized Project',
      tenant_id: 'tenant-1',
    };
    (projectAPI.list as any).mockResolvedValue({
      projects: [hiddenProject],
      total: 1,
      page: 1,
      page_size: 100,
    });

    render(
      <>
        <TenantChatSidebar tenantId="tenant-1" mobile />
        <LocationProbe />
      </>,
      {
        route: '/tenant/tenant-1/overview',
      }
    );

    fireEvent.change(screen.getByRole('textbox', { name: 'Search projects' }), {
      target: { value: 'Hidden Authorized' },
    });

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 300));
    });

    fireEvent.change(await screen.findByRole('combobox', { name: 'Project switcher' }), {
      target: { value: 'project-hidden' },
    });

    await waitFor(() => {
      expect(screen.getByTestId('location-probe')).toHaveTextContent(
        '/tenant/tenant-1/agent-workspace?projectId=project-hidden'
      );
    });
    expect(projectState.setCurrentProject).toHaveBeenCalledWith(hiddenProject);
  });

  it('loads additional authorized project search pages', async () => {
    const firstPageProjects = Array.from({ length: 100 }, (_, index) => ({
      id: `search-project-${index.toString()}`,
      name: `Search Project ${index.toString()}`,
      tenant_id: 'tenant-1',
    }));
    const secondPageProject = {
      id: 'search-project-100',
      name: 'Search Project 100',
      tenant_id: 'tenant-1',
    };
    (projectAPI.list as any)
      .mockResolvedValueOnce({
        projects: firstPageProjects,
        total: 101,
        page: 1,
        page_size: 100,
      })
      .mockResolvedValueOnce({
        projects: [secondPageProject],
        total: 101,
        page: 2,
        page_size: 100,
      });

    render(<TenantChatSidebar tenantId="tenant-1" mobile />, {
      route: '/tenant/tenant-1/agent-workspace',
    });

    fireEvent.change(screen.getByRole('textbox', { name: 'Search projects' }), {
      target: { value: 'Search Project' },
    });

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 300));
    });

    await waitFor(() => {
      expect(screen.getByText('Showing 100 of 101 projects')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Load more' })).toBeEnabled();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Load more' }));

    await waitFor(() => {
      expect(projectAPI.list).toHaveBeenLastCalledWith('tenant-1', {
        page: 2,
        page_size: 100,
        search: 'Search Project',
      });
      expect(screen.getByRole('option', { name: 'Search Project 100' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
    });

    fireEvent.change(screen.getByRole('combobox', { name: 'Project switcher' }), {
      target: { value: 'search-project-100' },
    });

    expect(projectState.setCurrentProject).toHaveBeenCalledWith(secondPageProject);
  });

  it('keeps the conversation list visible while switching session history', () => {
    conversationsState.conversationsLoading = false;

    render(<TenantChatSidebar tenantId="tenant-1" mobile />, {
      route: '/tenant/tenant-1/agent-workspace/conv-1?projectId=project-1',
    });

    expect(screen.getByText('Conversation One')).toBeInTheDocument();
    expect(screen.queryByText('No conversations yet')).not.toBeInTheDocument();
  });

  it('displays conversation activity time from updated_at when available', () => {
    conversationsState.conversations = [
      {
        id: 'conv-active-time',
        title: 'Conversation Activity Time',
        created_at: '2026-04-17T00:00:00.000Z',
        updated_at: '2026-04-18T00:00:00.000Z',
        status: 'active',
      },
    ];

    render(<TenantChatSidebar tenantId="tenant-1" mobile />, {
      route: '/tenant/tenant-1/agent-workspace?projectId=project-1',
    });

    expect(screen.getByText('Conversation Activity Time')).toBeInTheDocument();
    expect(formatDistanceToNowMock).toHaveBeenCalledWith('2026-04-18T00:00:00.000Z');
  });

  it('does not render conversation icons or tooltips when collapsed', () => {
    render(<TenantChatSidebar tenantId="tenant-1" collapsed />, {
      route: '/tenant/tenant-1/agent-workspace',
    });

    expect(screen.queryByText('Conversation One')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Conversation One/ })).not.toBeInTheDocument();
  });

  it('uses the URL project id when creating a new conversation', async () => {
    render(<TenantChatSidebar tenantId="tenant-1" mobile />, {
      route: '/tenant/tenant-1/agent-workspace?projectId=project-2',
    });

    const newChatButton = await screen.findByRole('button', { name: 'New Chat' });
    await waitFor(() => {
      expect(newChatButton).toBeEnabled();
    });

    fireEvent.click(newChatButton);

    await waitFor(() => {
      expect(agentState.createNewConversation).toHaveBeenCalledWith('project-2');
    });
    expect(projectState.setCurrentProject).toHaveBeenCalledWith({
      id: 'project-2',
      name: 'Project Two',
      tenant_id: 'tenant-1',
    });
  });

  it('persists project selection under the active tenant scope', async () => {
    localStorage.setItem('agent:lastProjectId', 'legacy-project');

    render(<TenantChatSidebar tenantId="tenant-1" mobile />, {
      route: '/tenant/tenant-1/agent-workspace',
    });

    const projectSwitcher = await screen.findByRole('combobox', { name: 'Project switcher' });
    await waitFor(() => {
      expect(projectSwitcher).toHaveValue('project-1');
    });

    fireEvent.change(projectSwitcher, { target: { value: 'project-2' } });

    expect(localStorage.getItem('agent:tenant-1:lastProjectId')).toBe(JSON.stringify('project-2'));
    expect(localStorage.getItem('agent:tenant-1:lastProjectSelectionSource')).toBe(
      JSON.stringify('manual')
    );
    expect(localStorage.getItem('agent:lastProjectId')).toBeNull();
  });

  it('resets selected project when the tenant scope changes', async () => {
    projectState.projects = [
      { id: 'project-1', name: 'Project One', tenant_id: 'tenant-1' },
      { id: 'project-2', name: 'Project Two', tenant_id: 'tenant-2' },
    ];
    projectState.currentProject = { id: 'project-1', name: 'Project One', tenant_id: 'tenant-1' };

    const { rerender } = rtlRender(
      <MemoryRouter initialEntries={['/tenant/tenant-1/agent-workspace']}>
        <TenantChatSidebarRouteHarness
          tenantId="tenant-1"
          route="/tenant/tenant-1/agent-workspace"
        />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(agentState.loadConversations).toHaveBeenCalledWith(
        'project-1',
        expect.any(AbortSignal)
      );
    });
    agentState.loadConversations.mockClear();

    rerender(
      <MemoryRouter initialEntries={['/tenant/tenant-1/agent-workspace']}>
        <TenantChatSidebarRouteHarness
          tenantId="tenant-2"
          route="/tenant/tenant-2/agent-workspace"
        />
      </MemoryRouter>
    );

    const projectSwitcher = await screen.findByRole('combobox', { name: 'Project switcher' });
    await waitFor(() => {
      expect(projectSwitcher).toHaveValue('project-2');
      expect(agentState.loadConversations).toHaveBeenCalledWith(
        'project-2',
        expect.any(AbortSignal)
      );
    });
    expect(projectState.setCurrentProject).toHaveBeenLastCalledWith({
      id: 'project-2',
      name: 'Project Two',
      tenant_id: 'tenant-2',
    });
    expect(localStorage.getItem('agent:tenant-2:lastProjectId')).toBeNull();
    expect(localStorage.getItem('agent:tenant-2:lastProjectSelectionSource')).toBeNull();
  });

  it('clears stale conversations when the new tenant has no valid projects', async () => {
    projectState.projects = [{ id: 'project-1', name: 'Project One', tenant_id: 'tenant-1' }];
    projectState.currentProject = { id: 'project-1', name: 'Project One', tenant_id: 'tenant-1' };

    const { rerender } = rtlRender(
      <MemoryRouter initialEntries={['/tenant/tenant-1/agent-workspace']}>
        <TenantChatSidebarRouteHarness
          tenantId="tenant-1"
          route="/tenant/tenant-1/agent-workspace"
        />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('Conversation One')).toBeInTheDocument();
    });
    conversationsState.reset.mockClear();
    agentState.setActiveConversation.mockClear();

    projectState.projects = [];
    projectState.currentProject = null;

    rerender(
      <MemoryRouter initialEntries={['/tenant/tenant-1/agent-workspace']}>
        <TenantChatSidebarRouteHarness
          tenantId="tenant-2"
          route="/tenant/tenant-2/agent-workspace"
        />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: 'Project switcher' })).toBeDisabled();
      expect(screen.queryByText('Conversation One')).not.toBeInTheDocument();
    });
    expect(screen.getByText('Select a project to view conversations')).toBeInTheDocument();
    expect(conversationsState.reset).toHaveBeenCalled();
    expect(agentState.setActiveConversation).toHaveBeenCalledWith(null);
  });

  it('does not carry workspace context when creating a new conversation', async () => {
    render(
      <>
        <TenantChatSidebar tenantId="tenant-1" mobile />
        <LocationProbe />
      </>,
      {
        route: '/tenant/tenant-1/agent-workspace?projectId=project-1&workspaceId=ws-current',
      }
    );

    const newChatButton = await screen.findByRole('button', { name: 'New Chat' });
    await waitFor(() => {
      expect(newChatButton).toBeEnabled();
    });

    fireEvent.click(newChatButton);

    await waitFor(() => {
      expect(agentState.createNewConversation).toHaveBeenCalledWith('project-1');
      expect(screen.getByTestId('location-probe')).toHaveTextContent(
        '/tenant/tenant-1/agent-workspace/conv-new?projectId=project-1'
      );
    });
    expect(screen.getByTestId('location-probe')).not.toHaveTextContent('workspaceId=');
  });

  it('groups workspace conversations by workspace only with collapsible sections', () => {
    conversationsState.conversations = [
      {
        id: 'workspace-verifier:ws-current:node-b2768f4c07e7:agent-1:attempt-1',
        title: 'Workspace Verification Gate - node-b2768f4c07e7',
        created_at: '2026-04-17T00:00:00.000Z',
        status: 'active',
        workspace_id: 'ws-current',
        linked_workspace_task_id: 'node-b2768f4c07e7',
      },
      {
        id: 'workspace-chat:ws-current:agent-1',
        title: 'Workspace Chat - Verifier',
        created_at: '2026-04-17T00:00:00.000Z',
        status: 'idle',
        workspace_id: 'ws-current',
      },
      {
        id: 'workspace-contract:supervisor-decision:tenant-1:project-1:ws-current:plan-1:abc',
        title: 'Workspace Supervisor Decision - node-b2768f4c07e7',
        created_at: '2026-04-17T00:00:00.000Z',
        status: 'active',
        workspace_id: 'ws-current',
        linked_workspace_task_id: 'node-b2768f4c07e7',
      },
    ];

    render(<TenantChatSidebar tenantId="tenant-1" mobile />, {
      route: '/tenant/tenant-1/agent-workspace?projectId=project-1&workspaceId=ws-current',
    });

    expect(screen.getByRole('button', { name: /Workspace Alpha/ })).toHaveAttribute(
      'aria-expanded',
      'true'
    );
    expect(screen.getAllByText('Workspace Alpha')).toHaveLength(1);
    expect(screen.getAllByText('Fix Drone deploy pipeline')).toHaveLength(2);
    expect(screen.getByText('Workspace task')).toBeInTheDocument();
    expect(screen.getByText('Verifier')).toBeInTheDocument();
    expect(screen.getByText('Supervisor')).toBeInTheDocument();
    expect(screen.getByText('Chat')).toBeInTheDocument();
    expect(screen.getAllByText('just now')).toHaveLength(3);
    expect(
      screen.queryByText('Workspace Verification Gate - node-b2768f4c07e7')
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText('Workspace Supervisor Decision - node-b2768f4c07e7')
    ).not.toBeInTheDocument();
    expect(screen.queryByText('node-b2768f4c07e7')).not.toBeInTheDocument();

    const groupButton = screen.getByRole('button', { name: /Workspace Alpha/ });
    expect(groupButton).not.toBeNull();
    fireEvent.click(groupButton as HTMLElement);

    expect(groupButton).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Fix Drone deploy pipeline')).not.toBeInTheDocument();
    expect(screen.queryByText('Workspace task')).not.toBeInTheDocument();
    expect(screen.queryByText('Verifier')).not.toBeInTheDocument();
    expect(screen.queryByText('Supervisor')).not.toBeInTheDocument();
    expect(screen.queryByText('Chat')).not.toBeInTheDocument();
  });

  it('does not re-clean collapsed workspace groups when group ids are unchanged', () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    conversationsState.conversations = [
      {
        id: 'workspace-chat:ws-current:agent-1',
        title: 'Workspace Chat - Verifier',
        created_at: '2026-04-17T00:00:00.000Z',
        status: 'idle',
        workspace_id: 'ws-current',
      },
    ];

    const sidebar = (
      <StrictMode>
        <MemoryRouter
          initialEntries={[
            '/tenant/tenant-1/agent-workspace?projectId=project-1&workspaceId=ws-current',
          ]}
        >
          <TenantChatSidebar tenantId="tenant-1" mobile />
        </MemoryRouter>
      </StrictMode>
    );
    const { rerender } = rtlRender(sidebar);

    for (let index = 0; index < 5; index += 1) {
      rerender(sidebar);
    }

    expect(screen.getByRole('button', { name: /Workspace Alpha/ })).toBeInTheDocument();
    expect(
      consoleErrorSpy.mock.calls.some((args) =>
        String(args[0]).includes('Maximum update depth exceeded')
      )
    ).toBe(false);
    consoleErrorSpy.mockRestore();
  });

  it('uses workspace names returned by the conversation API', () => {
    conversationsState.conversations = [
      {
        id: 'workspace-chat:ws-api:agent-1',
        title: 'Workspace Chat - Verifier',
        created_at: '2026-04-17T00:00:00.000Z',
        status: 'active',
        workspace_id: 'ws-api',
        workspace_name: 'API Workspace',
      },
    ];

    render(<TenantChatSidebar tenantId="tenant-1" mobile />, {
      route: '/tenant/tenant-1/agent-workspace?projectId=project-1',
    });

    expect(screen.getByRole('button', { name: /API Workspace/ })).toBeInTheDocument();
    expect(screen.queryByText('Unknown workspace')).not.toBeInTheDocument();
  });

  it('does not move later workspace conversations ahead of newer normal conversations', () => {
    conversationsState.conversations = [
      {
        id: 'workspace-verifier:ws-current:node-b2768f4c07e7:agent-1:attempt-1',
        title: 'Workspace Verification Gate - node-b2768f4c07e7',
        created_at: '2026-04-17T03:00:00.000Z',
        status: 'active',
        workspace_id: 'ws-current',
        linked_workspace_task_id: 'node-b2768f4c07e7',
      },
      {
        id: 'normal-recent',
        title: 'Recent normal conversation',
        created_at: '2026-04-17T02:00:00.000Z',
        status: 'idle',
      },
      {
        id: 'workspace-worker:ws-current:node-b2768f4c07e7:agent-1:attempt-2',
        title: 'Workspace Worker - node-b2768f4c07e7',
        created_at: '2026-04-17T01:00:00.000Z',
        status: 'active',
        workspace_id: 'ws-current',
        linked_workspace_task_id: 'node-b2768f4c07e7',
      },
    ];

    const { container } = render(<TenantChatSidebar tenantId="tenant-1" mobile />, {
      route: '/tenant/tenant-1/agent-workspace?projectId=project-1&workspaceId=ws-current',
    });

    const sidebarText = container.textContent ?? '';
    expect(sidebarText.indexOf('Fix Drone deploy pipeline')).toBeLessThan(
      sidebarText.indexOf('Recent normal conversation')
    );
    expect(sidebarText.indexOf('Recent normal conversation')).toBeLessThan(
      sidebarText.lastIndexOf('Fix Drone deploy pipeline')
    );
  });

  it('scrolls the selected conversation into view on distant session switches', async () => {
    agentState.activeConversationId = 'conv-1';
    conversationsState.conversations = Array.from({ length: 50 }, (_, index) => {
      const ordinal = index === 39 ? 'Forty' : `${index + 1}`;
      return {
        id: `conv-${index + 1}`,
        title: `Conversation ${ordinal}`,
        created_at: '2026-04-17T00:00:00.000Z',
        status: 'idle',
      };
    });

    const getBoundingClientRect = vi
      .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockImplementation(function (this: HTMLElement) {
        if (this.classList.contains('custom-scrollbar')) {
          return {
            bottom: 100,
            height: 100,
            left: 0,
            right: 256,
            top: 0,
            width: 256,
            x: 0,
            y: 0,
            toJSON: () => ({}),
          };
        }
        if (this.textContent?.includes('Conversation Forty')) {
          const containerScrollTop =
            this.closest('.custom-scrollbar') instanceof HTMLElement
              ? this.closest('.custom-scrollbar')?.scrollTop || 0
              : 0;
          const top = 420 - containerScrollTop;
          return {
            bottom: top + 40,
            height: 40,
            left: 0,
            right: 256,
            top,
            width: 256,
            x: 0,
            y: top,
            toJSON: () => ({}),
          };
        }
        return {
          bottom: 40,
          height: 40,
          left: 0,
          right: 256,
          top: 0,
          width: 256,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        };
      });

    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get() {
        return this.classList.contains('custom-scrollbar') ? 100 : 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
      configurable: true,
      get() {
        return this.textContent?.includes('Conversation Forty') ? 40 : 0;
      },
    });

    render(<TenantChatSidebar tenantId="tenant-1" mobile />, {
      route: '/tenant/tenant-1/agent-workspace/conv-40?projectId=project-1',
    });

    const activeItem = await screen.findByText('Conversation Forty');
    const scrollContainer = activeItem.closest('.custom-scrollbar');

    expect(scrollContainer).toBeInstanceOf(HTMLElement);
    await waitFor(() => {
      expect((scrollContainer as HTMLElement).scrollTop).toBe(390);
    });

    getBoundingClientRect.mockRestore();
  });

  it('continues loading when hidden subagent sessions leave the visible list underfilled', async () => {
    conversationsState.hasMoreConversations = true;
    conversationsState.conversations = [
      {
        id: 'conv-visible',
        title: 'Visible Conversation',
        created_at: '2026-04-17T00:00:00.000Z',
        status: 'idle',
      },
    ];

    let resolveLoadMore: (() => void) | undefined;
    agentState.loadMoreConversations.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveLoadMore = resolve;
        })
    );

    render(<TenantChatSidebar tenantId="tenant-1" mobile />, {
      route: '/tenant/tenant-1/agent-workspace?projectId=project-1',
    });

    await waitFor(() => {
      expect(agentState.loadMoreConversations).toHaveBeenCalledTimes(1);
    });

    conversationsState.conversations = [
      ...conversationsState.conversations,
      {
        id: 'child-agent-session',
        title: 'Worker session',
        created_at: '2026-04-17T00:00:00.000Z',
        status: 'idle',
        parent_conversation_id: 'conv-visible',
      },
    ];

    await act(async () => {
      resolveLoadMore?.();
    });

    await waitFor(() => {
      expect(agentState.loadMoreConversations).toHaveBeenCalledTimes(2);
    });
  });

  it('caps automatic underfilled-list loading per project', async () => {
    conversationsState.hasMoreConversations = true;
    conversationsState.conversations = [
      {
        id: 'conv-visible',
        title: 'Visible Conversation',
        created_at: '2026-04-17T00:00:00.000Z',
        status: 'idle',
      },
    ];
    agentState.loadMoreConversations.mockResolvedValue(undefined);

    render(<TenantChatSidebar tenantId="tenant-1" mobile />, {
      route: '/tenant/tenant-1/agent-workspace?projectId=project-1',
    });

    await waitFor(() => {
      expect(agentState.loadMoreConversations).toHaveBeenCalledTimes(2);
    });

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 50));
    });

    expect(agentState.loadMoreConversations).toHaveBeenCalledTimes(2);
  });
});
