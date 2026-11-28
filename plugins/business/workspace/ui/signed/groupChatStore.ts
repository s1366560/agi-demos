import { create } from 'zustand';
import type {
  Workspace,
  WorkspaceAgent,
  WorkspaceMember,
  WorkspaceMessage,
} from '../web/types/workspace';
import { readDirectory } from './readDirectory';

type State = {
  user: { id: string } | null;
  currentWorkspace: { id: string } | null;
  workspaces: Workspace[];
  agents: WorkspaceAgent[];
  members: WorkspaceMember[];
  chatMessages: WorkspaceMessage[];
  chatLoading: boolean;
  loadWorkspaces: () => Promise<void>;
  loadWorkspaceSurface: (tenant: string, project: string, workspace: string) => Promise<void>;
  loadChatMessages: (tenant: string, project: string, workspace: string) => Promise<void>;
  sendChatMessage: (
    tenant: string,
    project: string,
    workspace: string,
    content: string,
    mentions: string[]
  ) => Promise<void>;
};

const host = window.memstack;
let generation = 0;
let selected = '';
let readSequence = 0;
let loadedWorkspace: string | null = null;
export function selectWorkspace(id: string) {
  if (selected === id) return;
  selected = id;
  generation++;
  loadedWorkspace = null;
  useWorkspaceStore.setState({
    currentWorkspace: null,
    chatMessages: [],
    members: [],
    agents: [],
    chatLoading: false,
  });
}
export const useWorkspaceStore = create<State>((set) => ({
  user: null,
  currentWorkspace: null,
  workspaces: [],
  agents: [],
  members: [],
  chatMessages: [],
  chatLoading: false,
  async loadWorkspaces() {
    set({ workspaces: await readDirectory(host) });
  },
  async loadWorkspaceSurface(_tenant, _project, workspace) {
    const epoch = generation;
    const result = (await host.invoke('read-group-chat', {
      workspace_id: workspace,
      view: 'roster',
    })) as Pick<State, 'members' | 'agents'>;
    if (epoch === generation && workspace === selected)
      set({ currentWorkspace: { id: workspace }, members: result.members, agents: result.agents });
  },
  async loadChatMessages(_tenant, _project, workspace) {
    const epoch = generation;
    const request = ++readSequence;
    if (loadedWorkspace !== workspace) set({ chatLoading: true });
    try {
      const result = (await host.invoke('read-group-chat', {
        workspace_id: workspace,
        view: 'messages',
      })) as { principal_id: string; messages: WorkspaceMessage[] };
      if (epoch === generation && workspace === selected && request === readSequence) {
        loadedWorkspace = workspace;
        set({ user: { id: result.principal_id }, chatMessages: result.messages });
      }
    } finally {
      if (epoch === generation && request === readSequence) set({ chatLoading: false });
    }
  },
  async sendChatMessage(_tenant, _project, workspace, content, mentions = []) {
    const epoch = generation;
    const { message } = (await host.invoke('send-group-message', {
      workspace_id: workspace,
      content,
      mentions,
      request_id: crypto.randomUUID(),
    })) as { message: WorkspaceMessage };
    if (epoch === generation && workspace === selected) {
      ++readSequence;
      set((state) => ({
        chatLoading: false,
        chatMessages: [...state.chatMessages.filter((row) => row.id !== message.id), message],
      }));
    }
  },
}));
export const useAuthStore = useWorkspaceStore;
