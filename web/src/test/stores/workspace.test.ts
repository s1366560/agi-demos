import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';

import {
  workspaceBlackboardService,
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
      tasks: [],
      topologyNodes: [],
      topologyEdges: [],
      isLoading: false,
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
    vi.mocked(workspaceBlackboardService.listReplies).mockResolvedValueOnce([]);
    vi.mocked(workspaceTaskService.list).mockResolvedValueOnce([
      { id: 'task-1', title: 'Ship v1', status: 'todo' },
    ] as any);
    vi.mocked(workspaceTopologyService.listNodes).mockResolvedValueOnce([
      { id: 'node-1', node_type: 'task', title: 'Ship v1', position_x: 0, position_y: 0 },
    ] as any);
    vi.mocked(workspaceTopologyService.listEdges).mockResolvedValueOnce([
      { id: 'edge-1', source_node_id: 'node-1', target_node_id: 'node-1' },
    ] as any);

    await useWorkspaceStore.getState().loadWorkspaceSurface('t-1', 'p-1', 'ws-1');

    const state = useWorkspaceStore.getState();
    expect(state.currentWorkspace?.id).toBe('ws-1');
    expect(state.posts[0].id).toBe('post-1');
    expect(state.tasks[0].id).toBe('task-1');
    expect(state.topologyNodes[0].id).toBe('node-1');
    expect(state.topologyEdges[0].id).toBe('edge-1');
  });

  it('useWorkspaceReplies returns stable empty array reference when post has no replies', () => {
    const { result, rerender } = renderHook(() => useWorkspaceReplies('missing-post'));
    const firstValue = result.current;

    rerender();

    expect(result.current).toBe(firstValue);
    expect(result.current).toEqual([]);
  });
});
