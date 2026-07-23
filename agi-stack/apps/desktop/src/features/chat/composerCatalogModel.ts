import type {
  AgentInputFileMetadata,
  ConversationMessagesResponse,
  ManagedAgentDefinition,
  ManagedPlugin,
  ManagedSkill,
  ManagedSubAgent,
  PaginatedConversationsResponse,
  PromptTemplateRecord,
  WorkspaceAgentBinding,
} from '../../types';

export type ComposerCatalogClient = {
  listWorkspaceAgents: (signal?: AbortSignal) => Promise<WorkspaceAgentBinding[]>;
  listManagedAgents: (signal?: AbortSignal) => Promise<ManagedAgentDefinition[]>;
  listManagedSkills: (signal?: AbortSignal) => Promise<ManagedSkill[]>;
  listManagedPlugins: (signal?: AbortSignal) => Promise<ManagedPlugin[]>;
  listManagedSubAgents?: (signal?: AbortSignal) => Promise<ManagedSubAgent[]>;
  listPromptTemplates?: (
    tenantId: string,
    signal?: AbortSignal,
  ) => Promise<PromptTemplateRecord[]>;
  deletePromptTemplate?: (templateId: string, signal?: AbortSignal) => Promise<void>;
  listConversations?: (
    projectId?: string,
    workspaceIdOrOptions?:
      | string
      | null
      | {
          workspaceId?: string | null;
          unboundOnly?: boolean;
          signal?: AbortSignal;
        },
    legacySignal?: AbortSignal,
  ) => Promise<PaginatedConversationsResponse>;
  getConversationMessages?: (
    conversationId: string,
    projectId?: string,
    options?: {
      limit?: number;
      fromTimeUs?: number;
      fromCounter?: number;
      beforeTimeUs?: number;
      beforeCounter?: number;
      signal?: AbortSignal;
    },
  ) => Promise<ConversationMessagesResponse>;
  uploadSandboxFile?: (
    file: Pick<File, 'name' | 'type' | 'size' | 'arrayBuffer'>,
  ) => Promise<AgentInputFileMetadata>;
};

export type ComposerCatalog = {
  workspaceAgents: WorkspaceAgentBinding[];
  agents: ManagedAgentDefinition[];
  skills: ManagedSkill[];
  plugins: ManagedPlugin[];
  subagents: ManagedSubAgent[];
};

export async function loadComposerCatalog(
  api: ComposerCatalogClient,
  signal?: AbortSignal,
): Promise<ComposerCatalog> {
  const [workspaceAgents, agents, skills, plugins, subagents] = await Promise.all([
    api.listWorkspaceAgents(signal),
    api.listManagedAgents(signal),
    api.listManagedSkills(signal),
    api.listManagedPlugins(signal),
    api.listManagedSubAgents?.(signal) ?? Promise.resolve([]),
  ]);
  return { workspaceAgents, agents, skills, plugins, subagents };
}

export function unboundComposerCatalogClient(
  api: ComposerCatalogClient,
): ComposerCatalogClient {
  const listManagedSubAgents = api.listManagedSubAgents?.bind(api);
  const listPromptTemplates = api.listPromptTemplates?.bind(api);
  const deletePromptTemplate = api.deletePromptTemplate?.bind(api);
  const listConversations = api.listConversations?.bind(api);
  const getConversationMessages = api.getConversationMessages?.bind(api);
  const uploadSandboxFile = api.uploadSandboxFile?.bind(api);
  return {
    listWorkspaceAgents: async () => [],
    listManagedAgents: (signal) => api.listManagedAgents(signal),
    listManagedSkills: (signal) => api.listManagedSkills(signal),
    listManagedPlugins: (signal) => api.listManagedPlugins(signal),
    ...(listManagedSubAgents ? { listManagedSubAgents } : {}),
    ...(listPromptTemplates ? { listPromptTemplates } : {}),
    ...(deletePromptTemplate ? { deletePromptTemplate } : {}),
    ...(listConversations ? { listConversations } : {}),
    ...(getConversationMessages ? { getConversationMessages } : {}),
    ...(uploadSandboxFile ? { uploadSandboxFile } : {}),
  };
}
