import { fireEvent } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { CentralBlackboardContent } from '@/components/blackboard/CentralBlackboardContent';
import { render, screen, within } from '@/test/utils';

import type { CentralBlackboardContentProps } from '@/components/blackboard/CentralBlackboardContent';
import type { BlackboardTab } from '@/components/blackboard/BlackboardTabBar';

const workspaceActionsMock = {
  createObjective: vi.fn(),
  deleteObjective: vi.fn(),
  projectObjectiveToTask: vi.fn(),
  loadGoalCandidates: vi.fn(),
  materializeGoalCandidate: vi.fn(),
  deleteGene: vi.fn(),
  updateGene: vi.fn(),
};

vi.mock('@/stores/workspace', () => ({
  useWorkspaceActions: () => workspaceActionsMock,
  useWorkspaceGoalCandidates: () => [],
  useWorkspaceGoalCandidatesLoading: () => false,
  useWorkspaceGoalCandidatesError: () => null,
  useWorkspaceStore: (selector: (state: any) => unknown) =>
    selector({
      chatMessages: [],
      loadChatMessages: vi.fn(),
    }),
}));

vi.mock('@/components/ui/lazyAntd', () => ({
  useLazyMessage: () => ({
    error: vi.fn(),
  }),
}));

vi.mock('@/pages/tenant/WorkspaceSettings', () => ({
  WorkspaceSettingsPanel: () => <div>Workspace settings</div>,
}));

vi.mock('@/components/workspace/chat/ChatPanel', () => ({
  ChatPanel: () => <div>Chat panel</div>,
}));

vi.mock('@/components/blackboard/tabs/CollaborationOverviewTab', () => ({
  CollaborationOverviewTab: () => <div>Collaboration overview</div>,
}));

vi.mock('@/components/workspace/genes/GeneList', () => ({
  GeneList: () => <div>Gene list</div>,
}));

vi.mock('@/components/workspace/MemberPanel', () => ({
  MemberPanel: () => <div>Member panel</div>,
}));

vi.mock('@/components/workspace/objectives/ObjectiveCreateModal', () => ({
  ObjectiveCreateModal: (props: { open: boolean }) => (
    <div data-testid="objective-create-modal" data-open={props.open}>
      {props.open ? 'ObjectiveCreateModal open' : null}
    </div>
  ),
}));

vi.mock('@/components/workspace/objectives/ObjectiveList', () => ({
  ObjectiveList: (props: { onCreate?: () => void }) => (
    <div>
      Objective list
      {props.onCreate && (
        <button type="button" data-testid="mock-create-objective" onClick={props.onCreate}>
          Add objective
        </button>
      )}
    </div>
  ),
}));

vi.mock('@/components/workspace/presence/PresenceBar', () => ({
  PresenceBar: () => <div>Presence bar</div>,
}));

vi.mock('@/components/workspace/TaskBoard', () => ({
  TaskBoard: () => <div>Task board</div>,
}));

vi.mock('@/components/blackboard/tabs/SharedFileBrowser', () => ({
  SharedFileBrowser: () => <div>Shared files browser</div>,
}));

vi.mock('@/components/blackboard/WorkstationArrangementBoard', () => ({
  WorkstationArrangementBoard: () => <div>Workstation arrangement board</div>,
}));

function defaultProps(
  overrides: Partial<CentralBlackboardContentProps> = {}
): CentralBlackboardContentProps {
  return {
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    workspace: { id: 'workspace-1', name: 'Central board' } as any,
    posts: [],
    repliesByPostId: {},
    loadedReplyPostIds: {},
    tasks: [],
    objectives: [],
    genes: [],
    agents: [],
    topologyNodes: [],
    topologyEdges: [],
    activeTab: 'goals',
    onActiveTabChange: vi.fn(),
    agentWorkspacePath: '/tenant/tenant-1/project/project-1/agent',
    onLoadReplies: vi.fn().mockResolvedValue(true),
    onCreatePost: vi.fn().mockResolvedValue(true),
    onCreateReply: vi.fn().mockResolvedValue(true),
    onDeletePost: vi.fn().mockResolvedValue(true),
    onPinPost: vi.fn().mockResolvedValue(undefined),
    onUnpinPost: vi.fn().mockResolvedValue(undefined),
    onDeleteReply: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

function getTabByName(name: RegExp): HTMLElement {
  const tablist = screen.getByRole('tablist');
  return within(tablist).getByRole('tab', { name });
}

describe('CentralBlackboardContent', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('auto-loads goal candidates when goals tab is active', () => {
    render(<CentralBlackboardContent {...defaultProps()} />);

    expect(workspaceActionsMock.loadGoalCandidates).toHaveBeenCalledWith('workspace-1');
  });

  it('renders the tablist with all blackboard tab controls', () => {
    render(<CentralBlackboardContent {...defaultProps()} />);

    const tablist = screen.getByRole('tablist');
    const tabs = within(tablist).getAllByRole('tab');

    expect(tabs.length).toBeGreaterThan(0);
  });

  it('renders ObjectiveList + TaskBoard when activeTab is goals', () => {
    render(<CentralBlackboardContent {...defaultProps({ activeTab: 'goals' })} />);

    expect(screen.getByText('Objective list')).toBeInTheDocument();
    expect(screen.getByText('Task board')).toBeInTheDocument();
  });

  it('renders CollaborationOverviewTab when activeTab is collaboration', () => {
    render(<CentralBlackboardContent {...defaultProps({ activeTab: 'collaboration' })} />);

    expect(screen.getByText('Collaboration overview')).toBeInTheDocument();
  });

  it('renders MemberPanel when activeTab is members', () => {
    render(<CentralBlackboardContent {...defaultProps({ activeTab: 'members' })} />);

    expect(screen.getByText('Member panel')).toBeInTheDocument();
  });

  it('renders GeneList when activeTab is genes', () => {
    render(<CentralBlackboardContent {...defaultProps({ activeTab: 'genes' })} />);

    expect(screen.getByText('Gene list')).toBeInTheDocument();
  });

  it('renders SharedFileBrowser when activeTab is files', () => {
    render(<CentralBlackboardContent {...defaultProps({ activeTab: 'files' })} />);

    expect(screen.getByText('Shared files browser')).toBeInTheDocument();
  });

  it('renders PresenceBar when activeTab is status', () => {
    render(<CentralBlackboardContent {...defaultProps({ activeTab: 'status' })} />);

    expect(screen.getByText('Presence bar')).toBeInTheDocument();
  });

  it('renders WorkstationArrangementBoard when activeTab is topology', () => {
    render(<CentralBlackboardContent {...defaultProps({ activeTab: 'topology' })} />);

    expect(screen.getByText('Workstation arrangement board')).toBeInTheDocument();
  });

  it('renders WorkspaceSettingsPanel when activeTab is settings', () => {
    render(<CentralBlackboardContent {...defaultProps({ activeTab: 'settings' })} />);

    expect(screen.getByText('Workspace settings')).toBeInTheDocument();
  });

  it('calls onActiveTabChange when a different tab is clicked', () => {
    const onActiveTabChange = vi.fn();
    render(
      <CentralBlackboardContent
        {...defaultProps({ activeTab: 'goals', onActiveTabChange })}
      />
    );

    fireEvent.click(getTabByName(/members/i));

    expect(onActiveTabChange).toHaveBeenCalledWith('members' satisfies BlackboardTab);
  });

  it('opens ObjectiveCreateModal when goals tab triggers create', () => {
    render(<CentralBlackboardContent {...defaultProps({ activeTab: 'goals' })} />);

    const createModal = screen.getByTestId('objective-create-modal');
    expect(createModal.getAttribute('data-open')).toBe('false');

    fireEvent.click(screen.getByTestId('mock-create-objective'));

    expect(createModal.getAttribute('data-open')).toBe('true');
  });
});
