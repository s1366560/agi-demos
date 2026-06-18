import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';

import {
  workspaceBlackboardService,
  workspaceChatService,
  workspaceGeneService,
  workspaceObjectiveService,
  workspaceService,
  workspaceTaskService,
  workspaceTopologyService,
} from '@/services/workspaceService';
import {
  AUTHORITATIVE,
  HOSTED,
  NON_AUTHORITATIVE,
  OWNED,
  SENSING_CAPABLE,
} from '@/components/blackboard/blackboardSurfaceContract';
import { useWorkspaceReplies, useWorkspaceStore } from '@/stores/workspace';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

vi.mock('@/services/workspaceService', () => ({
  workspaceService: {
    listByProject: vi.fn(),
    getById: vi.fn(),
    listMembers: vi.fn(),
    listAgents: vi.fn(),
    bindAgent: vi.fn(),
    updateAgentBinding: vi.fn(),
    unbindAgent: vi.fn(),
  },
  workspaceBlackboardService: {
    listPosts: vi.fn(),
    listReplies: vi.fn(),
  },
  workspaceTaskService: {
    list: vi.fn(),
  },
  workspaceTopologyService: {
    listNodes: vi.fn(),
    listEdges: vi.fn(),
    createNode: vi.fn(),
    updateNode: vi.fn(),
    deleteNode: vi.fn(),
    createEdge: vi.fn(),
    updateEdge: vi.fn(),
    deleteEdge: vi.fn(),
  },
  workspaceObjectiveService: {
    list: vi.fn(),
    projectToTask: vi.fn(),
  },
  workspaceGeneService: {
    list: vi.fn(),
  },
  workspaceChatService: {
    listMessages: vi.fn(),
  },
}));

describe('workspace store', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useWorkspaceStore.setState({
      workspaces: [],
      currentWorkspace: null,
      members: [],
      agents: [],
      posts: [],
      repliesByPostId: {},
      loadedReplyPostIds: {},
      replyLoadingPostIds: {},
      tasks: [],
      topologyNodes: [],
      topologyEdges: [],
      objectives: [],
      genes: [],
      chatMessages: [],
      planRefreshCounters: {},
      fileRefreshCounters: {},
      isLoading: false,
      activeSurfaceRequestId: 0,
      error: null,
    });
  });

  it('loadWorkspaces updates workspace collection and picks current workspace', async () => {
    vi.mocked(workspaceService.listByProject).mockResolvedValueOnce([
      {
        id: 'ws-1',
        tenant_id: 't-1',
        project_id: 'p-1',
        name: 'Alpha',
        created_by: 'u-1',
        created_at: '',
      },
      {
        id: 'ws-2',
        tenant_id: 't-1',
        project_id: 'p-1',
        name: 'Beta',
        created_by: 'u-1',
        created_at: '',
      },
    ] as any);

    await useWorkspaceStore.getState().loadWorkspaces('t-1', 'p-1');

    const state = useWorkspaceStore.getState();
    expect(state.workspaces).toHaveLength(2);
    expect(state.currentWorkspace?.id).toBe('ws-1');
  });

  it('loadWorkspaces drops stale current workspace from a different project', async () => {
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: 'old-ws',
        tenant_id: 't-1',
        project_id: 'old-project',
        name: 'Old Project Workspace',
        created_by: 'u-1',
        created_at: '',
      } as any,
      members: [{ id: 'old-member' }] as any,
      posts: [{ id: 'old-post' }] as any,
      tasks: [{ id: 'old-task' }] as any,
      chatMessages: [{ id: 'old-message' }] as any,
    });
    vi.mocked(workspaceService.listByProject).mockResolvedValueOnce([
      {
        id: 'new-ws',
        tenant_id: 't-1',
        project_id: 'new-project',
        name: 'New Project Workspace',
        created_by: 'u-1',
        created_at: '',
      },
    ] as any);

    await useWorkspaceStore.getState().loadWorkspaces('t-1', 'new-project');

    const state = useWorkspaceStore.getState();
    expect(state.currentWorkspace?.id).toBe('new-ws');
    expect(state.members).toEqual([]);
    expect(state.posts).toEqual([]);
    expect(state.tasks).toEqual([]);
    expect(state.chatMessages).toEqual([]);
  });

  it('loadWorkspaces keeps a same-scope current workspace that is outside the loaded page', async () => {
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: 'ws-99',
        tenant_id: 't-1',
        project_id: 'p-1',
        name: 'Selected Workspace',
        created_by: 'u-1',
        created_at: '',
      } as any,
      members: [{ id: 'member-1' }] as any,
    });
    vi.mocked(workspaceService.listByProject).mockResolvedValueOnce([
      {
        id: 'ws-1',
        tenant_id: 't-1',
        project_id: 'p-1',
        name: 'First Page Workspace',
        created_by: 'u-1',
        created_at: '',
      },
    ] as any);

    await useWorkspaceStore.getState().loadWorkspaces('t-1', 'p-1');

    const state = useWorkspaceStore.getState();
    expect(state.currentWorkspace?.id).toBe('ws-99');
    expect(state.members).toEqual([{ id: 'member-1' }]);
  });

  it('loadWorkspaces ignores stale responses from older project requests', async () => {
    let resolveFirstList: ((value: any) => void) | null = null;
    const firstListPromise = new Promise((resolve) => {
      resolveFirstList = resolve;
    });

    vi.mocked(workspaceService.listByProject)
      .mockReturnValueOnce(firstListPromise as Promise<any>)
      .mockResolvedValueOnce([
        {
          id: 'ws-new',
          tenant_id: 't-1',
          project_id: 'new-project',
          name: 'New Project Workspace',
          created_by: 'u-1',
          created_at: '',
        },
      ] as any);

    const firstLoad = useWorkspaceStore.getState().loadWorkspaces('t-1', 'old-project');
    const secondLoad = useWorkspaceStore.getState().loadWorkspaces('t-1', 'new-project');

    await secondLoad;
    resolveFirstList?.([
      {
        id: 'ws-old',
        tenant_id: 't-1',
        project_id: 'old-project',
        name: 'Old Project Workspace',
        created_by: 'u-1',
        created_at: '',
      },
    ]);
    await firstLoad;

    const state = useWorkspaceStore.getState();
    expect(state.workspaces).toEqual([expect.objectContaining({ id: 'ws-new' })]);
    expect(state.currentWorkspace?.id).toBe('ws-new');
    expect(state.isLoading).toBe(false);
  });

  it('loadWorkspaces invalidates a stale surface load when selected workspace changes', async () => {
    const staleWorkspaceRequest = deferred<any>();
    vi.mocked(workspaceService.getById).mockReturnValueOnce(staleWorkspaceRequest.promise);
    vi.mocked(workspaceService.listMembers).mockResolvedValueOnce([{ id: 'old-member' }] as any);
    vi.mocked(workspaceService.listAgents).mockResolvedValueOnce([]);
    vi.mocked(workspaceBlackboardService.listPosts).mockResolvedValueOnce([
      { id: 'old-post', title: 'Old post' },
    ] as any);
    vi.mocked(workspaceTaskService.list).mockResolvedValueOnce([{ id: 'old-task' }] as any);
    vi.mocked(workspaceTopologyService.listNodes).mockResolvedValueOnce([]);
    vi.mocked(workspaceTopologyService.listEdges).mockResolvedValueOnce([]);
    vi.mocked(workspaceObjectiveService.list).mockResolvedValueOnce([]);
    vi.mocked(workspaceGeneService.list).mockResolvedValueOnce([]);
    vi.mocked(workspaceChatService.listMessages).mockResolvedValueOnce([]);

    const surfaceLoad = useWorkspaceStore
      .getState()
      .loadWorkspaceSurface('t-1', 'old-project', 'old-ws');

    vi.mocked(workspaceService.listByProject).mockResolvedValueOnce([
      {
        id: 'new-ws',
        tenant_id: 't-1',
        project_id: 'new-project',
        name: 'New Workspace',
        created_by: 'u-1',
        created_at: '',
      },
    ] as any);

    await useWorkspaceStore.getState().loadWorkspaces('t-1', 'new-project');

    staleWorkspaceRequest.resolve({
      id: 'old-ws',
      tenant_id: 't-1',
      project_id: 'old-project',
      name: 'Old Workspace',
      created_by: 'u-1',
      created_at: '',
    });
    await surfaceLoad;

    const state = useWorkspaceStore.getState();
    expect(state.currentWorkspace?.id).toBe('new-ws');
    expect(state.members).toEqual([]);
    expect(state.posts).toEqual([]);
    expect(state.tasks).toEqual([]);
    expect(state.isLoading).toBe(false);
  });

  it('loadWorkspaceSurface hydrates posts/tasks/topology for selected workspace', async () => {
    vi.mocked(workspaceService.getById).mockResolvedValueOnce({
      id: 'ws-1',
      tenant_id: 't-1',
      project_id: 'p-1',
      name: 'Alpha',
      created_by: 'u-1',
      created_at: '',
    } as any);
    vi.mocked(workspaceService.listMembers).mockResolvedValueOnce([]);
    vi.mocked(workspaceService.listAgents).mockResolvedValueOnce([]);
    vi.mocked(workspaceBlackboardService.listPosts).mockResolvedValueOnce([
      { id: 'post-1', title: 'Question', content: 'How to ship?', status: 'open' },
    ] as any);
    vi.mocked(workspaceTaskService.list).mockResolvedValueOnce([
      { id: 'task-1', title: 'Ship v1', status: 'todo' },
    ] as any);
    vi.mocked(workspaceTopologyService.listNodes).mockResolvedValueOnce([
      { id: 'node-1', node_type: 'task', title: 'Ship v1', position_x: 0, position_y: 0 },
    ] as any);
    vi.mocked(workspaceTopologyService.listEdges).mockResolvedValueOnce([
      { id: 'edge-1', source_node_id: 'node-1', target_node_id: 'node-1' },
    ] as any);
    vi.mocked(workspaceObjectiveService.list).mockResolvedValueOnce([]);
    vi.mocked(workspaceGeneService.list).mockResolvedValueOnce([]);
    vi.mocked(workspaceChatService.listMessages).mockResolvedValueOnce([]);

    await useWorkspaceStore.getState().loadWorkspaceSurface('t-1', 'p-1', 'ws-1');

    const state = useWorkspaceStore.getState();
    expect(state.currentWorkspace?.id).toBe('ws-1');
    expect(state.posts[0].id).toBe('post-1');
    expect(state.tasks[0].id).toBe('task-1');
    expect(state.topologyNodes[0].id).toBe('node-1');
    expect(state.topologyEdges[0].id).toBe('edge-1');
    expect(state.repliesByPostId).toEqual({});
    expect(state.loadedReplyPostIds).toEqual({});
    expect(workspaceBlackboardService.listReplies).not.toHaveBeenCalled();
  });

  it('loadReplies fetches replies on demand for the active workspace', async () => {
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: 'ws-1',
        tenant_id: 't-1',
        project_id: 'p-1',
        name: 'Alpha',
        created_by: 'u-1',
        created_at: '',
      } as any,
      repliesByPostId: {},
      loadedReplyPostIds: {},
      replyLoadingPostIds: {},
    });
    vi.mocked(workspaceBlackboardService.listReplies).mockResolvedValueOnce([
      {
        id: 'reply-1',
        post_id: 'post-1',
        workspace_id: 'ws-1',
        content: 'Ship it',
        author_id: 'u-2',
        metadata: {},
        created_at: '2026-03-30T10:00:00Z',
      },
    ] as any);

    await useWorkspaceStore.getState().loadReplies('t-1', 'p-1', 'ws-1', 'post-1');

    expect(useWorkspaceStore.getState().repliesByPostId['post-1']).toEqual([
      expect.objectContaining({ id: 'reply-1' }),
    ]);
    expect(useWorkspaceStore.getState().loadedReplyPostIds['post-1']).toBe(true);
  });

  it('loadReplies still fetches full history when live replies exist before the thread is loaded', async () => {
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: 'ws-1',
        tenant_id: 't-1',
        project_id: 'p-1',
        name: 'Alpha',
        created_by: 'u-1',
        created_at: '',
      } as any,
      repliesByPostId: {
        'post-1': [
          {
            id: 'reply-live',
            post_id: 'post-1',
            workspace_id: 'ws-1',
            content: 'Newest',
            author_id: 'u-2',
            metadata: {},
            created_at: '2026-03-30T10:00:01Z',
          },
        ] as any,
      },
      loadedReplyPostIds: {},
      replyLoadingPostIds: {},
    });
    vi.mocked(workspaceBlackboardService.listReplies).mockResolvedValueOnce([
      {
        id: 'reply-old',
        post_id: 'post-1',
        workspace_id: 'ws-1',
        content: 'Older',
        author_id: 'u-1',
        metadata: {},
        created_at: '2026-03-30T10:00:00Z',
      },
      {
        id: 'reply-live',
        post_id: 'post-1',
        workspace_id: 'ws-1',
        content: 'Newest',
        author_id: 'u-2',
        metadata: {},
        created_at: '2026-03-30T10:00:01Z',
      },
    ] as any);

    await useWorkspaceStore.getState().loadReplies('t-1', 'p-1', 'ws-1', 'post-1');

    expect(useWorkspaceStore.getState().repliesByPostId['post-1']).toEqual([
      expect.objectContaining({ id: 'reply-old' }),
      expect.objectContaining({ id: 'reply-live' }),
    ]);
    expect(useWorkspaceStore.getState().loadedReplyPostIds['post-1']).toBe(true);
  });

  it('handleBlackboardEvent tolerates owned-surface contract fields on post payloads', () => {
    useWorkspaceStore.setState({
      posts: [],
    });

    useWorkspaceStore.getState().handleBlackboardEvent({
      type: 'blackboard_post_created',
      data: {
        post: {
          id: 'post-1',
          workspace_id: 'ws-1',
          author_id: 'u-1',
          title: 'Owned post',
          content: 'Hello',
          status: 'open',
          is_pinned: false,
          metadata: {},
          created_at: '2026-03-30T10:00:00Z',
          updated_at: '2026-03-30T10:00:00Z',
        },
        surface_boundary: OWNED,
        authority_class: AUTHORITATIVE,
      },
    });

    expect(useWorkspaceStore.getState().posts).toEqual([
      expect.objectContaining({ id: 'post-1', title: 'Owned post' }),
    ]);
  });

  it('handleBlackboardEvent ignores non-owned blackboard payloads when boundary metadata is explicit', () => {
    useWorkspaceStore.setState({
      posts: [
        {
          id: 'post-1',
          workspace_id: 'ws-1',
          author_id: 'u-1',
          title: 'Existing',
          content: 'hello',
          status: 'open',
          is_pinned: false,
          metadata: {},
          created_at: '2026-03-30T10:00:00Z',
          updated_at: '2026-03-30T10:00:00Z',
        },
      ] as any,
    });

    useWorkspaceStore.getState().handleBlackboardEvent({
      type: 'blackboard_post_updated',
      data: {
        post: {
          id: 'post-1',
          workspace_id: 'ws-1',
          author_id: 'u-1',
          title: 'Should be ignored',
          content: 'hello',
          status: 'open',
          is_pinned: false,
          metadata: {},
          created_at: '2026-03-30T10:00:00Z',
          updated_at: '2026-03-30T10:01:00Z',
        },
        surface_boundary: HOSTED,
        authority_class: NON_AUTHORITATIVE,
      },
    });

    expect(useWorkspaceStore.getState().posts).toEqual([
      expect.objectContaining({ id: 'post-1', title: 'Existing' }),
    ]);
  });

  it('handleBlackboardEvent ignores malformed post payloads without throwing', () => {
    useWorkspaceStore.setState({
      posts: [],
    });

    expect(() => {
      useWorkspaceStore.getState().handleBlackboardEvent({
        type: 'blackboard_post_created',
        data: {
          post_id: 'post-1',
          surface_boundary: OWNED,
          authority_class: AUTHORITATIVE,
        },
      });
    }).not.toThrow();

    expect(useWorkspaceStore.getState().posts).toEqual([]);
  });

  it('handleBlackboardEvent merges updated reply payloads', () => {
    useWorkspaceStore.setState({
      repliesByPostId: {
        'post-1': [
          {
            id: 'reply-1',
            post_id: 'post-1',
            workspace_id: 'ws-1',
            author_id: 'u-1',
            content: 'Original',
            metadata: {},
            created_at: '2026-03-30T10:00:00Z',
          },
        ],
      },
    });

    useWorkspaceStore.getState().handleBlackboardEvent({
      type: 'blackboard_reply_updated',
      data: {
        post_id: 'post-1',
        reply: {
          id: 'reply-1',
          post_id: 'post-1',
          workspace_id: 'ws-1',
          author_id: 'u-1',
          content: 'Updated',
          metadata: { edited: true },
          created_at: '2026-03-30T10:00:00Z',
          updated_at: '2026-03-30T10:02:00Z',
        },
        surface_boundary: OWNED,
        authority_class: AUTHORITATIVE,
      },
    });

    expect(useWorkspaceStore.getState().repliesByPostId['post-1']).toEqual([
      expect.objectContaining({
        id: 'reply-1',
        content: 'Updated',
        metadata: { edited: true },
      }),
    ]);
  });

  it('handleBlackboardEvent increments file refresh counters for file events', () => {
    useWorkspaceStore.setState({
      fileRefreshCounters: {},
    });

    useWorkspaceStore.getState().handleBlackboardEvent({
      type: 'blackboard_file_created',
      data: {
        file: {
          id: 'file-1',
          workspace_id: 'ws-1',
          parent_path: '/',
          name: 'notes.txt',
        },
        workspace_id: 'ws-1',
      },
    });

    expect(useWorkspaceStore.getState().fileRefreshCounters['ws-1']).toBe(1);
  });

  it('handleChatEvent accepts hosted sensing chat payloads', () => {
    useWorkspaceStore.setState({
      chatMessages: [],
    });

    useWorkspaceStore.getState().handleChatEvent({
      type: 'workspace_message_created',
      data: {
        message: {
          id: 'msg-1',
          workspace_id: 'ws-1',
          content: 'hello',
          created_at: '2026-03-30T10:00:00Z',
        },
        surface_boundary: HOSTED,
        signal_role: SENSING_CAPABLE,
      },
    });

    expect(useWorkspaceStore.getState().chatMessages).toEqual([
      expect.objectContaining({ id: 'msg-1', content: 'hello' }),
    ]);
  });

  it('handleChatEvent ignores non-hosted or non-sensing chat payloads when metadata is explicit', () => {
    useWorkspaceStore.setState({
      chatMessages: [
        {
          id: 'msg-1',
          workspace_id: 'ws-1',
          content: 'existing',
          created_at: '2026-03-30T10:00:00Z',
        },
      ] as any,
    });

    useWorkspaceStore.getState().handleChatEvent({
      type: 'workspace_message_created',
      data: {
        message: {
          id: 'msg-2',
          workspace_id: 'ws-1',
          content: 'should be ignored',
          created_at: '2026-03-30T10:01:00Z',
        },
        surface_boundary: OWNED,
        signal_role: AUTHORITATIVE,
      },
    });

    expect(useWorkspaceStore.getState().chatMessages).toEqual([
      expect.objectContaining({ id: 'msg-1', content: 'existing' }),
    ]);
  });

  it('handleMemberEvent applies structured joined, updated, and left payloads', () => {
    useWorkspaceStore.setState({
      members: [
        {
          id: 'wm-1',
          workspace_id: 'ws-1',
          user_id: 'user-1',
          role: 'viewer',
          created_at: '2026-03-30T10:00:00Z',
        },
      ] as any,
    });

    useWorkspaceStore.getState().handleMemberEvent({
      type: 'workspace_member_joined',
      data: {
        member: {
          id: 'wm-2',
          workspace_id: 'ws-1',
          user_id: 'user-2',
          role: 'editor',
          created_at: '2026-03-30T10:01:00Z',
        },
      },
    });
    useWorkspaceStore.getState().handleMemberEvent({
      type: 'workspace_member_updated',
      data: {
        member: {
          id: 'wm-1',
          workspace_id: 'ws-1',
          user_id: 'user-1',
          role: 'owner',
          created_at: '2026-03-30T10:00:00Z',
        },
      },
    });
    useWorkspaceStore.getState().handleMemberEvent({
      type: 'workspace_member_left',
      data: {
        member: {
          id: 'wm-2',
          workspace_id: 'ws-1',
          user_id: 'user-2',
          role: 'editor',
          created_at: '2026-03-30T10:01:00Z',
        },
        member_id: 'wm-2',
      },
    });

    expect(useWorkspaceStore.getState().members).toEqual([
      expect.objectContaining({ id: 'wm-1', role: 'owner' }),
    ]);
  });

  it('handleWorkspaceLifecycleEvent applies structured workspace payload', () => {
    useWorkspaceStore.setState({
      workspaces: [
        {
          id: 'ws-1',
          tenant_id: 't-1',
          project_id: 'p-1',
          name: 'Old',
          created_by: 'u-1',
          created_at: '2026-03-30T10:00:00Z',
        },
      ] as any,
      currentWorkspace: {
        id: 'ws-1',
        tenant_id: 't-1',
        project_id: 'p-1',
        name: 'Old',
        created_by: 'u-1',
        created_at: '2026-03-30T10:00:00Z',
      } as any,
    });

    useWorkspaceStore.getState().handleWorkspaceLifecycleEvent({
      type: 'workspace_updated',
      data: {
        workspace: {
          id: 'ws-1',
          tenant_id: 't-1',
          project_id: 'p-1',
          name: 'Renamed',
          created_by: 'u-1',
          created_at: '2026-03-30T10:00:00Z',
        },
        workspace_id: 'ws-1',
      },
    });

    expect(useWorkspaceStore.getState().workspaces[0]?.name).toBe('Renamed');
    expect(useWorkspaceStore.getState().currentWorkspace?.name).toBe('Renamed');
  });

  it('handleWorkspaceLifecycleEvent selects another workspace when the current one is deleted', () => {
    useWorkspaceStore.setState({
      workspaces: [
        {
          id: 'ws-1',
          tenant_id: 't-1',
          project_id: 'p-1',
          name: 'Deleted',
          created_by: 'u-1',
          created_at: '2026-03-30T10:00:00Z',
        },
        {
          id: 'ws-2',
          tenant_id: 't-1',
          project_id: 'p-1',
          name: 'Remaining',
          created_by: 'u-1',
          created_at: '2026-03-30T10:00:00Z',
        },
      ] as any,
      currentWorkspace: {
        id: 'ws-1',
        tenant_id: 't-1',
        project_id: 'p-1',
        name: 'Deleted',
        created_by: 'u-1',
        created_at: '2026-03-30T10:00:00Z',
      } as any,
      posts: [{ id: 'old-post' }] as any,
      tasks: [{ id: 'old-task' }] as any,
    });

    useWorkspaceStore.getState().handleWorkspaceLifecycleEvent({
      type: 'workspace_deleted',
      data: {
        workspace_id: 'ws-1',
      },
    });

    const state = useWorkspaceStore.getState();
    expect(state.workspaces.map((workspace) => workspace.id)).toEqual(['ws-2']);
    expect(state.currentWorkspace?.id).toBe('ws-2');
    expect(state.posts).toEqual([]);
    expect(state.tasks).toEqual([]);
  });

  it('loadReplies lets canonical API reply data win over earlier live payloads', async () => {
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: 'ws-1',
        tenant_id: 't-1',
        project_id: 'p-1',
        name: 'Alpha',
        created_by: 'u-1',
        created_at: '',
      } as any,
      repliesByPostId: {
        'post-1': [
          {
            id: 'reply-1',
            post_id: 'post-1',
            workspace_id: 'ws-1',
            content: 'Live payload',
            author_id: 'u-2',
            metadata: {},
            created_at: '2026-03-30T10:00:00Z',
          },
        ] as any,
      },
      loadedReplyPostIds: {},
      replyLoadingPostIds: {},
    });
    vi.mocked(workspaceBlackboardService.listReplies).mockResolvedValueOnce([
      {
        id: 'reply-1',
        post_id: 'post-1',
        workspace_id: 'ws-1',
        content: 'Canonical payload',
        author_id: 'u-2',
        metadata: { source: 'api' },
        created_at: '2026-03-30T10:00:00Z',
      },
    ] as any);

    await useWorkspaceStore.getState().loadReplies('t-1', 'p-1', 'ws-1', 'post-1');

    expect(useWorkspaceStore.getState().repliesByPostId['post-1']).toEqual([
      expect.objectContaining({
        id: 'reply-1',
        content: 'Canonical payload',
        metadata: { source: 'api' },
      }),
    ]);
  });

  it('loadReplies keeps newer live replies that arrive while the fetch is in flight', async () => {
    let resolveReplies: ((value: any) => void) | null = null;
    const repliesPromise = new Promise((resolve) => {
      resolveReplies = resolve;
    });

    useWorkspaceStore.setState({
      currentWorkspace: {
        id: 'ws-1',
        tenant_id: 't-1',
        project_id: 'p-1',
        name: 'Alpha',
        created_by: 'u-1',
        created_at: '',
      } as any,
      repliesByPostId: {},
      loadedReplyPostIds: {},
      replyLoadingPostIds: {},
    });
    vi.mocked(workspaceBlackboardService.listReplies).mockReturnValueOnce(
      repliesPromise as Promise<any>
    );

    const loadPromise = useWorkspaceStore.getState().loadReplies('t-1', 'p-1', 'ws-1', 'post-1');

    useWorkspaceStore.getState().handleBlackboardEvent({
      type: 'blackboard_reply_created',
      data: {
        post_id: 'post-1',
        reply: {
          id: 'reply-live',
          post_id: 'post-1',
          workspace_id: 'ws-1',
          author_id: 'u-2',
          content: 'Newest',
          metadata: {},
          created_at: '2026-03-30T10:00:01Z',
        },
      },
    });

    resolveReplies?.([
      {
        id: 'reply-old',
        post_id: 'post-1',
        workspace_id: 'ws-1',
        author_id: 'u-1',
        content: 'Older',
        metadata: {},
        created_at: '2026-03-30T10:00:00Z',
      },
    ]);
    await loadPromise;

    expect(useWorkspaceStore.getState().repliesByPostId['post-1']).toEqual([
      expect.objectContaining({ id: 'reply-old' }),
      expect.objectContaining({ id: 'reply-live' }),
    ]);
    expect(useWorkspaceStore.getState().loadedReplyPostIds['post-1']).toBe(true);
  });

  it('loadReplies skips duplicate requests while the same post is already loading', async () => {
    let resolveReplies: ((value: any) => void) | null = null;
    const repliesPromise = new Promise((resolve) => {
      resolveReplies = resolve;
    });

    useWorkspaceStore.setState({
      currentWorkspace: {
        id: 'ws-1',
        tenant_id: 't-1',
        project_id: 'p-1',
        name: 'Alpha',
        created_by: 'u-1',
        created_at: '',
      } as any,
      repliesByPostId: {},
      loadedReplyPostIds: {},
      replyLoadingPostIds: {},
    });
    vi.mocked(workspaceBlackboardService.listReplies).mockReturnValue(
      repliesPromise as Promise<any>
    );

    const firstLoad = useWorkspaceStore.getState().loadReplies('t-1', 'p-1', 'ws-1', 'post-1');
    const secondLoad = useWorkspaceStore.getState().loadReplies('t-1', 'p-1', 'ws-1', 'post-1');

    expect(workspaceBlackboardService.listReplies).toHaveBeenCalledTimes(1);

    resolveReplies?.([]);
    await Promise.all([firstLoad, secondLoad]);

    expect(useWorkspaceStore.getState().replyLoadingPostIds['post-1']).toBeUndefined();
    expect(useWorkspaceStore.getState().loadedReplyPostIds['post-1']).toBe(true);
  });

  it('loadReplies does not restore reply state after the post is deleted mid-flight', async () => {
    let resolveReplies: ((value: any) => void) | null = null;
    const repliesPromise = new Promise((resolve) => {
      resolveReplies = resolve;
    });

    useWorkspaceStore.setState({
      currentWorkspace: {
        id: 'ws-1',
        tenant_id: 't-1',
        project_id: 'p-1',
        name: 'Alpha',
        created_by: 'u-1',
        created_at: '',
      } as any,
      posts: [{ id: 'post-1', title: 'Question', content: 'How?', status: 'open' }] as any,
      repliesByPostId: {},
      loadedReplyPostIds: {},
      replyLoadingPostIds: {},
    });
    vi.mocked(workspaceBlackboardService.listReplies).mockReturnValueOnce(
      repliesPromise as Promise<any>
    );

    const loadPromise = useWorkspaceStore.getState().loadReplies('t-1', 'p-1', 'ws-1', 'post-1');

    useWorkspaceStore.getState().handleBlackboardEvent({
      type: 'blackboard_post_deleted',
      data: { post_id: 'post-1' },
    });

    resolveReplies?.([
      {
        id: 'reply-1',
        post_id: 'post-1',
        workspace_id: 'ws-1',
        author_id: 'u-1',
        content: 'Older',
        metadata: {},
        created_at: '2026-03-30T10:00:00Z',
      },
    ]);
    await loadPromise;

    const state = useWorkspaceStore.getState();
    expect(state.posts).toEqual([]);
    expect(state.repliesByPostId['post-1']).toBeUndefined();
    expect(state.loadedReplyPostIds['post-1']).toBeUndefined();
    expect(state.replyLoadingPostIds['post-1']).toBeUndefined();
  });

  it('loadWorkspaceSurface ignores stale responses from older workspace requests', async () => {
    let resolveFirstWorkspace: ((value: any) => void) | null = null;
    const firstWorkspacePromise = new Promise((resolve) => {
      resolveFirstWorkspace = resolve;
    });

    vi.mocked(workspaceService.getById)
      .mockReturnValueOnce(firstWorkspacePromise as Promise<any>)
      .mockResolvedValueOnce({
        id: 'ws-2',
        tenant_id: 't-1',
        project_id: 'p-1',
        name: 'Beta',
        created_by: 'u-1',
        created_at: '',
      } as any);
    vi.mocked(workspaceService.listMembers).mockResolvedValue([]);
    vi.mocked(workspaceService.listAgents).mockResolvedValue([]);
    vi.mocked(workspaceBlackboardService.listPosts)
      .mockResolvedValueOnce([
        { id: 'post-1', title: 'Alpha', content: 'A', status: 'open' },
      ] as any)
      .mockResolvedValueOnce([
        { id: 'post-2', title: 'Beta', content: 'B', status: 'open' },
      ] as any);
    vi.mocked(workspaceTaskService.list)
      .mockResolvedValueOnce([{ id: 'task-1', title: 'Alpha task', status: 'todo' }] as any)
      .mockResolvedValueOnce([{ id: 'task-2', title: 'Beta task', status: 'done' }] as any);
    vi.mocked(workspaceTopologyService.listNodes).mockResolvedValue([]);
    vi.mocked(workspaceTopologyService.listEdges).mockResolvedValue([]);
    vi.mocked(workspaceObjectiveService.list).mockResolvedValue([]);
    vi.mocked(workspaceGeneService.list).mockResolvedValue([]);
    vi.mocked(workspaceChatService.listMessages).mockResolvedValue([]);

    const firstLoad = useWorkspaceStore.getState().loadWorkspaceSurface('t-1', 'p-1', 'ws-1');
    const secondLoad = useWorkspaceStore.getState().loadWorkspaceSurface('t-1', 'p-1', 'ws-2');

    await secondLoad;
    resolveFirstWorkspace?.({
      id: 'ws-1',
      tenant_id: 't-1',
      project_id: 'p-1',
      name: 'Alpha',
      created_by: 'u-1',
      created_at: '',
    });
    await firstLoad;

    const state = useWorkspaceStore.getState();
    expect(state.currentWorkspace?.id).toBe('ws-2');
    expect(state.posts[0].id).toBe('post-2');
    expect(state.tasks[0].id).toBe('task-2');
  });

  it('useWorkspaceReplies returns stable empty array reference when post has no replies', () => {
    const { result, rerender } = renderHook(() => useWorkspaceReplies('missing-post'));
    const firstValue = result.current;

    rerender();

    expect(result.current).toBe(firstValue);
    expect(result.current).toEqual([]);
  });

  it('moveAgent uses workspace binding id and upserts the updated agent payload', async () => {
    useWorkspaceStore.setState({
      agents: [
        {
          id: 'binding-1',
          agent_id: 'agent-alpha',
          hex_q: 0,
          hex_r: 0,
          is_active: true,
        },
      ] as any,
    });
    vi.mocked(workspaceService.updateAgentBinding).mockResolvedValueOnce({
      id: 'binding-1',
      agent_id: 'agent-alpha',
      hex_q: 2,
      hex_r: -1,
      is_active: true,
    } as any);

    await useWorkspaceStore
      .getState()
      .moveAgent('tenant-1', 'project-1', 'ws-1', 'binding-1', 2, -1);

    expect(workspaceService.updateAgentBinding).toHaveBeenCalledWith(
      'tenant-1',
      'project-1',
      'ws-1',
      'binding-1',
      { hex_q: 2, hex_r: -1 }
    );
    expect(useWorkspaceStore.getState().agents).toEqual([
      expect.objectContaining({ id: 'binding-1', hex_q: 2, hex_r: -1 }),
    ]);
  });

  it('updateTopologyNode keeps connected edge coordinates in sync locally', async () => {
    useWorkspaceStore.setState({
      topologyNodes: [
        {
          id: 'node-1',
          node_type: 'corridor',
          title: 'Lane',
          hex_q: 1,
          hex_r: 0,
          position_x: 0,
          position_y: 0,
        },
      ] as any,
      topologyEdges: [
        {
          id: 'edge-1',
          source_node_id: 'node-1',
          target_node_id: 'node-2',
          source_hex_q: 1,
          source_hex_r: 0,
          target_hex_q: 2,
          target_hex_r: 0,
        },
      ] as any,
    });
    vi.mocked(workspaceTopologyService.updateNode).mockResolvedValueOnce({
      id: 'node-1',
      node_type: 'corridor',
      title: 'Lane',
      hex_q: 3,
      hex_r: -1,
      position_x: 0,
      position_y: 0,
    } as any);

    await useWorkspaceStore
      .getState()
      .updateTopologyNode('ws-1', 'node-1', { hex_q: 3, hex_r: -1 });

    expect(useWorkspaceStore.getState().topologyEdges).toEqual([
      expect.objectContaining({
        id: 'edge-1',
        source_hex_q: 3,
        source_hex_r: -1,
        target_hex_q: 2,
        target_hex_r: 0,
      }),
    ]);
  });

  it('handleAgentBindingEvent upserts existing agents from event payloads', () => {
    useWorkspaceStore.setState({
      agents: [
        {
          id: 'binding-1',
          agent_id: 'agent-alpha',
          display_name: 'Old name',
          config: { retained: true },
          is_active: true,
        },
      ] as any,
    });

    useWorkspaceStore.getState().handleAgentBindingEvent({
      type: 'workspace_agent_bound',
      data: {
        agent: {
          id: 'binding-1',
          agent_id: 'agent-alpha',
          display_name: 'Updated name',
          hex_q: 4,
          hex_r: -2,
          is_active: true,
        },
      },
    });

    expect(useWorkspaceStore.getState().agents).toEqual([
      expect.objectContaining({
        id: 'binding-1',
        display_name: 'Updated name',
        config: { retained: true },
        hex_q: 4,
        hex_r: -2,
      }),
    ]);
  });

  it('handleAgentBindingEvent removes agents on workspace_agent_unbound payloads', () => {
    useWorkspaceStore.setState({
      agents: [
        {
          id: 'binding-1',
          agent_id: 'agent-alpha',
          is_active: true,
        },
      ] as any,
    });

    useWorkspaceStore.getState().handleAgentBindingEvent({
      type: 'workspace_agent_unbound',
      data: {
        workspace_agent_id: 'binding-1',
      },
    });

    expect(useWorkspaceStore.getState().agents).toEqual([]);
  });

  it('handleTaskEvent upserts full task payloads from workspace_task_assigned events', () => {
    useWorkspaceStore.setState({
      tasks: [],
    });

    useWorkspaceStore.getState().handleTaskEvent({
      type: 'workspace_task_assigned',
      data: {
        workspace_agent_id: 'binding-1',
        task: {
          id: 'task-1',
          workspace_id: 'ws-1',
          title: 'Execute root goal',
          status: 'todo',
          priority: 'P1',
          metadata: {
            goal_evidence: {
              goal_task_id: 'task-1',
            },
          },
          created_at: '2026-04-15T10:00:00Z',
        },
      },
    });

    expect(useWorkspaceStore.getState().tasks).toEqual([
      expect.objectContaining({
        id: 'task-1',
        priority: 'P1',
        workspace_agent_id: 'binding-1',
        metadata: {
          goal_evidence: {
            goal_task_id: 'task-1',
          },
        },
      }),
    ]);
  });

  it('handleTaskEvent ignores malformed task payloads', () => {
    useWorkspaceStore.setState({
      tasks: [
        {
          id: 'task-existing',
          workspace_id: 'ws-1',
          title: 'Existing task',
          status: 'todo',
          metadata: {},
          created_at: '2026-04-15T09:00:00Z',
        },
      ] as any,
    });

    useWorkspaceStore.getState().handleTaskEvent({
      type: 'workspace_task_created',
      data: {
        task: {
          title: 'Missing identity',
          status: 'todo',
        },
      },
    });

    expect(useWorkspaceStore.getState().tasks).toEqual([
      expect.objectContaining({ id: 'task-existing' }),
    ]);
  });

  it('handlePlanEvent increments the workspace plan refresh counter', () => {
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: 'ws-fallback',
        tenant_id: 't-1',
        project_id: 'p-1',
        name: 'Fallback',
        created_by: 'u-1',
        created_at: '',
      } as any,
      planRefreshCounters: {},
    });

    useWorkspaceStore.getState().handlePlanEvent({
      type: 'workspace_plan_updated',
      data: { workspace_id: 'ws-1', plan_id: 'plan-1' },
    });
    useWorkspaceStore.getState().handlePlanEvent({
      type: 'workspace_plan_updated',
      data: { workspace_id: 'ws-1', plan_id: 'plan-1' },
    });
    useWorkspaceStore.getState().handlePlanEvent({
      type: 'workspace_plan_updated',
      data: { plan_id: 'plan-fallback' },
    });

    expect(useWorkspaceStore.getState().planRefreshCounters).toEqual({
      'ws-1': 2,
      'ws-fallback': 1,
    });
  });

  it('handleTopologyEvent applies node update deltas with connected edge sync', () => {
    useWorkspaceStore.setState({
      topologyNodes: [{ id: 'node-1', node_type: 'corridor', hex_q: 1, hex_r: 0 }] as any,
      topologyEdges: [
        {
          id: 'edge-1',
          source_node_id: 'node-1',
          target_node_id: 'node-2',
          source_hex_q: 1,
          source_hex_r: 0,
          target_hex_q: 2,
          target_hex_r: 0,
        },
      ] as any,
    });

    useWorkspaceStore.getState().handleTopologyEvent({
      type: 'topology_updated',
      data: {
        operation: 'node_updated',
        node_id: 'node-1',
        node: {
          id: 'node-1',
          node_type: 'corridor',
          hex_q: 4,
          hex_r: -2,
          position_x: 0,
          position_y: 0,
        },
        updated_edges: [
          {
            id: 'edge-1',
            source_node_id: 'node-1',
            target_node_id: 'node-2',
            source_hex_q: 4,
            source_hex_r: -2,
            target_hex_q: 2,
            target_hex_r: 0,
          },
        ],
      },
    });

    expect(useWorkspaceStore.getState().topologyNodes).toEqual([
      expect.objectContaining({ id: 'node-1', hex_q: 4, hex_r: -2 }),
    ]);
    expect(useWorkspaceStore.getState().topologyEdges).toEqual([
      expect.objectContaining({ id: 'edge-1', source_hex_q: 4, source_hex_r: -2 }),
    ]);
  });

  it('handleTopologyEvent still replaces topology state from snapshot payloads', () => {
    useWorkspaceStore.setState({
      topologyNodes: [{ id: 'old-node' }] as any,
      topologyEdges: [{ id: 'old-edge' }] as any,
    });

    useWorkspaceStore.getState().handleTopologyEvent({
      type: 'topology_updated',
      data: {
        nodes: [{ id: 'node-1', node_type: 'corridor', hex_q: 1, hex_r: 0 }],
        edges: [{ id: 'edge-1', source_node_id: 'node-1', target_node_id: 'node-1' }],
      },
    });

    expect(useWorkspaceStore.getState().topologyNodes).toEqual([
      expect.objectContaining({ id: 'node-1' }),
    ]);
    expect(useWorkspaceStore.getState().topologyEdges).toEqual([
      expect.objectContaining({ id: 'edge-1' }),
    ]);
  });

  it('handleTopologyEvent ignores malformed topology snapshots', () => {
    useWorkspaceStore.setState({
      topologyNodes: [{ id: 'old-node' }] as any,
      topologyEdges: [{ id: 'old-edge' }] as any,
    });

    useWorkspaceStore.getState().handleTopologyEvent({
      type: 'topology_updated',
      data: {
        nodes: [{ title: 'Missing identity' }],
        edges: [{ source_node_id: 'old-node' }],
      },
    });

    expect(useWorkspaceStore.getState().topologyNodes).toEqual([
      expect.objectContaining({ id: 'old-node' }),
    ]);
    expect(useWorkspaceStore.getState().topologyEdges).toEqual([
      expect.objectContaining({ id: 'old-edge' }),
    ]);
  });

  it('ignores live surface events for inactive workspaces', () => {
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: 'ws-1',
        tenant_id: 't-1',
        project_id: 'p-1',
        name: 'Alpha',
        created_by: 'u-1',
        created_at: '',
      } as any,
      chatMessages: [
        {
          id: 'msg-current',
          workspace_id: 'ws-1',
          content: 'current',
          created_at: '2026-03-30T10:00:00Z',
        },
      ] as any,
      tasks: [
        {
          id: 'task-current',
          workspace_id: 'ws-1',
          title: 'Current task',
          status: 'todo',
          metadata: {},
          created_at: '2026-03-30T10:00:00Z',
        },
      ] as any,
      posts: [
        {
          id: 'post-current',
          workspace_id: 'ws-1',
          author_id: 'u-1',
          title: 'Current post',
          content: 'hello',
          status: 'open',
          is_pinned: false,
          metadata: {},
          created_at: '2026-03-30T10:00:00Z',
        },
      ] as any,
      members: [
        {
          id: 'member-current',
          workspace_id: 'ws-1',
          user_id: 'u-1',
          role: 'owner',
          created_at: '2026-03-30T10:00:00Z',
        },
      ] as any,
      agents: [
        {
          id: 'binding-current',
          workspace_id: 'ws-1',
          agent_id: 'agent-current',
          is_active: true,
          created_at: '2026-03-30T10:00:00Z',
        },
      ] as any,
      topologyNodes: [
        {
          id: 'node-current',
          workspace_id: 'ws-1',
          node_type: 'corridor',
          title: 'Current node',
          position_x: 0,
          position_y: 0,
          data: {},
        },
      ] as any,
      topologyEdges: [],
      onlineUsers: [],
      onlineAgents: [],
    });

    useWorkspaceStore.getState().handleChatEvent({
      type: 'workspace_message_created',
      data: {
        message: {
          id: 'msg-other',
          workspace_id: 'ws-2',
          content: 'other',
          created_at: '2026-03-30T10:01:00Z',
        },
        surface_boundary: HOSTED,
        signal_role: SENSING_CAPABLE,
      },
    });
    useWorkspaceStore.getState().handleTaskEvent({
      type: 'workspace_task_created',
      data: {
        task: {
          id: 'task-other',
          workspace_id: 'ws-2',
          title: 'Other task',
          status: 'todo',
          metadata: {},
          created_at: '2026-03-30T10:01:00Z',
        },
      },
    });
    useWorkspaceStore.getState().handleBlackboardEvent({
      type: 'blackboard_post_created',
      data: {
        post: {
          id: 'post-other',
          workspace_id: 'ws-2',
          author_id: 'u-2',
          title: 'Other post',
          content: 'ignored',
          status: 'open',
          is_pinned: false,
          metadata: {},
          created_at: '2026-03-30T10:01:00Z',
        },
        surface_boundary: OWNED,
        authority_class: AUTHORITATIVE,
      },
    });
    useWorkspaceStore.getState().handleMemberEvent({
      type: 'workspace_member_joined',
      data: {
        member: {
          id: 'member-other',
          workspace_id: 'ws-2',
          user_id: 'u-2',
          role: 'editor',
          created_at: '2026-03-30T10:01:00Z',
        },
      },
    });
    useWorkspaceStore.getState().handleAgentBindingEvent({
      type: 'workspace_agent_bound',
      data: {
        agent: {
          id: 'binding-other',
          workspace_id: 'ws-2',
          agent_id: 'agent-other',
          is_active: true,
          created_at: '2026-03-30T10:01:00Z',
        },
      },
    });
    useWorkspaceStore.getState().handleTopologyEvent({
      type: 'topology_updated',
      data: {
        workspace_id: 'ws-2',
        nodes: [
          {
            id: 'node-other',
            workspace_id: 'ws-2',
            node_type: 'corridor',
            title: 'Other node',
            position_x: 0,
            position_y: 0,
            data: {},
          },
        ],
        edges: [],
      },
    });
    useWorkspaceStore.getState().handlePresenceEvent({
      type: 'workspace.presence.joined',
      data: { workspace_id: 'ws-2', user_id: 'u-2', display_name: 'Other' },
    });
    useWorkspaceStore.getState().handleAgentStatusEvent({
      type: 'workspace.agent.status',
      data: {
        workspace_id: 'ws-2',
        agent_id: 'agent-other',
        display_name: 'Other',
        status: 'idle',
      },
    });

    const state = useWorkspaceStore.getState();
    expect(state.chatMessages).toEqual([expect.objectContaining({ id: 'msg-current' })]);
    expect(state.tasks).toEqual([expect.objectContaining({ id: 'task-current' })]);
    expect(state.posts).toEqual([expect.objectContaining({ id: 'post-current' })]);
    expect(state.members).toEqual([expect.objectContaining({ id: 'member-current' })]);
    expect(state.agents).toEqual([expect.objectContaining({ id: 'binding-current' })]);
    expect(state.topologyNodes).toEqual([expect.objectContaining({ id: 'node-current' })]);
    expect(state.onlineUsers).toEqual([]);
    expect(state.onlineAgents).toEqual([]);
  });
});
