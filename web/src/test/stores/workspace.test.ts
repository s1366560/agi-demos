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
import { useWorkspaceReplies, useWorkspaceStore } from '@/stores/workspace';

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
    vi.mocked(workspaceBlackboardService.listReplies).mockReturnValueOnce(repliesPromise as Promise<any>);

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
    vi.mocked(workspaceBlackboardService.listReplies).mockReturnValue(repliesPromise as Promise<any>);

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
    vi.mocked(workspaceBlackboardService.listReplies).mockReturnValueOnce(repliesPromise as Promise<any>);

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
      .mockResolvedValueOnce([{ id: 'post-1', title: 'Alpha', content: 'A', status: 'open' }] as any)
      .mockResolvedValueOnce([{ id: 'post-2', title: 'Beta', content: 'B', status: 'open' }] as any);
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

    await useWorkspaceStore.getState().moveAgent(
      'tenant-1',
      'project-1',
      'ws-1',
      'binding-1',
      2,
      -1
    );

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
        { id: 'node-1', node_type: 'corridor', title: 'Lane', hex_q: 1, hex_r: 0, position_x: 0, position_y: 0 },
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

    await useWorkspaceStore.getState().updateTopologyNode('ws-1', 'node-1', { hex_q: 3, hex_r: -1 });

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
        metadata: {
          goal_evidence: {
            goal_task_id: 'task-1',
          },
        },
      }),
    ]);
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
        node: { id: 'node-1', node_type: 'corridor', hex_q: 4, hex_r: -2, position_x: 0, position_y: 0 },
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
});
