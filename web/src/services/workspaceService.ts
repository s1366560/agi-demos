import { apiFetch } from './client/urlUtils';

import type {
  BlackboardPost,
  BlackboardReply,
  TopologyEdge,
  TopologyNode,
  Workspace,
  WorkspaceAgent,
  WorkspaceCreateRequest,
  WorkspaceMember,
  WorkspaceTask,
  WorkspaceUpdateRequest,
} from '@/types/workspace';

const workspaceBase = (tenantId: string, projectId: string) =>
  `/tenants/${tenantId}/projects/${projectId}/workspaces`;

const blackboardBase = (tenantId: string, projectId: string, workspaceId: string) =>
  `${workspaceBase(tenantId, projectId)}/${workspaceId}/blackboard`;

const taskBase = (workspaceId: string) => `/workspaces/${workspaceId}/tasks`;

const topologyBase = (workspaceId: string) => `/workspaces/${workspaceId}/topology`;

function normalizeListResponse<T>(
  payload: unknown,
  keys: Array<'items' | 'workspaces' | 'members' | 'agents'>
): T[] {
  if (Array.isArray(payload)) {
    return payload as T[];
  }
  if (payload && typeof payload === 'object') {
    for (const key of keys) {
      const value = (payload as Record<string, unknown>)[key];
      if (Array.isArray(value)) {
        return value as T[];
      }
    }
  }
  return [];
}

export const workspaceService = {
  listByProject: async (tenantId: string, projectId: string): Promise<Workspace[]> => {
    const response = await apiFetch.get(workspaceBase(tenantId, projectId), {
      retry: {
        maxRetries: 1,
      },
    });
    const payload: unknown = await response.json();
    return normalizeListResponse<Workspace>(payload, ['items', 'workspaces']);
  },

  getById: async (tenantId: string, projectId: string, workspaceId: string): Promise<Workspace> => {
    const response = await apiFetch.get(`${workspaceBase(tenantId, projectId)}/${workspaceId}`);
    return response.json() as Promise<Workspace>;
  },

  create: async (
    tenantId: string,
    projectId: string,
    data: WorkspaceCreateRequest
  ): Promise<Workspace> => {
    const response = await apiFetch.post(workspaceBase(tenantId, projectId), data);
    return response.json() as Promise<Workspace>;
  },

  update: async (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    data: WorkspaceUpdateRequest
  ): Promise<Workspace> => {
    const response = await apiFetch.patch(
      `${workspaceBase(tenantId, projectId)}/${workspaceId}`,
      data
    );
    return response.json() as Promise<Workspace>;
  },

  remove: async (tenantId: string, projectId: string, workspaceId: string): Promise<void> => {
    await apiFetch.delete(`${workspaceBase(tenantId, projectId)}/${workspaceId}`);
  },

  listMembers: async (
    tenantId: string,
    projectId: string,
    workspaceId: string
  ): Promise<WorkspaceMember[]> => {
    const response = await apiFetch.get(
      `${workspaceBase(tenantId, projectId)}/${workspaceId}/members`
    );
    const payload: unknown = await response.json();
    return normalizeListResponse<WorkspaceMember>(payload, ['items', 'members']);
  },

  addMember: async (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    data: { user_id: string; role: string }
  ): Promise<WorkspaceMember> => {
    const response = await apiFetch.post(
      `${workspaceBase(tenantId, projectId)}/${workspaceId}/members`,
      data
    );
    return response.json() as Promise<WorkspaceMember>;
  },

  removeMember: async (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    memberId: string
  ): Promise<void> => {
    await apiFetch.delete(
      `${workspaceBase(tenantId, projectId)}/${workspaceId}/members/${memberId}`
    );
  },

  updateMemberRole: async (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    memberId: string,
    role: string
  ): Promise<WorkspaceMember> => {
    const response = await apiFetch.patch(
      `${workspaceBase(tenantId, projectId)}/${workspaceId}/members/${memberId}`,
      { role }
    );
    return response.json() as Promise<WorkspaceMember>;
  },

  listAgents: async (
    tenantId: string,
    projectId: string,
    workspaceId: string
  ): Promise<WorkspaceAgent[]> => {
    const response = await apiFetch.get(
      `${workspaceBase(tenantId, projectId)}/${workspaceId}/agents`
    );
    const payload: unknown = await response.json();
    return normalizeListResponse<WorkspaceAgent>(payload, ['items', 'agents']);
  },

  bindAgent: async (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    data: {
      agent_id: string;
      display_name?: string;
      description?: string;
      config?: Record<string, unknown>;
      is_active?: boolean;
      hex_q?: number;
      hex_r?: number;
      theme_color?: string;
      label?: string;
    }
  ): Promise<WorkspaceAgent> => {
    const response = await apiFetch.post(
      `${workspaceBase(tenantId, projectId)}/${workspaceId}/agents`,
      data
    );
    return response.json() as Promise<WorkspaceAgent>;
  },

  unbindAgent: async (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    workspaceAgentId: string
  ): Promise<void> => {
    await apiFetch.delete(
      `${workspaceBase(tenantId, projectId)}/${workspaceId}/agents/${workspaceAgentId}`
    );
  },
};

export const workspaceBlackboardService = {
  listPosts: async (
    tenantId: string,
    projectId: string,
    workspaceId: string
  ): Promise<BlackboardPost[]> => {
    const response = await apiFetch.get(
      `${blackboardBase(tenantId, projectId, workspaceId)}/posts`,
      {
        retry: {
          maxRetries: 1,
        },
      }
    );
    const payload = (await response.json()) as { items?: BlackboardPost[] };
    return payload.items ?? [];
  },

  createPost: async (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    data: Pick<BlackboardPost, 'title' | 'content'> &
      Partial<Pick<BlackboardPost, 'status' | 'is_pinned'>>
  ): Promise<BlackboardPost> => {
    const response = await apiFetch.post(
      `${blackboardBase(tenantId, projectId, workspaceId)}/posts`,
      data
    );
    return response.json() as Promise<BlackboardPost>;
  },

  listReplies: async (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    postId: string
  ): Promise<BlackboardReply[]> => {
    const response = await apiFetch.get(
      `${blackboardBase(tenantId, projectId, workspaceId)}/posts/${postId}/replies`
    );
    const payload = (await response.json()) as { items?: BlackboardReply[] };
    return payload.items ?? [];
  },

  createReply: async (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    postId: string,
    data: Pick<BlackboardReply, 'content'>
  ): Promise<BlackboardReply> => {
    const response = await apiFetch.post(
      `${blackboardBase(tenantId, projectId, workspaceId)}/posts/${postId}/replies`,
      data
    );
    return response.json() as Promise<BlackboardReply>;
  },
};

export const workspaceTaskService = {
  list: async (workspaceId: string): Promise<WorkspaceTask[]> => {
    const response = await apiFetch.get(taskBase(workspaceId), {
      retry: {
        maxRetries: 1,
      },
    });
    return response.json() as Promise<WorkspaceTask[]>;
  },

  create: async (
    workspaceId: string,
    data: Pick<WorkspaceTask, 'title'> &
      Partial<Pick<WorkspaceTask, 'description' | 'assignee_user_id'>>
  ): Promise<WorkspaceTask> => {
    const response = await apiFetch.post(taskBase(workspaceId), data);
    return response.json() as Promise<WorkspaceTask>;
  },

  update: async (
    workspaceId: string,
    taskId: string,
    data: Partial<
      Pick<
        WorkspaceTask,
        | 'title'
        | 'description'
        | 'status'
        | 'assignee_user_id'
        | 'assignee_agent_id'
        | 'priority'
        | 'estimated_effort'
        | 'blocker_reason'
      >
    >
  ): Promise<WorkspaceTask> => {
    const response = await apiFetch.patch(`${taskBase(workspaceId)}/${taskId}`, data);
    return response.json() as Promise<WorkspaceTask>;
  },

  assignToAgent: async (
    workspaceId: string,
    taskId: string,
    agentId: string
  ): Promise<WorkspaceTask> => {
    const response = await apiFetch.post(`${taskBase(workspaceId)}/${taskId}/assign-agent`, {
      agent_id: agentId,
    });
    return response.json() as Promise<WorkspaceTask>;
  },

  unassignAgent: async (workspaceId: string, taskId: string): Promise<WorkspaceTask> => {
    const response = await apiFetch.post(`${taskBase(workspaceId)}/${taskId}/unassign-agent`);
    return response.json() as Promise<WorkspaceTask>;
  },
};

export const workspaceTopologyService = {
  listNodes: async (workspaceId: string): Promise<TopologyNode[]> => {
    const response = await apiFetch.get(`${topologyBase(workspaceId)}/nodes`, {
      retry: {
        maxRetries: 1,
      },
    });
    return response.json() as Promise<TopologyNode[]>;
  },

  listEdges: async (workspaceId: string): Promise<TopologyEdge[]> => {
    const response = await apiFetch.get(`${topologyBase(workspaceId)}/edges`, {
      retry: {
        maxRetries: 1,
      },
    });
    return response.json() as Promise<TopologyEdge[]>;
  },

  moveAgentPosition: async (
    workspaceId: string,
    agentId: string,
    hexQ: number,
    hexR: number
  ): Promise<void> => {
    await apiFetch.patch(`/workspaces/${workspaceId}/agents/${agentId}`, {
      hex_q: hexQ,
      hex_r: hexR,
    });
  },
};

export const workspaceObjectiveService = {
  list: async (
    tenantId: string,
    projectId: string,
    workspaceId: string
  ): Promise<import('@/types/workspace').CyberObjective[]> => {
    const response = await apiFetch.get(
      `${workspaceBase(tenantId, projectId)}/${workspaceId}/objectives`
    );
    const payload: unknown = await response.json();
    return normalizeListResponse<import('@/types/workspace').CyberObjective>(payload, ['items']);
  },

  create: async (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    data: {
      title: string;
      description?: string;
      obj_type?: import('@/types/workspace').CyberObjectiveType;
      parent_id?: string;
    }
  ): Promise<import('@/types/workspace').CyberObjective> => {
    const response = await apiFetch.post(
      `${workspaceBase(tenantId, projectId)}/${workspaceId}/objectives`,
      data
    );
    return response.json() as Promise<import('@/types/workspace').CyberObjective>;
  },

  update: async (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    objectiveId: string,
    data: Partial<{ title: string; description: string; progress: number }>
  ): Promise<import('@/types/workspace').CyberObjective> => {
    const response = await apiFetch.patch(
      `${workspaceBase(tenantId, projectId)}/${workspaceId}/objectives/${objectiveId}`,
      data
    );
    return response.json() as Promise<import('@/types/workspace').CyberObjective>;
  },

  remove: async (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    objectiveId: string
  ): Promise<void> => {
    await apiFetch.delete(
      `${workspaceBase(tenantId, projectId)}/${workspaceId}/objectives/${objectiveId}`
    );
  },
};

export const workspaceGeneService = {
  list: async (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    params?: { category?: string; is_active?: boolean }
  ): Promise<import('@/types/workspace').CyberGene[]> => {
    let url = `${workspaceBase(tenantId, projectId)}/${workspaceId}/genes`;
    if (params) {
      const searchParams = new URLSearchParams();
      if (params.category) searchParams.append('category', params.category);
      if (params.is_active !== undefined)
        searchParams.append('is_active', String(params.is_active));
      const qs = searchParams.toString();
      if (qs) {
        url += `?${qs}`;
      }
    }
    const response = await apiFetch.get(url);
    const payload: unknown = await response.json();
    return normalizeListResponse<import('@/types/workspace').CyberGene>(payload, ['items']);
  },

  create: async (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    data: {
      name: string;
      category?: import('@/types/workspace').CyberGeneCategory;
      description?: string;
      config_json?: string;
    }
  ): Promise<import('@/types/workspace').CyberGene> => {
    const response = await apiFetch.post(
      `${workspaceBase(tenantId, projectId)}/${workspaceId}/genes`,
      data
    );
    return response.json() as Promise<import('@/types/workspace').CyberGene>;
  },

  update: async (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    geneId: string,
    data: Partial<{
      name: string;
      category: import('@/types/workspace').CyberGeneCategory;
      description: string;
      is_active: boolean;
      version: string;
    }>
  ): Promise<import('@/types/workspace').CyberGene> => {
    const response = await apiFetch.patch(
      `${workspaceBase(tenantId, projectId)}/${workspaceId}/genes/${geneId}`,
      data
    );
    return response.json() as Promise<import('@/types/workspace').CyberGene>;
  },

  remove: async (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    geneId: string
  ): Promise<void> => {
    await apiFetch.delete(`${workspaceBase(tenantId, projectId)}/${workspaceId}/genes/${geneId}`);
  },
};

const chatBase = (tenantId: string, projectId: string, workspaceId: string) =>
  `${workspaceBase(tenantId, projectId)}/${workspaceId}/messages`;

export const workspaceChatService = {
  listMessages: async (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    params?: { limit?: number; before?: string }
  ): Promise<import('@/types/workspace').WorkspaceMessage[]> => {
    let url = chatBase(tenantId, projectId, workspaceId);
    if (params) {
      const sp = new URLSearchParams();
      if (params.limit !== undefined) sp.append('limit', String(params.limit));
      if (params.before) sp.append('before', params.before);
      const qs = sp.toString();
      if (qs) url += `?${qs}`;
    }
    const response = await apiFetch.get(url, { retry: { maxRetries: 1 } });
    const payload = (await response.json()) as import('@/types/workspace').MessageListResponse;
    return payload.items;
  },

  sendMessage: async (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    data: import('@/types/workspace').SendMessageRequest
  ): Promise<import('@/types/workspace').WorkspaceMessage> => {
    const response = await apiFetch.post(chatBase(tenantId, projectId, workspaceId), data);
    return response.json() as Promise<import('@/types/workspace').WorkspaceMessage>;
  },

  getMentions: async (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    targetId: string,
    limit?: number
  ): Promise<import('@/types/workspace').WorkspaceMessage[]> => {
    let url = `${chatBase(tenantId, projectId, workspaceId)}/mentions/${targetId}`;
    if (limit !== undefined) url += '?limit=' + String(limit);
    const response = await apiFetch.get(url);
    const payload = (await response.json()) as import('@/types/workspace').MessageListResponse;
    return payload.items;
  },
};
