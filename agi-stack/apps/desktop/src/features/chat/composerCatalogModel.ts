import type {
  AgentInputFileMetadata,
  AgentConversation,
  ConversationMessagesResponse,
  ManagedAgentDefinition,
  ManagedPlugin,
  ManagedSkill,
  ManagedSubAgent,
  PaginatedConversationsResponse,
  PromptTemplateCreateInput,
  PromptTemplateRecord,
  WorkspaceAgentBinding,
} from "../../types";

export type ComposerCatalogClient = {
  readExecutionSelection?: (
    conversation: AgentConversation,
  ) => Promise<AgentConversation>;
  updateExecutionSelection?: (
    conversation: AgentConversation,
    patch: Partial<NonNullable<AgentConversation["execution_selection"]>>,
  ) => Promise<AgentConversation>;
  listWorkspaceAgents: (
    signal?: AbortSignal,
  ) => Promise<WorkspaceAgentBinding[]>;
  listManagedAgents: (
    signal?: AbortSignal,
  ) => Promise<ManagedAgentDefinition[]>;
  listManagedSkills: (signal?: AbortSignal) => Promise<ManagedSkill[]>;
  listMarketplacePlugins: (signal?: AbortSignal) => Promise<ManagedPlugin[]>;
  listManagedSubAgents: (signal?: AbortSignal) => Promise<ManagedSubAgent[]>;
  listPromptTemplates: (
    tenantId: string,
    signal?: AbortSignal,
  ) => Promise<PromptTemplateRecord[]>;
  createPromptTemplate: (
    tenantId: string,
    input: PromptTemplateCreateInput,
    signal?: AbortSignal,
  ) => Promise<PromptTemplateRecord>;
  deletePromptTemplate: (
    templateId: string,
    signal?: AbortSignal,
    expectedRevision?: number,
  ) => Promise<void>;
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
    file: Pick<File, "name" | "type" | "size" | "arrayBuffer">,
    signal?: AbortSignal,
  ) => Promise<AgentInputFileMetadata>;
};

export type ComposerCatalog = {
  workspaceAgents: WorkspaceAgentBinding[];
  agents: ManagedAgentDefinition[];
  skills: ManagedSkill[];
  plugins: ManagedPlugin[];
  subagents: ManagedSubAgent[];
  errors?: Partial<
    Record<
      "workspaceAgents" | "agents" | "skills" | "plugins" | "subagents",
      string | null
    >
  >;
};

export function composerCatalogErrorMessage(error: unknown): string | null {
  if (typeof error === "string") return error;
  if (error && typeof error === "object") {
    const record = error as Record<string, unknown>;
    for (const key of [
      "message",
      "detail",
      "reasonCode",
      "reason_code",
      "code",
    ]) {
      if (typeof record[key] === "string") return record[key];
    }
  }
  return null;
}

export async function loadComposerCatalog(
  api: ComposerCatalogClient,
  signal?: AbortSignal,
): Promise<ComposerCatalog> {
  const errors: NonNullable<ComposerCatalog["errors"]> = {};
  const load = async <T>(
    key: keyof typeof errors,
    request: () => Promise<T[]>,
  ): Promise<T[]> => {
    try {
      return await request();
    } catch (error) {
      if (signal?.aborted) throw error;
      errors[key] = composerCatalogErrorMessage(error);
      return [];
    }
  };
  const [workspaceAgents, agents, skills, plugins, subagents] =
    await Promise.all([
      load("workspaceAgents", () => api.listWorkspaceAgents(signal)),
      load("agents", () => api.listManagedAgents(signal)),
      load("skills", () => api.listManagedSkills(signal)),
      load("plugins", () => api.listMarketplacePlugins(signal)),
      load("subagents", () => api.listManagedSubAgents(signal)),
    ]);
  return {
    workspaceAgents,
    agents,
    skills,
    plugins,
    subagents,
    ...(Object.keys(errors).length ? { errors } : {}),
  };
}

export function unboundComposerCatalogClient(
  api: ComposerCatalogClient,
): ComposerCatalogClient {
  const listManagedSubAgents = api.listManagedSubAgents.bind(api);
  const listPromptTemplates = api.listPromptTemplates.bind(api);
  const createPromptTemplate = api.createPromptTemplate.bind(api);
  const deletePromptTemplate = api.deletePromptTemplate.bind(api);
  const listConversations = api.listConversations?.bind(api);
  const getConversationMessages = api.getConversationMessages?.bind(api);
  const uploadSandboxFile = api.uploadSandboxFile?.bind(api);
  return {
    ...(api.readExecutionSelection
      ? { readExecutionSelection: api.readExecutionSelection.bind(api) }
      : {}),
    ...(api.updateExecutionSelection
      ? { updateExecutionSelection: api.updateExecutionSelection.bind(api) }
      : {}),
    listWorkspaceAgents: async () => [],
    listManagedAgents: (signal) => api.listManagedAgents(signal),
    listManagedSkills: (signal) => api.listManagedSkills(signal),
    listMarketplacePlugins: (signal) => api.listMarketplacePlugins(signal),
    listManagedSubAgents,
    listPromptTemplates,
    createPromptTemplate,
    deletePromptTemplate,
    ...(listConversations ? { listConversations } : {}),
    ...(getConversationMessages ? { getConversationMessages } : {}),
    ...(uploadSandboxFile ? { uploadSandboxFile } : {}),
  };
}
