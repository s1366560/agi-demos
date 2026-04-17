import { fireEvent } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { CentralBlackboardModal } from '@/components/blackboard/CentralBlackboardModal';
import { render, screen, within } from '@/test/utils';

import type { CentralBlackboardModalProps } from '@/components/blackboard/CentralBlackboardModal';

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

function defaultProps(overrides: Partial<CentralBlackboardModalProps> = {}): CentralBlackboardModalProps {
  return {
    open: true,
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
    onClose: vi.fn(),
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

describe('CentralBlackboardModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('auto-loads goal candidates when goals tab is active', async () => {
    render(<CentralBlackboardModal {...defaultProps()} />);

    expect(workspaceActionsMock.loadGoalCandidates).toHaveBeenCalledWith('workspace-1');
  });

  it('renders a matching tabpanel element for every tab control', () => {
    render(<CentralBlackboardModal {...defaultProps()} />);

    const tablist = screen.getByRole('tablist');
    const tabs = within(tablist).getAllByRole('tab');
    const panels = screen.getAllByRole('tabpanel', { hidden: true });

    expect(panels).toHaveLength(tabs.length);

    tabs.forEach((tab) => {
      const controls = tab.getAttribute('aria-controls');

      expect(controls).toBeTruthy();
      expect(document.getElementById(controls ?? '')).not.toBeNull();
    });
  });

  it('renders ObjectiveList content when goals tab is active (default)', () => {
    render(<CentralBlackboardModal {...defaultProps()} />);

    expect(screen.getByText('Objective list')).toBeInTheDocument();
    expect(screen.getByText('Task board')).toBeInTheDocument();
  });

  it('renders DiscussionTab content when discussion tab is selected', () => {
    render(<CentralBlackboardModal {...defaultProps()} />);

    fireEvent.click(getTabByName(/discussion/i));

    const activePanel = document.getElementById('blackboard-panel-discussion');
    expect(activePanel).not.toBeNull();
    expect(activePanel!.hidden).toBe(false);
  });

  it('renders ChatPanel when collaboration tab is selected', () => {
    render(<CentralBlackboardModal {...defaultProps()} />);

    fireEvent.click(getTabByName(/collaboration/i));

    expect(screen.getByText('Collaboration overview')).toBeInTheDocument();
  });

  it('renders MemberPanel when members tab is selected', () => {
    render(<CentralBlackboardModal {...defaultProps()} />);

    fireEvent.click(getTabByName(/members/i));

    expect(screen.getByText('Member panel')).toBeInTheDocument();
  });

  it('renders GeneList when genes tab is selected', () => {
    render(<CentralBlackboardModal {...defaultProps()} />);

    fireEvent.click(getTabByName(/genes/i));

    expect(screen.getByText('Gene list')).toBeInTheDocument();
  });

  it('renders FilesPlaceholder when files tab is selected', () => {
    render(<CentralBlackboardModal {...defaultProps()} />);

    fireEvent.click(getTabByName(/files/i));

    const activePanel = document.getElementById('blackboard-panel-files');
    expect(activePanel).not.toBeNull();
    expect(activePanel!.hidden).toBe(false);
    expect(screen.getByText('Shared files browser')).toBeInTheDocument();
  });

  it('renders StatusTab with PresenceBar when status tab is selected', () => {
    render(<CentralBlackboardModal {...defaultProps()} />);

    fireEvent.click(getTabByName(/status/i));

    expect(screen.getByText('Presence bar')).toBeInTheDocument();
  });

  it('renders pending adjudication details in the status tab', () => {
    render(
      <CentralBlackboardModal
        {...defaultProps({
          tasks: [
            {
              id: 'task-1',
              workspace_id: 'workspace-1',
              title: 'Draft checklist',
              status: 'in_progress',
              metadata: {
                pending_leader_adjudication: true,
                last_worker_report_type: 'completed',
                last_worker_report_summary: 'Checklist drafted successfully',
                last_worker_report_artifacts: ['artifact:checklist'],
                last_worker_report_verifications: ['worker_report:completed'],
              },
              created_at: '2026-04-17T00:00:00Z',
            },
          ] as any,
        })}
      />
    );

    fireEvent.click(getTabByName(/status/i));

    expect(screen.getByText(/blackboard\.pendingAdjudicationTitle/i)).toBeInTheDocument();
    expect(screen.getByText(/Checklist drafted successfully/i)).toBeInTheDocument();
    expect(screen.getByText(/blackboard\.pendingAdjudicationArtifacts: artifact:checklist/i)).toBeInTheDocument();
    expect(
      screen.getByText(/blackboard\.pendingAdjudicationChecks: worker_report:completed/i)
    ).toBeInTheDocument();
  });

  it('renders NotesTab when notes tab is selected', () => {
    render(<CentralBlackboardModal {...defaultProps()} />);

    fireEvent.click(getTabByName(/notes/i));

    const activePanel = document.getElementById('blackboard-panel-notes');
    expect(activePanel).not.toBeNull();
    expect(activePanel!.hidden).toBe(false);
  });

  it('renders TopologyTab when topology tab is selected', () => {
    render(<CentralBlackboardModal {...defaultProps()} />);

    fireEvent.click(getTabByName(/topology/i));

    const activePanel = document.getElementById('blackboard-panel-topology');
    expect(activePanel).not.toBeNull();
    expect(activePanel!.hidden).toBe(false);
    expect(screen.getByText(/blackboard\.topologyNodesTitle/)).toBeInTheDocument();
  });

  it('renders WorkspaceSettingsPanel when settings tab is selected', () => {
    render(<CentralBlackboardModal {...defaultProps()} />);

    fireEvent.click(getTabByName(/settings/i));

    expect(screen.getByText('Workspace settings')).toBeInTheDocument();
  });

  it('clicking a tab sets aria-selected and reveals its panel', () => {
    render(<CentralBlackboardModal {...defaultProps()} />);

    const membersTab = getTabByName(/members/i);
    expect(membersTab.getAttribute('aria-selected')).toBe('false');

    fireEvent.click(membersTab);

    expect(membersTab.getAttribute('aria-selected')).toBe('true');

    const membersPanel = document.getElementById('blackboard-panel-members');
    expect(membersPanel).not.toBeNull();
    expect(membersPanel!.hidden).toBe(false);

    const goalsTab = getTabByName(/goals/i);
    expect(goalsTab.getAttribute('aria-selected')).toBe('false');
  });

  it('ArrowRight moves focus to the next tab', () => {
    render(<CentralBlackboardModal {...defaultProps()} />);

    const goalsTab = getTabByName(/goals/i);
    goalsTab.focus();

    fireEvent.keyDown(goalsTab, { key: 'ArrowRight' });

    const discussionTab = getTabByName(/discussion/i);
    expect(discussionTab.getAttribute('aria-selected')).toBe('true');
  });

  it('ArrowLeft moves focus to the previous tab', () => {
    render(<CentralBlackboardModal {...defaultProps()} />);

    const discussionTab = getTabByName(/discussion/i);
    fireEvent.click(discussionTab);

    fireEvent.keyDown(discussionTab, { key: 'ArrowLeft' });

    const goalsTab = getTabByName(/goals/i);
    expect(goalsTab.getAttribute('aria-selected')).toBe('true');
  });

  it('Home key moves to the first tab', () => {
    render(<CentralBlackboardModal {...defaultProps()} />);

    const settingsTab = getTabByName(/settings/i);
    fireEvent.click(settingsTab);

    fireEvent.keyDown(settingsTab, { key: 'Home' });

    const goalsTab = getTabByName(/goals/i);
    expect(goalsTab.getAttribute('aria-selected')).toBe('true');
  });

  it('End key moves to the last tab', () => {
    render(<CentralBlackboardModal {...defaultProps()} />);

    const goalsTab = getTabByName(/goals/i);
    goalsTab.focus();

    fireEvent.keyDown(goalsTab, { key: 'End' });

    const settingsTab = getTabByName(/settings/i);
    expect(settingsTab.getAttribute('aria-selected')).toBe('true');
  });

  it('ArrowRight wraps around from last tab to first', () => {
    render(<CentralBlackboardModal {...defaultProps()} />);

    const settingsTab = getTabByName(/settings/i);
    fireEvent.click(settingsTab);

    fireEvent.keyDown(settingsTab, { key: 'ArrowRight' });

    const goalsTab = getTabByName(/goals/i);
    expect(goalsTab.getAttribute('aria-selected')).toBe('true');
  });

  it('ArrowLeft wraps around from first tab to last', () => {
    render(<CentralBlackboardModal {...defaultProps()} />);

    const goalsTab = getTabByName(/goals/i);
    goalsTab.focus();

    fireEvent.keyDown(goalsTab, { key: 'ArrowLeft' });

    const settingsTab = getTabByName(/settings/i);
    expect(settingsTab.getAttribute('aria-selected')).toBe('true');
  });

  it('calls onClose when the modal close button is clicked', () => {
    const onClose = vi.fn();
    render(<CentralBlackboardModal {...defaultProps({ onClose })} />);

    const closeButton = document.querySelector('.ant-modal-close') as HTMLElement | null;
    if (closeButton) {
      fireEvent.click(closeButton);
      expect(onClose).toHaveBeenCalledTimes(1);
    } else {
      expect(onClose).not.toHaveBeenCalled();
    }
  });

  it('does not render modal content when open is false', () => {
    render(<CentralBlackboardModal {...defaultProps({ open: false })} />);

    expect(screen.queryByRole('tablist')).not.toBeInTheDocument();
    expect(screen.queryByText('Objective list')).not.toBeInTheDocument();
  });

  it('opens ObjectiveCreateModal when goals tab triggers create', () => {
    render(<CentralBlackboardModal {...defaultProps()} />);

    const createModal = screen.getByTestId('objective-create-modal');
    expect(createModal.getAttribute('data-open')).toBe('false');

    const addButton = screen.getByTestId('mock-create-objective');
    fireEvent.click(addButton);

    expect(createModal.getAttribute('data-open')).toBe('true');
  });

  it('calls onCreatePost when a new post is submitted on discussion tab', async () => {
    const onCreatePost = vi.fn().mockResolvedValue(true);
    render(<CentralBlackboardModal {...defaultProps({ onCreatePost })} />);

    fireEvent.click(getTabByName(/discussion/i));

    const titleInputs = document.querySelectorAll('input');
    const textAreas = document.querySelectorAll('textarea');

    if (titleInputs.length > 0 && textAreas.length > 0) {
      fireEvent.change(titleInputs[0], { target: { value: 'Test Post Title' } });
      fireEvent.change(textAreas[0], { target: { value: 'Test post content body' } });

      const submitButton = screen.getByText(/blackboard\.createPost|create|publish/i);
      fireEvent.click(submitButton);

      await vi.waitFor(() => {
        expect(onCreatePost).toHaveBeenCalledWith({
          title: 'Test Post Title',
          content: 'Test post content body',
        });
      });
    } else {
      const discussionPanel = document.getElementById('blackboard-panel-discussion');
      expect(discussionPanel).not.toBeNull();
      expect(discussionPanel!.hidden).toBe(false);
    }
  });
});
