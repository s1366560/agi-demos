import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import {
  workspaceBlackboardService,
  workspaceService,
  workspaceTaskService,
  workspaceTopologyService,
  workspaceObjectiveService,
  workspaceGeneService,
  workspaceChatService,
} from '@/services/workspaceService';

import {
  isHostedSensingChatEventData,
  isOwnedBlackboardEventData,
} from '@/components/blackboard/blackboardSurfaceContract';

import { getErrorMessage } from '@/types/common';
import type {
  BlackboardPost,
  BlackboardReply,
  PresenceAgent,
  PresenceUser,
  TopologyEdge,
  TopologyNode,
  Workspace,
  WorkspaceAgent,
  WorkspaceMember,
  WorkspaceTask,
  CyberObjective,
  CyberGene,
  CyberObjectiveType,
  CyberGeneCategory,
  WorkspaceMessage,
  WorkspaceCreateRequest,
} from '@/types/workspace';

type WorkspaceSurfaceState = Pick<
  WorkspaceState,
  | 'currentWorkspace'
  | 'members'
  | 'agents'
  | 'posts'
  | 'repliesByPostId'
  | 'loadedReplyPostIds'
  | 'replyLoadingPostIds'
  | 'tasks'
  | 'topologyNodes'
  | 'topologyEdges'
  | 'objectives'
  | 'genes'
  | 'chatMessages'
>;

const createEmptySurfaceState = (): WorkspaceSurfaceState => ({
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
});

const hasLoadedReplies = (loadedReplyPostIds: Record<string, boolean>, postId: string): boolean =>
  loadedReplyPostIds[postId] === true;

let workspaceSurfaceRequestSequence = 0;
let workspaceListRequestSequence = 0;

const mergeReplies = (
  fetchedReplies: BlackboardReply[],
  existingReplies: BlackboardReply[]
): BlackboardReply[] => {
  const mergedReplies = new Map<string, BlackboardReply>();

  for (const reply of [...existingReplies, ...fetchedReplies]) {
    mergedReplies.set(reply.id, reply);
  }

  return Array.from(mergedReplies.values()).sort((left, right) =>
    left.created_at.localeCompare(right.created_at)
  );
};

function upsertById<T extends { id: string }>(items: T[], nextItem: T): T[] {
  const existingIndex = items.findIndex((item) => item.id === nextItem.id);
  if (existingIndex === -1) {
    return [...items, nextItem];
  }
  return items.map((item) => (item.id === nextItem.id ? nextItem : item));
}

function upsertManyById<T extends { id: string }>(items: T[], nextItems: T[]): T[] {
  return nextItems.reduce((acc, item) => upsertById(acc, item), items);
}

function workspaceBelongsToScope(
  workspace: Workspace | null,
  tenantId: string,
  projectId: string
): workspace is Workspace {
  return workspace?.tenant_id === tenantId && workspace.project_id === projectId;
}

function selectScopedWorkspace(
  workspaces: Workspace[],
  currentWorkspace: Workspace | null,
  tenantId: string,
  projectId: string
): Workspace | null {
  if (!workspaceBelongsToScope(currentWorkspace, tenantId, projectId)) {
    return workspaces[0] ?? null;
  }

  return workspaces.find((workspace) => workspace.id === currentWorkspace.id) ?? currentWorkspace;
}

function hasStringId(value: unknown): value is { id: string } {
  return (
    typeof value === 'object' &&
    value !== null &&
    'id' in value &&
    typeof value.id === 'string' &&
    value.id.length > 0
  );
}

function hasStringProperty(value: object, key: string): boolean {
  return key in value && typeof value[key as keyof typeof value] === 'string';
}

function isBlackboardPost(value: unknown): value is BlackboardPost {
  return (
    hasStringId(value) &&
    hasStringProperty(value, 'workspace_id') &&
    hasStringProperty(value, 'author_id') &&
    hasStringProperty(value, 'title') &&
    hasStringProperty(value, 'content') &&
    hasStringProperty(value, 'status') &&
    hasStringProperty(value, 'created_at') &&
    'is_pinned' in value &&
    typeof value.is_pinned === 'boolean' &&
    'metadata' in value &&
    typeof value.metadata === 'object' &&
    value.metadata !== null
  );
}

function isBlackboardReply(value: unknown): value is BlackboardReply {
  return (
    hasStringId(value) &&
    hasStringProperty(value, 'post_id') &&
    hasStringProperty(value, 'workspace_id') &&
    hasStringProperty(value, 'author_id') &&
    hasStringProperty(value, 'content') &&
    hasStringProperty(value, 'created_at') &&
    'metadata' in value &&
    typeof value.metadata === 'object' &&
    value.metadata !== null
  );
}

function isWorkspaceTask(value: unknown): value is WorkspaceTask {
  return (
    hasStringId(value) &&
    hasStringProperty(value, 'workspace_id') &&
    hasStringProperty(value, 'title') &&
    hasStringProperty(value, 'status') &&
    hasStringProperty(value, 'created_at') &&
    'metadata' in value &&
    typeof value.metadata === 'object' &&
    value.metadata !== null
  );
}

function hasOnlyIdentifiedItems<T extends { id: string }>(items: unknown[]): items is T[] {
  return items.every(hasStringId);
}

function getBlackboardFileEventWorkspaceId(data: Record<string, unknown>): string | null {
  if (typeof data.workspace_id === 'string' && data.workspace_id.length > 0) {
    return data.workspace_id;
  }
  const file = data.file;
  if (
    typeof file === 'object' &&
    file !== null &&
    'workspace_id' in file &&
    typeof file.workspace_id === 'string' &&
    file.workspace_id.length > 0
  ) {
    return file.workspace_id;
  }
  return null;
}

function getWorkspaceId(value: unknown): string | null {
  if (typeof value !== 'object' || value === null) {
    return null;
  }

  const workspaceId = (value as { workspace_id?: unknown }).workspace_id;
  return typeof workspaceId === 'string' && workspaceId.length > 0 ? workspaceId : null;
}

function getEventWorkspaceId(data: Record<string, unknown>): string | null {
  const directWorkspaceId = getWorkspaceId(data);
  if (directWorkspaceId) {
    return directWorkspaceId;
  }

  const objectKeys = [
    'workspace',
    'message',
    'task',
    'member',
    'agent',
    'post',
    'reply',
    'node',
    'edge',
    'file',
  ];
  for (const key of objectKeys) {
    const workspaceId = getWorkspaceId(data[key]);
    if (workspaceId) {
      return workspaceId;
    }
  }

  for (const key of ['nodes', 'edges']) {
    const items = data[key];
    if (!Array.isArray(items)) {
      continue;
    }
    for (const item of items) {
      const workspaceId = getWorkspaceId(item);
      if (workspaceId) {
        return workspaceId;
      }
    }
  }

  return null;
}

function isCurrentWorkspaceEvent(
  data: Record<string, unknown>,
  currentWorkspaceId: string | undefined
): boolean {
  const eventWorkspaceId = getEventWorkspaceId(data);
  return !eventWorkspaceId || !currentWorkspaceId || eventWorkspaceId === currentWorkspaceId;
}

function mergeWorkspaceAgentById(
  items: WorkspaceAgent[],
  nextItem: WorkspaceAgent
): WorkspaceAgent[] {
  const existingIndex = items.findIndex((item) => item.id === nextItem.id);
  if (existingIndex === -1) {
    return [...items, nextItem];
  }
  return items.map((item) => (item.id === nextItem.id ? { ...item, ...nextItem } : item));
}

function syncTopologyEdgesForNode(edges: TopologyEdge[], node: TopologyNode): TopologyEdge[] {
  if (node.hex_q === undefined || node.hex_r === undefined) {
    return edges;
  }
  return edges.map((edge) => {
    let nextEdge = edge;
    if (edge.source_node_id === node.id) {
      nextEdge = {
        ...nextEdge,
        source_hex_q: node.hex_q,
        source_hex_r: node.hex_r,
      };
    }
    if (edge.target_node_id === node.id) {
      nextEdge = {
        ...nextEdge,
        target_hex_q: node.hex_q,
        target_hex_r: node.hex_r,
      };
    }
    return nextEdge;
  });
}

interface WorkspaceState {
  workspaces: Workspace[];
  currentWorkspace: Workspace | null;
  members: WorkspaceMember[];
  agents: WorkspaceAgent[];
  posts: BlackboardPost[];
  repliesByPostId: Record<string, BlackboardReply[]>;
  loadedReplyPostIds: Record<string, boolean>;
  replyLoadingPostIds: Record<string, boolean>;
  tasks: WorkspaceTask[];
  topologyNodes: TopologyNode[];
  topologyEdges: TopologyEdge[];
  objectives: CyberObjective[];
  genes: CyberGene[];
  isLoading: boolean;
  activeSurfaceRequestId: number;
  error: string | null;
  onlineUsers: PresenceUser[];
  onlineAgents: PresenceAgent[];
  selectedHex: { q: number; r: number } | null;
  planRefreshCounters: Record<string, number>;
  fileRefreshCounters: Record<string, number>;

  chatMessages: WorkspaceMessage[];
  chatLoading: boolean;
  loadChatMessages: (tenantId: string, projectId: string, workspaceId: string) => Promise<void>;
  sendChatMessage: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    content: string,
    mentions?: string[]
  ) => Promise<void>;
  handleChatEvent: (event: { type: string; data: Record<string, unknown> }) => void;

  loadObjectives: (tenantId: string, projectId: string, workspaceId: string) => Promise<void>;
  createObjective: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    data: { title: string; description?: string; obj_type?: CyberObjectiveType; parent_id?: string }
  ) => Promise<void>;
  updateObjective: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    objectiveId: string,
    data: Partial<{ title: string; description: string; progress: number }>
  ) => Promise<void>;
  deleteObjective: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    objectiveId: string
  ) => Promise<void>;
  projectObjectiveToTask: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    objectiveId: string
  ) => Promise<void>;
  loadGenes: (tenantId: string, projectId: string, workspaceId: string) => Promise<void>;
  createGene: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    data: {
      name: string;
      category?: CyberGeneCategory;
      description?: string;
      config_json?: string;
      version?: string;
      is_active?: boolean;
    }
  ) => Promise<void>;
  updateGene: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    geneId: string,
    data: Partial<{
      name: string;
      category: CyberGeneCategory;
      description: string;
      config_json: string;
      is_active: boolean;
      version: string;
    }>
  ) => Promise<void>;
  deleteGene: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    geneId: string
  ) => Promise<void>;
  loadWorkspaces: (tenantId: string, projectId: string) => Promise<void>;
  loadWorkspaceSurface: (tenantId: string, projectId: string, workspaceId: string) => Promise<void>;
  setCurrentWorkspace: (workspace: Workspace | null) => void;
  createWorkspace: (
    tenantId: string,
    projectId: string,
    data: WorkspaceCreateRequest
  ) => Promise<Workspace>;
  createPost: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    data: { title: string; content: string }
  ) => Promise<void>;
  updatePost: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    postId: string,
    data: { title: string; content: string }
  ) => Promise<void>;
  loadReplies: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    postId: string
  ) => Promise<void>;
  createReply: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    postId: string,
    data: { content: string }
  ) => Promise<void>;
  updateReply: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    postId: string,
    replyId: string,
    data: { content: string }
  ) => Promise<void>;
  deletePost: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    postId: string
  ) => Promise<void>;
  pinPost: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    postId: string
  ) => Promise<void>;
  unpinPost: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    postId: string
  ) => Promise<void>;
  deleteReply: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    postId: string,
    replyId: string
  ) => Promise<void>;
  createTask: (workspaceId: string, data: { title: string; description?: string }) => Promise<void>;
  setTaskStatus: (
    workspaceId: string,
    taskId: string,
    status: WorkspaceTask['status']
  ) => Promise<void>;
  clearError: () => void;
  handlePresenceEvent: (event: { type: string; data: Record<string, unknown> }) => void;
  handleAgentStatusEvent: (event: { type: string; data: Record<string, unknown> }) => void;
  setOnlineUsers: (users: PresenceUser[]) => void;
  clearPresence: () => void;
  selectHex: (q: number, r: number) => void;
  clearSelectedHex: () => void;
  bindAgent: (
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
  ) => Promise<WorkspaceAgent>;
  updateAgentBinding: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    workspaceAgentId: string,
    data: Partial<{
      display_name: string;
      description: string;
      config: Record<string, unknown>;
      is_active: boolean;
      hex_q: number;
      hex_r: number;
      theme_color: string;
      label: string;
    }>
  ) => Promise<WorkspaceAgent>;
  unbindAgent: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    workspaceAgentId: string
  ) => Promise<void>;
  moveAgent: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    workspaceAgentId: string,
    q: number,
    r: number
  ) => Promise<WorkspaceAgent>;
  createTopologyNode: (
    workspaceId: string,
    data: {
      node_type: TopologyNode['node_type'];
      ref_id?: string;
      title?: string;
      position_x?: number;
      position_y?: number;
      hex_q?: number;
      hex_r?: number;
      status?: string;
      tags?: string[];
      data?: Record<string, unknown>;
    }
  ) => Promise<TopologyNode>;
  updateTopologyNode: (
    workspaceId: string,
    nodeId: string,
    data: Partial<{
      node_type: TopologyNode['node_type'];
      ref_id: string;
      title: string;
      position_x: number;
      position_y: number;
      hex_q: number;
      hex_r: number;
      status: string;
      tags: string[];
      data: Record<string, unknown>;
    }>
  ) => Promise<TopologyNode>;
  deleteTopologyNode: (workspaceId: string, nodeId: string) => Promise<void>;
  createTopologyEdge: (
    workspaceId: string,
    data: {
      source_node_id: string;
      target_node_id: string;
      label?: string;
      direction?: string;
      auto_created?: boolean;
      data?: Record<string, unknown>;
    }
  ) => Promise<TopologyEdge>;
  updateTopologyEdge: (
    workspaceId: string,
    edgeId: string,
    data: Partial<{
      source_node_id: string;
      target_node_id: string;
      label: string;
      direction: string;
      auto_created: boolean;
      data: Record<string, unknown>;
    }>
  ) => Promise<TopologyEdge>;
  deleteTopologyEdge: (workspaceId: string, edgeId: string) => Promise<void>;
  handleTopologyEvent: (event: { type: string; data: Record<string, unknown> }) => void;
  handleTaskEvent: (event: { type: string; data: Record<string, unknown> }) => void;
  handlePlanEvent: (event: { type: string; data: Record<string, unknown> }) => void;
  handleBlackboardEvent: (event: { type: string; data: Record<string, unknown> }) => void;
  handleMemberEvent: (event: { type: string; data: Record<string, unknown> }) => void;
  handleWorkspaceLifecycleEvent: (event: { type: string; data: Record<string, unknown> }) => void;
  handleAgentBindingEvent: (event: { type: string; data: Record<string, unknown> }) => void;
}

export const useWorkspaceStore = create<WorkspaceState>()(
  devtools(
    (set, get) => ({
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
      chatLoading: false,
      isLoading: false,
      activeSurfaceRequestId: 0,
      error: null,
      onlineUsers: [],
      onlineAgents: [],
      selectedHex: null,
      planRefreshCounters: {},
      fileRefreshCounters: {},

      loadWorkspaces: async (tenantId, projectId) => {
        const requestId = ++workspaceListRequestSequence;
        set({ isLoading: true, error: null });
        try {
          const workspaces = await workspaceService.listByProject(tenantId, projectId);
          if (workspaceListRequestSequence !== requestId) {
            return;
          }
          const previousWorkspace = get().currentWorkspace;
          const currentWorkspace = selectScopedWorkspace(
            workspaces,
            previousWorkspace,
            tenantId,
            projectId
          );
          const workspaceChanged = previousWorkspace?.id !== currentWorkspace?.id;
          set({
            ...(workspaceChanged ? createEmptySurfaceState() : {}),
            workspaces,
            currentWorkspace,
            isLoading: false,
          });
        } catch (error) {
          if (workspaceListRequestSequence !== requestId) {
            return;
          }
          set({ error: getErrorMessage(error), isLoading: false });
          throw error;
        }
      },

      loadWorkspaceSurface: async (tenantId, projectId, workspaceId) => {
        const requestId = ++workspaceSurfaceRequestSequence;
        set({ activeSurfaceRequestId: requestId, isLoading: true, error: null });
        try {
          const [
            workspace,
            members,
            agents,
            posts,
            tasks,
            topologyNodes,
            topologyEdges,
            objectives,
            genes,
            chatMessages,
          ] = await Promise.all([
            workspaceService.getById(tenantId, projectId, workspaceId),
            workspaceService.listMembers(tenantId, projectId, workspaceId),
            workspaceService.listAgents(tenantId, projectId, workspaceId),
            workspaceBlackboardService.listPosts(tenantId, projectId, workspaceId),
            workspaceTaskService.list(workspaceId),
            workspaceTopologyService.listNodes(workspaceId),
            workspaceTopologyService.listEdges(workspaceId),
            workspaceObjectiveService.list(tenantId, projectId, workspaceId),
            workspaceGeneService.list(tenantId, projectId, workspaceId),
            workspaceChatService.listMessages(tenantId, projectId, workspaceId),
          ]);

          if (get().activeSurfaceRequestId !== requestId) {
            return;
          }

          set({
            ...createEmptySurfaceState(),
            currentWorkspace: workspace,
            members,
            agents,
            posts,
            tasks,
            topologyNodes,
            topologyEdges,
            objectives,
            genes,
            chatMessages,
            isLoading: false,
          });
        } catch (error) {
          if (get().activeSurfaceRequestId !== requestId) {
            return;
          }
          set({
            ...createEmptySurfaceState(),
            error: getErrorMessage(error),
            isLoading: false,
          });
          throw error;
        }
      },

      loadObjectives: async (tenantId, projectId, workspaceId) => {
        set({ isLoading: true, error: null });
        try {
          const objectives = await workspaceObjectiveService.list(tenantId, projectId, workspaceId);
          set({ objectives, isLoading: false });
        } catch (error) {
          set({ error: getErrorMessage(error), isLoading: false });
          throw error;
        }
      },

      createObjective: async (tenantId, projectId, workspaceId, data) => {
        const obj = await workspaceObjectiveService.create(tenantId, projectId, workspaceId, data);
        set({ objectives: [...get().objectives, obj] });
      },

      updateObjective: async (tenantId, projectId, workspaceId, objectiveId, data) => {
        const updated = await workspaceObjectiveService.update(
          tenantId,
          projectId,
          workspaceId,
          objectiveId,
          data
        );
        set({ objectives: get().objectives.map((o) => (o.id === objectiveId ? updated : o)) });
      },

      deleteObjective: async (tenantId, projectId, workspaceId, objectiveId) => {
        await workspaceObjectiveService.remove(tenantId, projectId, workspaceId, objectiveId);
        set({ objectives: get().objectives.filter((o) => o.id !== objectiveId) });
      },

      projectObjectiveToTask: async (tenantId, projectId, workspaceId, objectiveId) => {
        const task = await workspaceObjectiveService.projectToTask(
          tenantId,
          projectId,
          workspaceId,
          objectiveId
        );
        set((state) => ({
          tasks: state.tasks.some((existing) => existing.id === task.id)
            ? state.tasks.map((existing) => (existing.id === task.id ? task : existing))
            : [task, ...state.tasks],
        }));
      },

      loadGenes: async (tenantId, projectId, workspaceId) => {
        set({ isLoading: true, error: null });
        try {
          const genes = await workspaceGeneService.list(tenantId, projectId, workspaceId);
          set({ genes, isLoading: false });
        } catch (error) {
          set({ error: getErrorMessage(error), isLoading: false });
          throw error;
        }
      },

      createGene: async (tenantId, projectId, workspaceId, data) => {
        const gene = await workspaceGeneService.create(tenantId, projectId, workspaceId, data);
        set({ genes: [...get().genes, gene] });
      },

      updateGene: async (tenantId, projectId, workspaceId, geneId, data) => {
        const updated = await workspaceGeneService.update(
          tenantId,
          projectId,
          workspaceId,
          geneId,
          data
        );
        set({ genes: get().genes.map((g) => (g.id === geneId ? updated : g)) });
      },

      deleteGene: async (tenantId, projectId, workspaceId, geneId) => {
        await workspaceGeneService.remove(tenantId, projectId, workspaceId, geneId);
        set({ genes: get().genes.filter((g) => g.id !== geneId) });
      },

      setCurrentWorkspace: (workspace) => {
        set({ currentWorkspace: workspace });
      },

      createWorkspace: async (tenantId, projectId, data) => {
        set({ isLoading: true, error: null });
        try {
          const workspace = await workspaceService.create(tenantId, projectId, data);
          set({
            workspaces: [...get().workspaces, workspace],
            currentWorkspace: workspace,
            isLoading: false,
          });
          return workspace;
        } catch (error) {
          set({ error: getErrorMessage(error), isLoading: false });
          throw error;
        }
      },

      createPost: async (tenantId, projectId, workspaceId, data) => {
        const post = await workspaceBlackboardService.createPost(
          tenantId,
          projectId,
          workspaceId,
          data
        );
        set((state) => ({
          posts: [post, ...state.posts],
          repliesByPostId: {
            ...state.repliesByPostId,
            [post.id]: [],
          },
          loadedReplyPostIds: {
            ...state.loadedReplyPostIds,
            [post.id]: true,
          },
        }));
      },

      updatePost: async (tenantId, projectId, workspaceId, postId, data) => {
        const post = await workspaceBlackboardService.updatePost(
          tenantId,
          projectId,
          workspaceId,
          postId,
          data
        );
        set((state) => ({
          posts: upsertById(state.posts, post),
        }));
      },

      loadReplies: async (tenantId, projectId, workspaceId, postId) => {
        const state = get();
        const startedWithExistingPost = state.posts.some((post) => post.id === postId);
        if (
          state.currentWorkspace?.id !== workspaceId ||
          hasLoadedReplies(state.loadedReplyPostIds, postId) ||
          state.replyLoadingPostIds[postId] === true
        ) {
          return;
        }

        set((current) => ({
          replyLoadingPostIds: {
            ...current.replyLoadingPostIds,
            [postId]: true,
          },
        }));

        try {
          const replies = await workspaceBlackboardService.listReplies(
            tenantId,
            projectId,
            workspaceId,
            postId
          );

          if (get().currentWorkspace?.id !== workspaceId) {
            return;
          }

          set((current) => {
            if (current.currentWorkspace?.id !== workspaceId) {
              return current;
            }
            if (startedWithExistingPost && !current.posts.some((post) => post.id === postId)) {
              return current;
            }

            const mergedReplies = mergeReplies(replies, current.repliesByPostId[postId] ?? []);

            return {
              repliesByPostId: {
                ...current.repliesByPostId,
                [postId]: mergedReplies,
              },
              loadedReplyPostIds: {
                ...current.loadedReplyPostIds,
                [postId]: true,
              },
            };
          });
        } finally {
          set((current) => {
            const { [postId]: _loadingReply, ...nextReplyLoadingPostIds } =
              current.replyLoadingPostIds;

            return {
              replyLoadingPostIds: nextReplyLoadingPostIds,
            };
          });
        }
      },

      createReply: async (tenantId, projectId, workspaceId, postId, data) => {
        const reply = await workspaceBlackboardService.createReply(
          tenantId,
          projectId,
          workspaceId,
          postId,
          data
        );
        set({
          repliesByPostId: {
            ...get().repliesByPostId,
            [postId]: mergeReplies([reply], get().repliesByPostId[postId] ?? []),
          },
        });
      },

      updateReply: async (tenantId, projectId, workspaceId, postId, replyId, data) => {
        const reply = await workspaceBlackboardService.updateReply(
          tenantId,
          projectId,
          workspaceId,
          postId,
          replyId,
          data
        );
        set((state) => ({
          repliesByPostId: {
            ...state.repliesByPostId,
            [postId]: mergeReplies([reply], state.repliesByPostId[postId] ?? []),
          },
        }));
      },

      deletePost: async (tenantId, projectId, workspaceId, postId) => {
        await workspaceBlackboardService.deletePost(tenantId, projectId, workspaceId, postId);
        set((state) => {
          const { [postId]: _removedReplies, ...nextRepliesByPostId } = state.repliesByPostId;
          const { [postId]: _loadedReplies, ...nextLoadedReplyPostIds } = state.loadedReplyPostIds;
          const { [postId]: _loadingReplies, ...nextReplyLoadingPostIds } =
            state.replyLoadingPostIds;

          return {
            posts: state.posts.filter((post) => post.id !== postId),
            repliesByPostId: nextRepliesByPostId,
            loadedReplyPostIds: nextLoadedReplyPostIds,
            replyLoadingPostIds: nextReplyLoadingPostIds,
          };
        });
      },

      pinPost: async (tenantId, projectId, workspaceId, postId) => {
        const post = await workspaceBlackboardService.pinPost(
          tenantId,
          projectId,
          workspaceId,
          postId
        );
        set((state) => ({
          posts: state.posts.map((entry) => (entry.id === post.id ? post : entry)),
        }));
      },

      unpinPost: async (tenantId, projectId, workspaceId, postId) => {
        const post = await workspaceBlackboardService.unpinPost(
          tenantId,
          projectId,
          workspaceId,
          postId
        );
        set((state) => ({
          posts: state.posts.map((entry) => (entry.id === post.id ? post : entry)),
        }));
      },

      deleteReply: async (tenantId, projectId, workspaceId, postId, replyId) => {
        await workspaceBlackboardService.deleteReply(
          tenantId,
          projectId,
          workspaceId,
          postId,
          replyId
        );
        set((state) => ({
          repliesByPostId: {
            ...state.repliesByPostId,
            [postId]: (state.repliesByPostId[postId] ?? []).filter((reply) => reply.id !== replyId),
          },
        }));
      },

      createTask: async (workspaceId, data) => {
        const task = await workspaceTaskService.create(workspaceId, data);
        set({ tasks: [task, ...get().tasks] });
      },

      setTaskStatus: async (workspaceId, taskId, status) => {
        const updated = await workspaceTaskService.update(workspaceId, taskId, { status });
        set({ tasks: get().tasks.map((task) => (task.id === taskId ? updated : task)) });
      },

      selectHex: (q, r) => {
        set({ selectedHex: { q, r } });
      },

      clearSelectedHex: () => {
        set({ selectedHex: null });
      },

      bindAgent: async (tenantId, projectId, workspaceId, data) => {
        const agent = await workspaceService.bindAgent(tenantId, projectId, workspaceId, data);
        set((state) => ({ agents: mergeWorkspaceAgentById(state.agents, agent) }));
        return agent;
      },

      updateAgentBinding: async (tenantId, projectId, workspaceId, workspaceAgentId, data) => {
        const agent = await workspaceService.updateAgentBinding(
          tenantId,
          projectId,
          workspaceId,
          workspaceAgentId,
          data
        );
        set((state) => ({ agents: mergeWorkspaceAgentById(state.agents, agent) }));
        return agent;
      },

      unbindAgent: async (tenantId, projectId, workspaceId, workspaceAgentId) => {
        await workspaceService.unbindAgent(tenantId, projectId, workspaceId, workspaceAgentId);
        set({ agents: get().agents.filter((a) => a.id !== workspaceAgentId) });
      },

      moveAgent: async (tenantId, projectId, workspaceId, workspaceAgentId, q, r) => {
        const agent = await workspaceService.updateAgentBinding(
          tenantId,
          projectId,
          workspaceId,
          workspaceAgentId,
          { hex_q: q, hex_r: r }
        );
        set((state) => ({ agents: mergeWorkspaceAgentById(state.agents, agent) }));
        return agent;
      },

      createTopologyNode: async (workspaceId, data) => {
        const node = await workspaceTopologyService.createNode(workspaceId, data);
        set((state) => ({ topologyNodes: upsertById(state.topologyNodes, node) }));
        return node;
      },

      updateTopologyNode: async (workspaceId, nodeId, data) => {
        const node = await workspaceTopologyService.updateNode(workspaceId, nodeId, data);
        set((state) => ({
          topologyNodes: upsertById(state.topologyNodes, node),
          topologyEdges: syncTopologyEdgesForNode(state.topologyEdges, node),
        }));
        return node;
      },

      deleteTopologyNode: async (workspaceId, nodeId) => {
        await workspaceTopologyService.deleteNode(workspaceId, nodeId);
        set((state) => ({
          topologyNodes: state.topologyNodes.filter((node) => node.id !== nodeId),
          topologyEdges: state.topologyEdges.filter(
            (edge) => edge.source_node_id !== nodeId && edge.target_node_id !== nodeId
          ),
        }));
      },

      createTopologyEdge: async (workspaceId, data) => {
        const edge = await workspaceTopologyService.createEdge(workspaceId, data);
        set((state) => ({ topologyEdges: upsertById(state.topologyEdges, edge) }));
        return edge;
      },

      updateTopologyEdge: async (workspaceId, edgeId, data) => {
        const edge = await workspaceTopologyService.updateEdge(workspaceId, edgeId, data);
        set((state) => ({ topologyEdges: upsertById(state.topologyEdges, edge) }));
        return edge;
      },

      deleteTopologyEdge: async (workspaceId, edgeId) => {
        await workspaceTopologyService.deleteEdge(workspaceId, edgeId);
        set((state) => ({
          topologyEdges: state.topologyEdges.filter((edge) => edge.id !== edgeId),
        }));
      },

      handleTopologyEvent: (event) => {
        const { type, data } = event;
        if (!isCurrentWorkspaceEvent(data, get().currentWorkspace?.id)) {
          return;
        }
        if (type === 'workspace.topology.agent_moved') {
          const agentId = data.agent_id as string;
          const hexQ = data.hex_q as number;
          const hexR = data.hex_r as number;
          if (typeof agentId !== 'string' || typeof hexQ !== 'number' || typeof hexR !== 'number') {
            return;
          }
          set({
            agents: get().agents.map((a) =>
              a.agent_id === agentId ? { ...a, hex_q: hexQ, hex_r: hexR } : a
            ),
          });
        } else if (type === 'topology_updated') {
          const nodes = data.nodes as TopologyNode[] | undefined;
          const edges = data.edges as TopologyEdge[] | undefined;
          if (Array.isArray(nodes) || Array.isArray(edges)) {
            if (
              (Array.isArray(nodes) && !hasOnlyIdentifiedItems<TopologyNode>(nodes)) ||
              (Array.isArray(edges) && !hasOnlyIdentifiedItems<TopologyEdge>(edges))
            ) {
              return;
            }
            set((state) => ({
              topologyNodes: nodes ?? state.topologyNodes,
              topologyEdges: edges ?? state.topologyEdges,
            }));
            return;
          }

          const operation = data.operation as string | undefined;
          if (operation === 'node_created' || operation === 'node_updated') {
            const node = data.node as TopologyNode | undefined;
            const updatedEdges = Array.isArray(data.updated_edges)
              ? (data.updated_edges as TopologyEdge[])
              : [];
            if (node) {
              set((state) => ({
                topologyNodes: upsertById(state.topologyNodes, node),
                topologyEdges: upsertManyById(
                  syncTopologyEdgesForNode(state.topologyEdges, node),
                  updatedEdges
                ),
              }));
            }
          } else if (operation === 'node_deleted') {
            const nodeId = data.node_id as string;
            set((state) => ({
              topologyNodes: state.topologyNodes.filter((node) => node.id !== nodeId),
              topologyEdges: state.topologyEdges.filter(
                (edge) => edge.source_node_id !== nodeId && edge.target_node_id !== nodeId
              ),
            }));
          } else if (operation === 'edge_created' || operation === 'edge_updated') {
            const edge = data.edge as TopologyEdge | undefined;
            if (edge) {
              set((state) => ({
                topologyEdges: upsertById(state.topologyEdges, edge),
              }));
            }
          } else if (operation === 'edge_deleted') {
            const edgeId = data.edge_id as string;
            set((state) => ({
              topologyEdges: state.topologyEdges.filter((edge) => edge.id !== edgeId),
            }));
          }
        }
      },

      handleTaskEvent: (event) => {
        const { type, data } = event;
        if (!isCurrentWorkspaceEvent(data, get().currentWorkspace?.id)) {
          return;
        }
        if (
          type === 'workspace_task_created' ||
          type === 'workspace_task_updated' ||
          type === 'workspace_task_status_changed'
        ) {
          const task = data.task;
          if (!isWorkspaceTask(task)) {
            return;
          }
          set((state) => ({
            tasks: state.tasks.some((t) => t.id === task.id)
              ? state.tasks.map((t) => (t.id === task.id ? task : t))
              : [...state.tasks, task],
          }));
        } else if (type === 'workspace_task_deleted') {
          const taskId = data.task_id as string;
          set((state) => ({
            tasks: state.tasks.filter((t) => t.id !== taskId),
          }));
        } else if (type === 'workspace_task_assigned') {
          const task = data.task;
          if (isWorkspaceTask(task)) {
            const workspaceAgentId =
              typeof data.workspace_agent_id === 'string' && data.workspace_agent_id.length > 0
                ? data.workspace_agent_id
                : task.workspace_agent_id;
            const normalizedTask: WorkspaceTask = workspaceAgentId
              ? { ...task, workspace_agent_id: workspaceAgentId }
              : task;
            set((state) => ({
              tasks: state.tasks.some((t) => t.id === normalizedTask.id)
                ? state.tasks.map((t) => (t.id === normalizedTask.id ? normalizedTask : t))
                : [...state.tasks, normalizedTask],
            }));
          }
        }
      },

      handlePlanEvent: (event) => {
        const { type, data } = event;
        if (type !== 'workspace_plan_updated') {
          return;
        }
        const workspaceId =
          typeof data.workspace_id === 'string' && data.workspace_id.length > 0
            ? data.workspace_id
            : get().currentWorkspace?.id;
        if (!workspaceId) {
          return;
        }
        set((state) => ({
          planRefreshCounters: {
            ...state.planRefreshCounters,
            [workspaceId]: (state.planRefreshCounters[workspaceId] ?? 0) + 1,
          },
        }));
      },

      handleBlackboardEvent: (event) => {
        const { type, data } = event;
        if (!isCurrentWorkspaceEvent(data, get().currentWorkspace?.id)) {
          return;
        }
        if (!isOwnedBlackboardEventData(data)) {
          return;
        }
        if (type === 'blackboard_post_created' || type === 'blackboard_post_updated') {
          const post = data.post;
          if (!isBlackboardPost(post)) {
            return;
          }
          set((state) => ({
            posts: state.posts.some((p) => p.id === post.id)
              ? state.posts.map((p) => (p.id === post.id ? post : p))
              : [post, ...state.posts],
          }));
        } else if (type === 'blackboard_post_deleted') {
          const postId = data.post_id as string;
          set((state) => {
            const { [postId]: _removedReplies, ...nextRepliesByPostId } = state.repliesByPostId;
            const { [postId]: _loadedReplies, ...nextLoadedReplyPostIds } =
              state.loadedReplyPostIds;
            const { [postId]: _loadingReplies, ...nextReplyLoadingPostIds } =
              state.replyLoadingPostIds;

            return {
              posts: state.posts.filter((p) => p.id !== postId),
              repliesByPostId: nextRepliesByPostId,
              loadedReplyPostIds: nextLoadedReplyPostIds,
              replyLoadingPostIds: nextReplyLoadingPostIds,
            };
          });
        } else if (type === 'blackboard_reply_created' || type === 'blackboard_reply_updated') {
          const reply = data.reply;
          if (!isBlackboardReply(reply)) {
            return;
          }
          const postId = typeof data.post_id === 'string' ? data.post_id : reply.post_id;
          if (!postId) {
            return;
          }
          set((state) => ({
            repliesByPostId: {
              ...state.repliesByPostId,
              [postId]: mergeReplies([reply], state.repliesByPostId[postId] || []),
            },
          }));
        } else if (type === 'blackboard_reply_deleted') {
          const replyId = data.reply_id as string;
          const postId = data.post_id as string;
          set((state) => ({
            repliesByPostId: {
              ...state.repliesByPostId,
              [postId]: (state.repliesByPostId[postId] || []).filter((r) => r.id !== replyId),
            },
          }));
        } else if (type === 'blackboard_file_created' || type === 'blackboard_file_deleted') {
          const workspaceId = getBlackboardFileEventWorkspaceId(data);
          if (!workspaceId) {
            return;
          }
          set((state) => ({
            fileRefreshCounters: {
              ...state.fileRefreshCounters,
              [workspaceId]: (state.fileRefreshCounters[workspaceId] ?? 0) + 1,
            },
          }));
        }
      },

      handleMemberEvent: (event) => {
        const { type, data } = event;
        if (!isCurrentWorkspaceEvent(data, get().currentWorkspace?.id)) {
          return;
        }
        if (type === 'workspace_member_joined') {
          const member = data.member as WorkspaceMember | undefined;
          if (member) {
            set((state) => ({ members: upsertById(state.members, member) }));
          }
        } else if (type === 'workspace_member_updated') {
          const member = data.member as WorkspaceMember | undefined;
          if (member) {
            set((state) => ({ members: upsertById(state.members, member) }));
          }
        } else if (type === 'workspace_member_left') {
          const member = data.member as WorkspaceMember | undefined;
          const memberId = typeof data.member_id === 'string' ? data.member_id : member?.id;
          const userId = typeof data.user_id === 'string' ? data.user_id : member?.user_id;
          set({
            members: get().members.filter((m) => m.id !== memberId && m.user_id !== userId),
          });
        }
      },

      handleWorkspaceLifecycleEvent: (event) => {
        const { type, data } = event;
        if (type === 'workspace_updated') {
          const workspace = data.workspace as Workspace | undefined;
          if (workspace) {
            set((state) => ({
              workspaces: state.workspaces.map((w) => (w.id === workspace.id ? workspace : w)),
              currentWorkspace:
                state.currentWorkspace?.id === workspace.id ? workspace : state.currentWorkspace,
            }));
          }
        } else if (type === 'workspace_deleted') {
          const workspaceId = data.workspace_id as string;
          set((state) => {
            const workspaces = state.workspaces.filter((w) => w.id !== workspaceId);
            const currentWorkspaceDeleted = state.currentWorkspace?.id === workspaceId;
            return {
              ...(currentWorkspaceDeleted ? createEmptySurfaceState() : {}),
              workspaces,
              currentWorkspace: currentWorkspaceDeleted
                ? (workspaces[0] ?? null)
                : state.currentWorkspace,
            };
          });
        }
      },

      handleAgentBindingEvent: (event) => {
        const { type, data } = event;
        if (!isCurrentWorkspaceEvent(data, get().currentWorkspace?.id)) {
          return;
        }
        if (type === 'workspace_agent_bound') {
          const agent = data.agent as WorkspaceAgent | undefined;
          if (agent) {
            set((state) => ({
              agents: mergeWorkspaceAgentById(state.agents, agent),
            }));
          }
        } else if (type === 'workspace_agent_unbound') {
          const agentBindingId = data.workspace_agent_id as string;
          set({ agents: get().agents.filter((a) => a.id !== agentBindingId) });
        }
      },

      clearError: () => {
        set({ error: null });
      },

      handlePresenceEvent: (event) => {
        const { type, data } = event;
        if (!isCurrentWorkspaceEvent(data, get().currentWorkspace?.id)) {
          return;
        }
        if (type === 'workspace.presence.joined') {
          const user: PresenceUser = {
            user_id: data.user_id as string,
            display_name: data.display_name as string,
            joined_at: new Date().toISOString(),
            last_heartbeat: new Date().toISOString(),
          };
          const existing = get().onlineUsers;
          const filtered = existing.filter((u) => u.user_id !== user.user_id);
          set({ onlineUsers: [...filtered, user] });
        } else if (type === 'workspace.presence.left') {
          set({
            onlineUsers: get().onlineUsers.filter((u) => u.user_id !== (data.user_id as string)),
          });
        }
      },

      handleAgentStatusEvent: (event) => {
        const { data } = event;
        if (!isCurrentWorkspaceEvent(data, get().currentWorkspace?.id)) {
          return;
        }
        const agent: PresenceAgent = {
          agent_id: data.agent_id as string,
          display_name: data.display_name as string,
          status: data.status as string,
        };
        const existing = get().onlineAgents;
        const filtered = existing.filter((a) => a.agent_id !== agent.agent_id);
        set({ onlineAgents: [...filtered, agent] });
      },

      setOnlineUsers: (users) => {
        set({ onlineUsers: users });
      },

      clearPresence: () => {
        set({ onlineUsers: [], onlineAgents: [] });
      },

      loadChatMessages: async (tenantId, projectId, workspaceId) => {
        set({ chatLoading: true });
        try {
          const messages = await workspaceChatService.listMessages(
            tenantId,
            projectId,
            workspaceId
          );
          set({ chatMessages: messages, chatLoading: false });
        } catch (error) {
          set({ error: getErrorMessage(error), chatLoading: false });
          throw error;
        }
      },

      sendChatMessage: async (tenantId, projectId, workspaceId, content, mentions = []) => {
        const message = await workspaceChatService.sendMessage(tenantId, projectId, workspaceId, {
          content,
          mentions,
        });
        set({ chatMessages: [...get().chatMessages, message] });
      },

      handleChatEvent: (event) => {
        const { type, data } = event;
        if (!isCurrentWorkspaceEvent(data, get().currentWorkspace?.id)) {
          return;
        }
        if (!isHostedSensingChatEventData(data)) {
          return;
        }
        if (type === 'workspace_message_created') {
          const msg = data.message as WorkspaceMessage | undefined;
          if (msg && !get().chatMessages.some((m) => m.id === msg.id)) {
            set({ chatMessages: [...get().chatMessages, msg] });
          }
        }
      },
    }),
    { name: 'WorkspaceStore', enabled: import.meta.env.DEV }
  )
);

export const useWorkspaces = () => useWorkspaceStore((state) => state.workspaces);
export const useCurrentWorkspace = () => useWorkspaceStore((state) => state.currentWorkspace);
export const useWorkspaceMembers = () => useWorkspaceStore((state) => state.members);
export const useWorkspaceAgents = () => useWorkspaceStore((state) => state.agents);
export const useWorkspacePosts = () => useWorkspaceStore((state) => state.posts);
export const useWorkspaceTasks = () => useWorkspaceStore((state) => state.tasks);
export const useWorkspaceObjectives = () => useWorkspaceStore((state) => state.objectives);
export const useWorkspaceGenes = () => useWorkspaceStore((state) => state.genes);
export const useWorkspaceTopology = () =>
  useWorkspaceStore(
    useShallow((state) => ({ nodes: state.topologyNodes, edges: state.topologyEdges }))
  );
const EMPTY_REPLIES: BlackboardReply[] = [];

export const useWorkspaceReplies = (postId: string) =>
  useWorkspaceStore((state) => state.repliesByPostId[postId] ?? EMPTY_REPLIES);
export const useWorkspaceLoading = () => useWorkspaceStore((state) => state.isLoading);
export const useWorkspaceError = () => useWorkspaceStore((state) => state.error);
export const useOnlineUsers = () => useWorkspaceStore((state) => state.onlineUsers);
export const useOnlineAgents = () => useWorkspaceStore((state) => state.onlineAgents);
export const useSelectedHex = () => useWorkspaceStore((state) => state.selectedHex);
export const useChatMessages = () => useWorkspaceStore((state) => state.chatMessages);
export const useChatLoading = () => useWorkspaceStore((state) => state.chatLoading);

export const useWorkspaceActions = () =>
  useWorkspaceStore(
    useShallow((state) => ({
      loadWorkspaces: state.loadWorkspaces,
      loadObjectives: state.loadObjectives,
      createObjective: state.createObjective,
      updateObjective: state.updateObjective,
      deleteObjective: state.deleteObjective,
      projectObjectiveToTask: state.projectObjectiveToTask,
      loadGenes: state.loadGenes,
      createGene: state.createGene,
      updateGene: state.updateGene,
      deleteGene: state.deleteGene,
      loadWorkspaceSurface: state.loadWorkspaceSurface,
      setCurrentWorkspace: state.setCurrentWorkspace,
      createWorkspace: state.createWorkspace,
      createPost: state.createPost,
      updatePost: state.updatePost,
      loadReplies: state.loadReplies,
      createReply: state.createReply,
      updateReply: state.updateReply,
      deletePost: state.deletePost,
      pinPost: state.pinPost,
      unpinPost: state.unpinPost,
      deleteReply: state.deleteReply,
      createTask: state.createTask,
      setTaskStatus: state.setTaskStatus,
      selectHex: state.selectHex,
      clearSelectedHex: state.clearSelectedHex,
      moveAgent: state.moveAgent,
      bindAgent: state.bindAgent,
      updateAgentBinding: state.updateAgentBinding,
      unbindAgent: state.unbindAgent,
      createTopologyNode: state.createTopologyNode,
      updateTopologyNode: state.updateTopologyNode,
      deleteTopologyNode: state.deleteTopologyNode,
      createTopologyEdge: state.createTopologyEdge,
      updateTopologyEdge: state.updateTopologyEdge,
      deleteTopologyEdge: state.deleteTopologyEdge,
      handleTopologyEvent: state.handleTopologyEvent,
      handleTaskEvent: state.handleTaskEvent,
      handleBlackboardEvent: state.handleBlackboardEvent,
      handleMemberEvent: state.handleMemberEvent,
      handleWorkspaceLifecycleEvent: state.handleWorkspaceLifecycleEvent,
      handleAgentBindingEvent: state.handleAgentBindingEvent,
      clearError: state.clearError,
      handlePresenceEvent: state.handlePresenceEvent,
      handleAgentStatusEvent: state.handleAgentStatusEvent,
      setOnlineUsers: state.setOnlineUsers,
      clearPresence: state.clearPresence,
      loadChatMessages: state.loadChatMessages,
      sendChatMessage: state.sendChatMessage,
      handleChatEvent: state.handleChatEvent,
    }))
  );
