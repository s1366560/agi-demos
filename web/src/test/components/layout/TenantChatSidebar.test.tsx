import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react';

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { TenantChatSidebar } from '@/components/layout/TenantChatSidebar';

import { fireEvent, render, screen, waitFor } from '../../utils';

const { modalConfirm } = vi.hoisted(() => ({
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
  useCurrentWorkspace: () => ({ id: 'ws-current' }),
  useWorkspaces: () => [{ id: 'ws-current' }],
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
});
