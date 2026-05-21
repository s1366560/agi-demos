import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react';

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { TenantChatSidebar } from '@/components/layout/TenantChatSidebar';

import { fireEvent, render, screen, waitFor } from '../../utils';

const { loadWorkspaceSurfaceMock, modalConfirm } = vi.hoisted(() => ({
  loadWorkspaceSurfaceMock: vi.fn(),
  modalConfirm: vi.fn(),
}));

const agentState = {
  activeConversationId: 'conv-1',
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
  hasMoreConversations: false,
};

const projectState = {
  projects: [{ id: 'project-1', name: 'Project One' }],
  currentProject: { id: 'project-1', name: 'Project One' },
  listProjects: vi.fn(),
  setCurrentProject: vi.fn(),
};

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback || _key,
  }),
}));

vi.mock('@/stores/agentV3', () => ({
  useAgentV3Store: (selector: (state: typeof agentState) => unknown) => selector(agentState),
}));

vi.mock('@/stores/agent/conversationsStore', () => ({
  useConversationsStore: (selector: (state: typeof conversationsState) => unknown) =>
    selector(conversationsState),
}));

vi.mock('@/stores/agent/timelineStore', () => ({
  useIsLoadingHistory: () => false,
}));

vi.mock('@/stores/project', () => ({
  useProjectStore: (selector?: (state: typeof projectState) => unknown) =>
    selector ? selector(projectState) : projectState,
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
  }: {
    tenantId?: string;
    projectId?: string;
    conversationId?: string;
  }) => `/tenant/${tenantId}/project/${projectId}/agent-workspace/${conversationId ?? ''}`,
}));

vi.mock('@/utils/date', () => ({
  formatDistanceToNow: () => 'just now',
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
  }: {
    value?: string;
    onChange?: (value: string) => void;
    options?: Array<{ value: string; label: ReactNode }>;
    disabled?: boolean;
  }) => (
    <select
      aria-label="Project switcher"
      value={value ?? ''}
      disabled={disabled}
      onChange={(event) => {
        onChange?.(event.target.value);
      }}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.value}
        </option>
      ))}
    </select>
  ),
  LazyInput: (props: InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
}));

describe('TenantChatSidebar', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    agentState.createNewConversation.mockResolvedValue('conv-new');
    conversationsState.conversations = [
      {
        id: 'conv-1',
        title: 'Conversation One',
        created_at: '2026-04-17T00:00:00.000Z',
        status: 'idle',
      },
    ];
    conversationsState.hasMoreConversations = false;
    projectState.projects = [
      { id: 'project-1', name: 'Project One' },
      { id: 'project-2', name: 'Project Two' },
    ];
    projectState.currentProject = { id: 'project-1', name: 'Project One' };
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
    });
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
    ];

    render(<TenantChatSidebar tenantId="tenant-1" mobile />, {
      route: '/tenant/tenant-1/agent-workspace?projectId=project-1&workspaceId=ws-current',
    });

    expect(screen.getByRole('button', { name: /Workspace Alpha/ })).toHaveAttribute(
      'aria-expanded',
      'true'
    );
    expect(screen.getAllByText('Workspace Alpha')).toHaveLength(1);
    expect(screen.getAllByText('Fix Drone deploy pipeline')).toHaveLength(1);
    expect(screen.getByText('Workspace task')).toBeInTheDocument();
    expect(screen.getByText('Verifier')).toBeInTheDocument();
    expect(screen.getByText('Chat')).toBeInTheDocument();
    expect(screen.getAllByText('just now')).toHaveLength(2);
    expect(
      screen.queryByText('Workspace Verification Gate - node-b2768f4c07e7')
    ).not.toBeInTheDocument();
    expect(screen.queryByText('node-b2768f4c07e7')).not.toBeInTheDocument();

    const groupButton = screen.getByRole('button', { name: /Workspace Alpha/ });
    expect(groupButton).not.toBeNull();
    fireEvent.click(groupButton as HTMLElement);

    expect(groupButton).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Fix Drone deploy pipeline')).not.toBeInTheDocument();
    expect(screen.queryByText('Workspace task')).not.toBeInTheDocument();
    expect(screen.queryByText('Verifier')).not.toBeInTheDocument();
    expect(screen.queryByText('Chat')).not.toBeInTheDocument();
  });
});
