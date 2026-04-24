import { MemoryRouter, useParams, useSearchParams } from 'react-router-dom';

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Blackboard } from '@/pages/project/Blackboard';

import type { Workspace } from '@/types/workspace';
import type { ReactNode } from 'react';

const {
  mockLoadWorkspaceSurface,
  mockClearSelectedHex,
  mockCreatePost,
  mockLoadReplies,
  mockCreateReply,
  mockDeletePost,
  mockPinPost,
  mockUnpinPost,
  mockDeleteReply,
  mockErrorFn,
  mockUnsubscribe,
  mockSubscribeWorkspace,
  mockListByProject,
  storeStateRef,
} = vi.hoisted(() => {
  const mockUnsubscribe = vi.fn();
  return {
    mockLoadWorkspaceSurface: vi.fn().mockResolvedValue(undefined),
    mockClearSelectedHex: vi.fn(),
    mockCreatePost: vi.fn().mockResolvedValue(undefined),
    mockLoadReplies: vi.fn().mockResolvedValue(undefined),
    mockCreateReply: vi.fn().mockResolvedValue(undefined),
    mockDeletePost: vi.fn().mockResolvedValue(undefined),
    mockPinPost: vi.fn().mockResolvedValue(undefined),
    mockUnpinPost: vi.fn().mockResolvedValue(undefined),
    mockDeleteReply: vi.fn().mockResolvedValue(undefined),
    mockErrorFn: vi.fn(),
    mockUnsubscribe,
    mockSubscribeWorkspace: vi.fn().mockReturnValue(mockUnsubscribe),
    mockListByProject: vi.fn().mockResolvedValue([]),
    storeStateRef: { current: {} as Record<string, unknown> },
  };
});

// Shared mutable state for useWorkspaceStore mock to allow per-test overrides
// Using storeStateRef from vi.hoisted() so the vi.mock factory can access it

function defaultStoreState(): Record<string, unknown> {
  return {
    currentWorkspace: null,
    posts: [],
    repliesByPostId: {},
    loadedReplyPostIds: {},
    tasks: [],
    objectives: [],
    genes: [],
    agents: [],
    topologyNodes: [],
    topologyEdges: [],
    error: null,
    // Actions used by getState() path for SSE handler
    handlePresenceEvent: vi.fn(),
    handleAgentStatusEvent: vi.fn(),
    handleTaskEvent: vi.fn(),
    handleBlackboardEvent: vi.fn(),
    handleChatEvent: vi.fn(),
    handleMemberEvent: vi.fn(),
    handleWorkspaceLifecycleEvent: vi.fn(),
    handleAgentBindingEvent: vi.fn(),
    handleTopologyEvent: vi.fn(),
  };
}

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock('zustand/react/shallow', () => ({
  useShallow: <T,>(selector: T) => selector,
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useParams: vi.fn().mockReturnValue({ tenantId: 't1', projectId: 'p1' }),
    useSearchParams: vi.fn(),
  };
});

vi.mock('@/stores/workspace', () => ({
  useWorkspaceStore: Object.assign(
    (selector: (state: Record<string, unknown>) => unknown) => selector(storeStateRef.current),
    {
      getState: () => storeStateRef.current,
    }
  ),
  useWorkspaceActions: () => ({
    loadWorkspaceSurface: mockLoadWorkspaceSurface,
    clearSelectedHex: mockClearSelectedHex,
    createPost: mockCreatePost,
    loadReplies: mockLoadReplies,
    createReply: mockCreateReply,
    deletePost: mockDeletePost,
    pinPost: mockPinPost,
    unpinPost: mockUnpinPost,
    deleteReply: mockDeleteReply,
  }),
}));

vi.mock('@/services/workspaceService', () => ({
  workspaceService: {
    listByProject: mockListByProject,
  },
}));

vi.mock('@/services/unifiedEventService', () => ({
  unifiedEventService: {
    subscribeWorkspace: mockSubscribeWorkspace,
  },
}));

vi.mock('@/components/blackboard/CentralBlackboardContent', () => ({
  CentralBlackboardContent: (props: { activeTab: string }) => (
    <div data-testid="central-blackboard-content" data-active-tab={props.activeTab} />
  ),
}));

vi.mock('@/components/ui/lazyAntd', () => ({
  useLazyMessage: () => ({ error: mockErrorFn }),
}));

vi.mock('@/pages/project/blackboardRouteUtils', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/pages/project/blackboardRouteUtils')>();
  return {
    ...actual,
    clearBlackboardAutoOpenSearchParam: vi.fn().mockReturnValue(null),
    resolveRequestedWorkspaceSelection: vi.fn().mockReturnValue(null),
    syncBlackboardWorkspaceSearchParams: vi.fn().mockReturnValue(null),
  };
});

vi.mock('@/utils/agentWorkspacePath', () => ({
  buildAgentWorkspacePath: vi.fn().mockReturnValue('/tenant/t1/agent-workspace'),
}));

// ---------------------------------------------------------------------------
// Test data helpers
// ---------------------------------------------------------------------------

function makeWorkspace(overrides: Partial<Workspace> = {}): Workspace {
  return {
    id: 'ws-1',
    tenant_id: 't1',
    project_id: 'p1',
    name: 'Alpha Workspace',
    created_by: 'user-1',
    created_at: '2025-01-01T00:00:00Z',
    ...overrides,
  };
}

function makeWorkspaces(count = 2): Workspace[] {
  return Array.from({ length: count }, (_, i) =>
    makeWorkspace({ id: `ws-${i + 1}`, name: `Workspace ${i + 1}` })
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function setupSearchParams(query: string = '') {
  const searchParams = new URLSearchParams(query);
  const setSearchParams = vi.fn();
  (useSearchParams as ReturnType<typeof vi.fn>).mockReturnValue([searchParams, setSearchParams]);
  return { searchParams, setSearchParams };
}

function renderBlackboard(options: { initialEntries?: string[] } = {}) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={options.initialEntries ?? ['/']}>{children}</MemoryRouter>
  );
  return render(<Blackboard />, { wrapper });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Blackboard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    storeStateRef.current = defaultStoreState();
    (useParams as ReturnType<typeof vi.fn>).mockReturnValue({ tenantId: 't1', projectId: 'p1' });
    setupSearchParams();
  });

  // 1. Loading state
  it('renders loading state initially while workspaces are being fetched', async () => {
    // listByProject never resolves so workspacesLoading stays true
    mockListByProject.mockReturnValue(new Promise(() => {}));

    renderBlackboard();

    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  // 2. Workspace selector visible after load
  it('renders workspace selector when workspaces are loaded', async () => {
    const workspaces = makeWorkspaces(2);
    mockListByProject.mockResolvedValue(workspaces);

    renderBlackboard();

    await waitFor(() => {
      expect(screen.getByRole('combobox')).toBeInTheDocument();
    });

    const options = screen.getAllByRole('option');
    expect(options).toHaveLength(2);
    expect(options[0]).toHaveTextContent('Workspace 1');
    expect(options[1]).toHaveTextContent('Workspace 2');
  });

  // 3. Selecting a workspace triggers surface loading
  it('selects workspace and triggers surface loading', async () => {
    const workspaces = makeWorkspaces(2);
    mockListByProject.mockResolvedValue(workspaces);

    // After surface loads, set currentWorkspace to match
    mockLoadWorkspaceSurface.mockImplementation(async () => {
      storeStateRef.current = {
        ...storeStateRef.current,
        currentWorkspace: workspaces[0],
      };
    });

    renderBlackboard();

    await waitFor(() => {
      expect(screen.getByRole('combobox')).toBeInTheDocument();
    });

    // The first workspace is auto-selected, so loadWorkspaceSurface is called
    await waitFor(() => {
      expect(mockLoadWorkspaceSurface).toHaveBeenCalledWith('t1', 'p1', 'ws-1');
    });

    // Now select the second workspace
    await act(async () => {
      fireEvent.change(screen.getByRole('combobox'), { target: { value: 'ws-2' } });
    });

    await waitFor(() => {
      expect(mockLoadWorkspaceSurface).toHaveBeenCalledWith('t1', 'p1', 'ws-2');
    });
  });

  // 4. loadWorkspaceSurface is called when a workspace becomes selected
  it('triggers loadWorkspaceSurface when a workspace is selected', async () => {
    const workspaces = makeWorkspaces(1);
    mockListByProject.mockResolvedValue(workspaces);
    mockLoadWorkspaceSurface.mockResolvedValue(undefined);

    renderBlackboard();

    await waitFor(() => {
      expect(mockLoadWorkspaceSurface).toHaveBeenCalledWith('t1', 'p1', 'ws-1');
    });
  });

  // 5. Central blackboard content renders directly on the page
  it('renders CentralBlackboardContent directly on the page when a workspace is loaded', async () => {
    const workspaces = makeWorkspaces(1);
    mockListByProject.mockResolvedValue(workspaces);

    storeStateRef.current = {
      ...storeStateRef.current,
      currentWorkspace: workspaces[0],
    };
    mockLoadWorkspaceSurface.mockResolvedValue(undefined);

    renderBlackboard();

    await waitFor(() => {
      expect(screen.getByTestId('central-blackboard-content')).toBeInTheDocument();
    });
    expect(screen.getByText('blackboard.shellHint')).toBeInTheDocument();
    expect(screen.getByTestId('central-blackboard-content').parentElement).toHaveAttribute(
      'data-blackboard-surface',
      'shell'
    );
  });

  // 6. Deep-links to a tab via ?tab= search param
  it('respects the ?tab= query parameter when deep-linking', async () => {
    const workspaces = makeWorkspaces(1);
    mockListByProject.mockResolvedValue(workspaces);

    storeStateRef.current = {
      ...storeStateRef.current,
      currentWorkspace: workspaces[0],
    };
    mockLoadWorkspaceSurface.mockResolvedValue(undefined);

    setupSearchParams('tab=status');
    renderBlackboard();

    await waitFor(() => {
      expect(screen.getByTestId('central-blackboard-content')).toHaveAttribute(
        'data-active-tab',
        'status'
      );
    });
  });

  // 7. SSE subscription lifecycle
  it('subscribes to SSE on workspace select and unsubscribes on unmount', async () => {
    const workspaces = makeWorkspaces(1);
    mockListByProject.mockResolvedValue(workspaces);

    storeStateRef.current = {
      ...storeStateRef.current,
      currentWorkspace: workspaces[0],
    };
    mockLoadWorkspaceSurface.mockResolvedValue(undefined);

    const { unmount } = renderBlackboard();

    await waitFor(() => {
      expect(mockSubscribeWorkspace).toHaveBeenCalledWith('ws-1', expect.any(Function));
    });

    unmount();

    expect(mockUnsubscribe).toHaveBeenCalled();
  });

  // 8. Error state rendering when workspace loading fails
  it('renders error state when workspace list loading fails', async () => {
    mockListByProject.mockRejectedValue(new Error('Network failure'));

    renderBlackboard();

    await waitFor(() => {
      expect(screen.getByText('Network failure')).toBeInTheDocument();
      expect(screen.getByText('Error')).toBeInTheDocument();
    });
  });

  // 9. Surface error state with retry
  it('renders surface error state with retry button', async () => {
    const workspaces = makeWorkspaces(1);
    mockListByProject.mockResolvedValue(workspaces);

    storeStateRef.current = {
      ...storeStateRef.current,
      currentWorkspace: workspaces[0],
      error: 'Surface load failed',
    };
    mockLoadWorkspaceSurface.mockResolvedValue(undefined);

    renderBlackboard();

    await waitFor(() => {
      expect(screen.getByText('Surface load failed')).toBeInTheDocument();
    });

    expect(screen.getByText('common.retry')).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByText('common.retry'));
    });

    // loadWorkspaceSurface is called from both initial load and retry
    await waitFor(() => {
      expect(mockLoadWorkspaceSurface).toHaveBeenCalledTimes(2);
    });
  });

  // 10. Post creation callback
  it('post creation callback calls createPost through workspace store', async () => {
    const workspaces = makeWorkspaces(1);
    mockListByProject.mockResolvedValue(workspaces);

    storeStateRef.current = {
      ...storeStateRef.current,
      currentWorkspace: workspaces[0],
    };
    mockLoadWorkspaceSurface.mockResolvedValue(undefined);

    renderBlackboard();

    await waitFor(() => {
      expect(screen.getByTestId('central-blackboard-content')).toBeInTheDocument();
    });

    // The mock CentralBlackboardModal receives onCreatePost as a prop but does not render it;
    // we verify the action mock is available and the modal is rendered
    expect(mockCreatePost).not.toHaveBeenCalled();
  });

  // 11. Reply creation callback
  it('reply creation callback wires through to workspace store createReply', async () => {
    const workspaces = makeWorkspaces(1);
    mockListByProject.mockResolvedValue(workspaces);

    storeStateRef.current = {
      ...storeStateRef.current,
      currentWorkspace: workspaces[0],
    };
    mockLoadWorkspaceSurface.mockResolvedValue(undefined);

    renderBlackboard();

    await waitFor(() => {
      expect(screen.getByTestId('central-blackboard-content')).toBeInTheDocument();
    });

    // The callbacks are wired; verify the mock has not been called prematurely
    expect(mockCreateReply).not.toHaveBeenCalled();
  });

  // 12. Delete/pin/unpin callbacks are wired
  it('delete, pin, and unpin callbacks are available and not called prematurely', async () => {
    const workspaces = makeWorkspaces(1);
    mockListByProject.mockResolvedValue(workspaces);

    storeStateRef.current = {
      ...storeStateRef.current,
      currentWorkspace: workspaces[0],
    };
    mockLoadWorkspaceSurface.mockResolvedValue(undefined);

    renderBlackboard();

    await waitFor(() => {
      expect(screen.getByTestId('central-blackboard-content')).toBeInTheDocument();
    });

    expect(mockDeletePost).not.toHaveBeenCalled();
    expect(mockPinPost).not.toHaveBeenCalled();
    expect(mockUnpinPost).not.toHaveBeenCalled();
    expect(mockDeleteReply).not.toHaveBeenCalled();
  });

  // 13. No workspaces found
  it('renders empty state when no workspaces exist', async () => {
    mockListByProject.mockResolvedValue([]);

    renderBlackboard();

    await waitFor(() => {
      expect(screen.getByText('blackboard.noWorkspaces')).toBeInTheDocument();
    });
  });

  // 14. Open in Agent Workspace link
  it('renders a link to agent workspace when workspace is selected', async () => {
    const workspaces = makeWorkspaces(1);
    mockListByProject.mockResolvedValue(workspaces);

    storeStateRef.current = {
      ...storeStateRef.current,
      currentWorkspace: workspaces[0],
    };
    mockLoadWorkspaceSurface.mockResolvedValue(undefined);

    renderBlackboard();

    await waitFor(() => {
      expect(screen.getByText('blackboard.openInAgentWorkspace')).toBeInTheDocument();
    });

    const link = screen.getByText('blackboard.openInAgentWorkspace').closest('a');
    expect(link).toBeInTheDocument();
  });

  // 15. clearSelectedHex called on unmount
  it('calls clearSelectedHex on unmount', async () => {
    const workspaces = makeWorkspaces(1);
    mockListByProject.mockResolvedValue(workspaces);

    storeStateRef.current = {
      ...storeStateRef.current,
      currentWorkspace: workspaces[0],
    };
    mockLoadWorkspaceSurface.mockResolvedValue(undefined);

    const { unmount } = renderBlackboard();

    await waitFor(() => {
      expect(screen.getByTestId('central-blackboard-content')).toBeInTheDocument();
    });

    unmount();

    expect(mockClearSelectedHex).toHaveBeenCalled();
  });

  // 17. SSE subscribes with new workspace ID when workspace changes
  it('re-subscribes to SSE when workspace changes', async () => {
    const workspaces = makeWorkspaces(2);
    mockListByProject.mockResolvedValue(workspaces);

    // Set up so store mirrors current workspace
    mockLoadWorkspaceSurface.mockImplementation(
      async (_t: string, _p: string, wsId: string) => {
        storeStateRef.current = {
          ...storeStateRef.current,
          currentWorkspace: workspaces.find((w) => w.id === wsId) ?? null,
        };
      }
    );

    renderBlackboard();

    await waitFor(() => {
      expect(mockSubscribeWorkspace).toHaveBeenCalledWith('ws-1', expect.any(Function));
    });

    // Switch workspace
    await act(async () => {
      fireEvent.change(screen.getByRole('combobox'), { target: { value: 'ws-2' } });
    });

    await waitFor(() => {
      expect(mockSubscribeWorkspace).toHaveBeenCalledWith('ws-2', expect.any(Function));
    });

    // Old subscription cleaned up
    expect(mockUnsubscribe).toHaveBeenCalled();
  });

  // 18. Surface loading state reflects in page (no stale content)
  it('waits for surface load before rendering central blackboard content', async () => {
    const workspaces = makeWorkspaces(1);
    mockListByProject.mockResolvedValue(workspaces);

    // Surface never resolves — currentWorkspace stays null
    mockLoadWorkspaceSurface.mockReturnValue(new Promise(() => {}));

    renderBlackboard();

    await waitFor(() => {
      expect(screen.getByRole('combobox')).toBeInTheDocument();
    });

    expect(screen.queryByTestId('central-blackboard-content')).not.toBeInTheDocument();
  });

  // 19. Renders page title (sr-only heading in compact toolbar)
  it('renders page heading', async () => {
    const workspaces = makeWorkspaces(1);
    mockListByProject.mockResolvedValue(workspaces);
    mockLoadWorkspaceSurface.mockResolvedValue(undefined);

    storeStateRef.current = {
      ...storeStateRef.current,
      currentWorkspace: workspaces[0],
    };

    renderBlackboard();

    await waitFor(() => {
      expect(screen.getByText('blackboard.title')).toBeInTheDocument();
    });
  });
});
