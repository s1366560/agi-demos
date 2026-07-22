import type {
  AgentConversation,
  AgentCapabilityMode,
  ArtifactDeliveryOutcome,
  ArtifactDeliveryRequest,
  ArtifactReviewOutcome,
  ArtifactReviewRequest,
  AgentPlanMode,
  AgentPlanModeResponse,
  AgentPlanTaskListResponse,
  AgentInputFileMetadata,
  ApprovePlanAndStartRequest,
  ApprovePlanAndStartResponse,
  AutomationCapabilities,
  AutomationCreateInput,
  AutomationDeleteInput,
  AutomationJob,
  AutomationJobListResponse,
  AutomationRunListResponse,
  AutomationToggleInput,
  AutomationUpdateInput,
  ConversationMessagesResponse,
  ComposerContextItem,
  ChangeSnapshot,
  CreateTaskSessionRequest,
  CreateTaskSessionResponse,
  CreateRunInputRequest,
  CurrentUser,
  DeviceCodeView,
  DeviceTokenView,
  DesktopRuntimeConfig,
  ForkRecoveryOutcome,
  HitlResponseOutcome,
  HitlResponseSubmission,
  LoginOutcome,
  LlmProviderAuthMethod,
  LlmProviderCreateInput,
  LlmProviderModelCatalog,
  LlmProviderMutationInput,
  LlmProviderProbeInput,
  LlmProviderRoutingPolicy,
  LlmProviderRoutingPolicyMutationInput,
  LlmRoutingRole,
  LlmProviderTypeDescriptor,
  LlmProviderUsage,
  LlmProviderUsageStatistic,
  LlmProviderValidationOutcome,
  ManagedAgentDefinition,
  ManagedAgentDefinitionMutation,
  ManagedChannelConfig,
  ManagedChannelPluginCatalogItem,
  ManagedChannelPluginConfigSchema,
  ManagedChannelTestResult,
  ManagedLlmProvider,
  ManagedPlugin,
  ManagedPluginRuntime,
  ManagedSkill,
  ManagedSkillContent,
  ManagedSkillCreateMutation,
  ManagedSkillEvolutionDetail,
  ManagedSkillEvolutionJob,
  ManagedSkillEvolutionRun,
  ManagedSkillImportInput,
  ManagedSkillLifecycle,
  ManagedSkillMutation,
  ManagedSkillPackage,
  ManagedSkillVersionDetail,
  ManagedSkillVersionList,
  ManagedSkillZipImportInput,
  ManagedSubAgent,
  ManagedSubAgentMutation,
  ManagedSubAgentTemplateList,
  PluginActionResponse,
  PluginConfigRecord,
  PluginConfigSchema,
  PaginatedConversationsResponse,
  PlanSnapshot,
  ProjectMyWorkResponse,
  ProjectSummary,
  ProjectSandbox,
  PromoteRunInputResponse,
  ReviewRunRequest,
  RunControlOutcome,
  RunInputAck,
  DesktopRunInput,
  RuntimeDataset,
  TenantSummary,
  TerminalServiceResponse,
  WorkspaceMessage,
  WorkspaceContextResponse,
  WorkspaceContextSwitchOutcome,
  WorkspaceAgentPolicy,
  WorkspaceAgentPolicyMutationInput,
  WorkspaceToolGrant,
  WorkspaceAgentBinding,
  WorkspaceAuthorityCollection,
  WorkspaceMemberSummary,
  WorkspaceSummary,
  WorkspaceTask,
  UpdatePluginConfigRequest,
  CreateManagedChannelConfigRequest,
  UpdateManagedChannelConfigRequest,
} from '../types';

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  contentType?: string;
  signal?: AbortSignal;
  skipAuth?: boolean;
};

export type DesktopMCPAppSummary = {
  id: string;
  server_name?: string | null;
  tool_name?: string | null;
};

export type DesktopMCPAppToolCallResponse = {
  content: unknown[];
  is_error: boolean;
  error_message?: string | null;
  error_code?: string | null;
};

export type DesktopMCPAppResourceReadResponse = {
  contents: Array<{ uri: string; mimeType: string; text: string }>;
};

export type DesktopMCPAppResourceListResponse = {
  resources: Array<{
    uri: string;
    name?: string;
    mimeType?: string;
    description?: string;
  }>;
};

const WORKSPACE_ROSTER_PAGE_SIZE = 500;
const IDENTITY_CATALOG_PAGE_SIZE = 100;
const IDENTITY_CATALOG_MAX_PAGES = 1_000;
const HIERARCHY_CATALOG_PAGE_SIZE = 500;
const HIERARCHY_CATALOG_MAX_PAGES = 1_000;

export class DesktopApiError extends Error {
  readonly status: number;
  readonly payload: unknown;

  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.name = 'DesktopApiError';
    this.status = status;
    this.payload = payload;
  }
}

export type DeviceTokenErrorClassification =
  | { code: 'authorization_pending'; interval: number }
  | { code: 'expired_token' };

export function classifyDeviceTokenError(
  error: unknown,
): DeviceTokenErrorClassification | null {
  if (!(error instanceof DesktopApiError) || !isRecord(error.payload)) return null;
  const detail = error.payload.detail;
  if (
    error.status === 428 &&
    isRecord(detail) &&
    detail.error === 'authorization_pending' &&
    isUnsignedSafeInteger(detail.interval)
  ) {
    return { code: 'authorization_pending', interval: detail.interval };
  }
  if (
    error.status === 410 &&
    (detail === 'expired_token' || (isRecord(detail) && detail.error === 'expired_token'))
  ) {
    return { code: 'expired_token' };
  }
  return null;
}

export function isWorkspaceContextUnavailableError(error: unknown): boolean {
  if (!(error instanceof DesktopApiError) || error.status !== 404) return false;
  if (!isRecord(error.payload)) return false;
  const detail = error.payload.detail;
  return isRecord(detail) && detail.code === 'workspace_context_unavailable';
}

export function isTaskSessionIdempotencyConflictError(error: unknown): boolean {
  return (
    error instanceof DesktopApiError &&
    error.status === 409 &&
    isRecord(error.payload) &&
    error.payload.code === 'TASK_SESSION_IDEMPOTENCY_CONFLICT'
  );
}

export class DesktopApiClient {
  private readonly config: DesktopRuntimeConfig;

  constructor(config: DesktopRuntimeConfig) {
    this.config = config;
  }

  async login(username: string, password: string): Promise<LoginOutcome> {
    const body = new URLSearchParams();
    body.set('username', username);
    body.set('password', password);
    return this.request<LoginOutcome>('/api/v1/auth/token', {
      method: 'POST',
      body,
      contentType: 'application/x-www-form-urlencoded;charset=UTF-8',
      skipAuth: true,
    });
  }

  async createDeviceCode(signal?: AbortSignal): Promise<DeviceCodeView> {
    const payload = await this.request<unknown>('/api/v1/auth/device/code', {
      method: 'POST',
      body: {},
      skipAuth: true,
      signal,
    });
    return requireDeviceCodeView(payload);
  }

  async pollDeviceToken(deviceCode: string, signal?: AbortSignal): Promise<DeviceTokenView> {
    const payload = await this.request<unknown>('/api/v1/auth/device/token', {
      method: 'POST',
      body: { device_code: requireValue(deviceCode, 'device code') },
      skipAuth: true,
      signal,
    });
    return requireDeviceTokenView(payload);
  }

  async cancelDeviceCode(deviceCode: string, signal?: AbortSignal): Promise<void> {
    await this.request<unknown>('/api/v1/auth/device/cancel', {
      method: 'POST',
      body: { device_code: requireValue(deviceCode, 'device code') },
      skipAuth: true,
      signal,
    });
  }

  async createLocalSession(trustedDevice = false): Promise<LoginOutcome> {
    return this.request<LoginOutcome>('/api/v1/auth/local-session', {
      method: 'POST',
      body: { trusted_device: trustedDevice },
      skipAuth: true,
    });
  }

  async resumeLocalSession(sessionId: string): Promise<LoginOutcome | null> {
    try {
      return await this.request<LoginOutcome>('/api/v1/auth/local-session/resume', {
        method: 'POST',
        body: { session_id: sessionId },
        skipAuth: true,
      });
    } catch (error) {
      if (error instanceof DesktopApiError && error.status === 401) return null;
      throw error;
    }
  }

  async signOut(): Promise<{ success: boolean }> {
    return this.request<{ success: boolean }>('/api/v1/auth/signout', { method: 'POST' });
  }

  async currentUser(signal?: AbortSignal): Promise<CurrentUser> {
    return this.request<CurrentUser>('/api/v1/auth/me', { signal });
  }

  async listTenants(signal?: AbortSignal): Promise<TenantSummary[]> {
    return loadPagedIdentityCatalog(
      'tenant catalog',
      'tenants',
      (page, pageSize) => {
        const params = new URLSearchParams({
          page: String(page),
          page_size: String(pageSize),
        });
        return this.request<unknown>(`/api/v1/tenants?${params.toString()}`, { signal });
      },
      normalizeTenantSummary,
    );
  }

  async listProjects(tenantId?: string, signal?: AbortSignal): Promise<ProjectSummary[]> {
    const requiredTenantId = tenantId?.trim() ?? '';
    const parseProject = (value: unknown) => normalizeProjectSummary(value, requiredTenantId);
    return loadPagedIdentityCatalog(
      'project catalog',
      'projects',
      (page, pageSize) => {
        const params = new URLSearchParams({
          page: String(page),
          page_size: String(pageSize),
        });
        if (requiredTenantId) params.set('tenant_id', requiredTenantId);
        return this.request<unknown>(`/api/v1/projects?${params.toString()}`, { signal });
      },
      parseProject,
    );
  }

  async getWorkspaceContext(signal?: AbortSignal): Promise<WorkspaceContextResponse> {
    return this.request<WorkspaceContextResponse>('/api/v1/workspace-context', { signal });
  }

  async getConversationSession(
    conversationId: string,
    scope: { tenantId: string; projectId: string; workspaceId?: string | null },
    signal?: AbortSignal,
  ): Promise<unknown> {
    const resolvedConversationId = requireValue(conversationId, 'conversation id');
    const params = new URLSearchParams({
      tenant_id: requireValue(scope.tenantId, 'tenant id'),
      project_id: requireValue(scope.projectId, 'project id'),
    });
    if (scope.workspaceId) params.set('workspace_id', scope.workspaceId);
    return this.request<unknown>(
      `/api/v1/agent/conversations/${encodeURIComponent(resolvedConversationId)}/session?${params.toString()}`,
      { signal },
    );
  }

  async switchWorkspaceContext(
    tenantId: string,
    projectId: string,
    expectedRevision: number,
    idempotencyKey: string,
  ): Promise<WorkspaceContextSwitchOutcome> {
    return this.request<WorkspaceContextSwitchOutcome>('/api/v1/workspace-context/switch', {
      method: 'POST',
      body: {
        tenant_id: tenantId,
        project_id: projectId,
        expected_revision: expectedRevision,
        idempotency_key: idempotencyKey,
      },
    });
  }

  async listMyWork(projectId = this.config.projectId, signal?: AbortSignal) {
    const resolvedProjectId = requireValue(projectId, 'project id');
    return this.request<ProjectMyWorkResponse>(
      `/api/v1/projects/${encodeURIComponent(resolvedProjectId)}/my-work`,
      { signal },
    );
  }

  async listAutomations(
    projectId = this.config.projectId,
    signal?: AbortSignal,
  ): Promise<AutomationJobListResponse> {
    const resolvedProjectId = requireValue(projectId, 'project id');
    const params = new URLSearchParams({
      include_disabled: 'true',
      limit: '100',
      offset: '0',
    });
    return this.request<AutomationJobListResponse>(
      `/api/v1/projects/${encodeURIComponent(resolvedProjectId)}/cron-jobs?${params.toString()}`,
      { signal },
    );
  }

  async getAutomationCapabilities(
    projectId = this.config.projectId,
    signal?: AbortSignal,
  ): Promise<AutomationCapabilities> {
    const resolvedProjectId = requireValue(projectId, 'project id');
    return this.request<AutomationCapabilities>(
      `/api/v1/projects/${encodeURIComponent(resolvedProjectId)}/cron-jobs/capabilities`,
      { signal },
    );
  }

  async createAutomation(
    input: AutomationCreateInput,
    projectId = this.config.projectId,
  ): Promise<AutomationJob> {
    const resolvedProjectId = requireValue(projectId, 'project id');
    return this.request<AutomationJob>(
      `/api/v1/projects/${encodeURIComponent(resolvedProjectId)}/cron-jobs`,
      { method: 'POST', body: input },
    );
  }

  async getAutomation(
    automationId: string,
    projectId = this.config.projectId,
    signal?: AbortSignal,
  ): Promise<AutomationJob> {
    const resolvedProjectId = requireValue(projectId, 'project id');
    return this.request<AutomationJob>(
      `/api/v1/projects/${encodeURIComponent(resolvedProjectId)}/cron-jobs/${encodeURIComponent(
        automationId,
      )}`,
      { signal },
    );
  }

  async updateAutomation(
    automationId: string,
    input: AutomationUpdateInput,
    projectId = this.config.projectId,
  ): Promise<AutomationJob> {
    const resolvedProjectId = requireValue(projectId, 'project id');
    return this.request<AutomationJob>(
      `/api/v1/projects/${encodeURIComponent(resolvedProjectId)}/cron-jobs/${encodeURIComponent(
        automationId,
      )}`,
      { method: 'PATCH', body: input },
    );
  }

  async toggleAutomation(
    automationId: string,
    input: AutomationToggleInput,
    projectId = this.config.projectId,
  ): Promise<AutomationJob> {
    const resolvedProjectId = requireValue(projectId, 'project id');
    return this.request<AutomationJob>(
      `/api/v1/projects/${encodeURIComponent(resolvedProjectId)}/cron-jobs/${encodeURIComponent(
        automationId,
      )}/toggle`,
      { method: 'POST', body: input },
    );
  }

  async deleteAutomation(
    automationId: string,
    input: AutomationDeleteInput,
    projectId = this.config.projectId,
  ): Promise<void> {
    const resolvedProjectId = requireValue(projectId, 'project id');
    await this.request<unknown>(
      `/api/v1/projects/${encodeURIComponent(resolvedProjectId)}/cron-jobs/${encodeURIComponent(
        automationId,
      )}`,
      { method: 'DELETE', body: input },
    );
  }

  async listAutomationRuns(
    automationId: string,
    projectId = this.config.projectId,
    signal?: AbortSignal,
  ): Promise<AutomationRunListResponse> {
    const resolvedProjectId = requireValue(projectId, 'project id');
    const params = new URLSearchParams({ limit: '50', offset: '0' });
    return this.request<AutomationRunListResponse>(
      `/api/v1/projects/${encodeURIComponent(resolvedProjectId)}/cron-jobs/${encodeURIComponent(
        automationId,
      )}/runs?${params.toString()}`,
      { signal },
    );
  }

  async listWorkspaces(signal?: AbortSignal): Promise<WorkspaceSummary[]> {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    const projectId = requireValue(this.config.projectId, 'project id');
    return this.listWorkspacesForProject(projectId, tenantId, signal);
  }

  async listWorkspacesForProject(
    projectId: string,
    tenantId = this.config.tenantId,
    signal?: AbortSignal,
  ): Promise<WorkspaceSummary[]> {
    const requiredTenantId = requireValue(tenantId, 'tenant id');
    const requiredProjectId = requireValue(projectId, 'project id');
    return loadScopedWorkspaceCatalog(
      requiredTenantId,
      requiredProjectId,
      (offset) => {
        const params = new URLSearchParams({
          limit: String(HIERARCHY_CATALOG_PAGE_SIZE),
          offset: String(offset),
        });
        return this.request<unknown>(
          `/api/v1/tenants/${encodeURIComponent(requiredTenantId)}/projects/${encodeURIComponent(
            requiredProjectId,
          )}/workspaces?${params.toString()}`,
          { signal },
        );
      },
    );
  }

  async listWorkspaceMembers(signal?: AbortSignal): Promise<WorkspaceMemberSummary[]> {
    const workspaceId = requireValue(this.config.workspaceId, 'workspace id');
    const members: WorkspaceMemberSummary[] = [];
    for (let offset = 0; ; offset += WORKSPACE_ROSTER_PAGE_SIZE) {
      const params = new URLSearchParams({
        limit: String(WORKSPACE_ROSTER_PAGE_SIZE),
        offset: String(offset),
      });
      const payload = await this.request<unknown>(
        this.workspacePath(`/members?${params.toString()}`),
        { signal },
      );
      const page = requireWorkspaceRosterPage(
        payload,
        'workspace members',
        workspaceId,
        isWorkspaceMemberSummary,
      );
      members.push(...page);
      if (page.length < WORKSPACE_ROSTER_PAGE_SIZE) return members;
    }
  }

  async listWorkspaceAgents(signal?: AbortSignal): Promise<WorkspaceAgentBinding[]> {
    const workspaceId = requireValue(this.config.workspaceId, 'workspace id');
    const agents: WorkspaceAgentBinding[] = [];
    for (let offset = 0; ; offset += WORKSPACE_ROSTER_PAGE_SIZE) {
      const params = new URLSearchParams({
        active_only: 'true',
        limit: String(WORKSPACE_ROSTER_PAGE_SIZE),
        offset: String(offset),
      });
      const payload = await this.request<unknown>(
        this.workspacePath(`/agents?${params.toString()}`),
        { signal },
      );
      const page = requireWorkspaceRosterPage(
        payload,
        'workspace agents',
        workspaceId,
        isWorkspaceAgentBinding,
      );
      agents.push(...page);
      if (page.length < WORKSPACE_ROSTER_PAGE_SIZE) return agents;
    }
  }

  async createWorkspace(name: string, description?: string): Promise<WorkspaceSummary> {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    const projectId = requireValue(this.config.projectId, 'project id');
    return this.createWorkspaceForProject(projectId, name, description, tenantId);
  }

  async createTaskSession(input: CreateTaskSessionRequest): Promise<CreateTaskSessionResponse> {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    const projectId = requireValue(this.config.projectId, 'project id');
    const payload = await this.request<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/projects/${encodeURIComponent(
        projectId,
      )}/task-sessions`,
      {
        method: 'POST',
        body: input,
      },
    );
    return requireCreateTaskSessionResponse(payload, tenantId, projectId, input);
  }

  async getWorkspaceAgentPolicy(
    projectId: string,
    workspaceId: string,
    signal?: AbortSignal,
  ): Promise<WorkspaceAgentPolicy> {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    const payload = await this.request<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/projects/${encodeURIComponent(
        requireValue(projectId, 'project id'),
      )}/workspaces/${encodeURIComponent(
        requireValue(workspaceId, 'workspace id'),
      )}/agent-policy`,
      { signal },
    );
    return normalizeWorkspaceAgentPolicy(payload);
  }

  async updateWorkspaceAgentPolicy(
    input: WorkspaceAgentPolicyMutationInput,
  ): Promise<WorkspaceAgentPolicy> {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    const payload = await this.request<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/projects/${encodeURIComponent(
        requireValue(input.projectId, 'project id'),
      )}/workspaces/${encodeURIComponent(
        requireValue(input.workspaceId, 'workspace id'),
      )}/agent-policy`,
      {
        method: 'PATCH',
        body: {
          expected_revision: input.expected_revision,
          capability_mode: input.capabilityMode,
          route: input.route,
          reasoning_effort: input.reasoning_effort,
          permission_mode: input.permission_mode,
        },
      },
    );
    return normalizeWorkspaceAgentPolicy(payload);
  }

  async listWorkspaceToolGrants(
    projectId: string,
    workspaceId: string,
    signal?: AbortSignal,
  ): Promise<WorkspaceToolGrant[]> {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    const payload = await this.request<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/projects/${encodeURIComponent(
        requireValue(projectId, 'project id'),
      )}/workspaces/${encodeURIComponent(
        requireValue(workspaceId, 'workspace id'),
      )}/tool-grants`,
      { signal },
    );
    return readArray<unknown>(payload, ['items']).map(normalizeWorkspaceToolGrant);
  }

  async revokeWorkspaceToolGrant(
    projectId: string,
    workspaceId: string,
    grantId: string,
  ): Promise<WorkspaceToolGrant> {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    const payload = await this.request<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/projects/${encodeURIComponent(
        requireValue(projectId, 'project id'),
      )}/workspaces/${encodeURIComponent(
        requireValue(workspaceId, 'workspace id'),
      )}/tool-grants/${encodeURIComponent(requireValue(grantId, 'grant id'))}`,
      { method: 'DELETE' },
    );
    return normalizeWorkspaceToolGrant(payload);
  }

  async createWorkspaceForProject(
    projectId: string,
    name: string,
    description?: string,
    tenantId = this.config.tenantId,
    options: {
      useCase?: 'general' | 'programming' | 'conversation' | 'research' | 'operations';
      collaborationMode?:
        | 'single_agent'
        | 'multi_agent_shared'
        | 'multi_agent_isolated'
        | 'autonomous';
      sandboxCodeRoot?: string;
    } = {},
  ): Promise<WorkspaceSummary> {
    const requiredTenantId = requireValue(tenantId, 'tenant id');
    const requiredProjectId = requireValue(projectId, 'project id');
    return this.request<WorkspaceSummary>(
      `/api/v1/tenants/${encodeURIComponent(requiredTenantId)}/projects/${encodeURIComponent(
        requiredProjectId,
      )}/workspaces`,
      {
        method: 'POST',
        body: {
          name,
          description,
          metadata: {
            source: 'desktop',
          },
          use_case: options.useCase ?? 'conversation',
          collaboration_mode: options.collaborationMode ?? 'multi_agent_shared',
          sandbox_code_root: options.sandboxCodeRoot || undefined,
        },
      },
    );
  }

  async listMessages(signal?: AbortSignal): Promise<WorkspaceMessage[]> {
    const path = this.workspacePath('/messages');
    const payload = await this.request<unknown>(path, { signal });
    return readArray<WorkspaceMessage>(payload, ['messages', 'items', 'data']);
  }

  async sendMessage(
    content: string,
    parentMessageId?: string,
    contextItems: ComposerContextItem[] = [],
    mentions: string[] = [],
  ): Promise<WorkspaceMessage> {
    const path = this.workspacePath('/messages');
    return this.request<WorkspaceMessage>(path, {
      method: 'POST',
      body: {
        content,
        sender_type: 'human',
        parent_message_id: parentMessageId || undefined,
        mentions,
        context_items: contextItems,
      },
    });
  }

  async createAgentConversation(
    title: string,
    projectId = this.config.projectId,
    capabilityMode?: AgentCapabilityMode,
  ): Promise<AgentConversation> {
    const requiredProjectId = requireValue(projectId, 'project id');
    return this.request<AgentConversation>('/api/v1/agent/conversations', {
      method: 'POST',
      body: {
        project_id: requiredProjectId,
        title,
        agent_config: {
          selected_agent_id: 'builtin:all-access',
          ...(capabilityMode ? { capability_mode: capabilityMode } : {}),
        },
      },
    });
  }

  async updateAgentConversationMode(
    conversationId: string,
    payload: {
      conversation_mode?: string | null;
      workspace_id?: string | null;
      linked_workspace_task_id?: string | null;
      capability_mode?: AgentCapabilityMode | null;
    },
    projectId = this.config.projectId,
  ): Promise<AgentConversation> {
    const requiredProjectId = requireValue(projectId, 'project id');
    return this.request<AgentConversation>(
      `/api/v1/agent/conversations/${encodeURIComponent(
        conversationId,
      )}/mode?project_id=${encodeURIComponent(requiredProjectId)}`,
      {
        method: 'PATCH',
        body: payload,
      },
    );
  }

  async listConversations(
    projectId = this.config.projectId,
    workspaceId?: string | null,
    signal?: AbortSignal,
  ): Promise<PaginatedConversationsResponse> {
    const requiredTenantId = requireValue(this.config.tenantId, 'tenant id');
    const requiredProjectId = requireValue(projectId, 'project id');
    const requiredWorkspaceId = workspaceId?.trim() || null;
    const items: AgentConversation[] = [];
    const seenIds = new Set<string>();
    let offset = 0;
    let expectedTotal: number | null = null;

    for (let pageNumber = 0; pageNumber < HIERARCHY_CATALOG_MAX_PAGES; pageNumber += 1) {
      const params = new URLSearchParams({
        project_id: requiredProjectId,
        status: 'active',
        limit: String(HIERARCHY_CATALOG_PAGE_SIZE),
        offset: String(offset),
      });
      if (requiredWorkspaceId) params.set('workspace_id', requiredWorkspaceId);
      const payload = await this.request<unknown>(
        `/api/v1/agent/conversations?${params.toString()}`,
        { signal },
      );
      const page = requireConversationCatalogPage(
        payload,
        offset,
        requiredTenantId,
        requiredProjectId,
        requiredWorkspaceId,
      );
      if (expectedTotal === null) {
        expectedTotal = page.total;
        if (
          Math.ceil(expectedTotal / HIERARCHY_CATALOG_PAGE_SIZE) >
          HIERARCHY_CATALOG_MAX_PAGES
        ) {
          throw invalidHierarchyCatalogResponse('conversation catalog', payload);
        }
      } else if (page.total !== expectedTotal) {
        throw invalidHierarchyCatalogResponse('conversation catalog', payload);
      }
      for (const item of page.items) {
        if (seenIds.has(item.id)) {
          throw invalidHierarchyCatalogResponse('conversation catalog', payload);
        }
        seenIds.add(item.id);
        items.push(item);
      }
      if (!page.hasMore) {
        if (items.length !== expectedTotal) {
          throw invalidHierarchyCatalogResponse('conversation catalog', payload);
        }
        return {
          items,
          total: expectedTotal,
          has_more: false,
          offset: 0,
          limit: HIERARCHY_CATALOG_PAGE_SIZE,
          next_offset: null,
        };
      }
      offset = page.nextOffset;
    }
    throw invalidHierarchyCatalogResponse('conversation catalog', {
      detail: 'hierarchy_catalog_page_limit_exceeded',
    });
  }

  async getConversationMessages(
    conversationId: string,
    projectId = this.config.projectId,
    options: {
      limit?: number;
      fromTimeUs?: number;
      fromCounter?: number;
      beforeTimeUs?: number;
      beforeCounter?: number;
      signal?: AbortSignal;
    } = {},
  ): Promise<ConversationMessagesResponse> {
    const requiredProjectId = requireValue(projectId, 'project id');
    const params = new URLSearchParams({
      project_id: requiredProjectId,
      limit: String(options.limit ?? 50),
    });
    if (typeof options.fromTimeUs === 'number') params.set('from_time_us', String(options.fromTimeUs));
    if (typeof options.fromCounter === 'number') params.set('from_counter', String(options.fromCounter));
    if (typeof options.beforeTimeUs === 'number') params.set('before_time_us', String(options.beforeTimeUs));
    if (typeof options.beforeCounter === 'number') params.set('before_counter', String(options.beforeCounter));
    return this.request<ConversationMessagesResponse>(
      `/api/v1/agent/conversations/${encodeURIComponent(conversationId)}/messages?${params.toString()}`,
      { signal: options.signal },
    );
  }

  async runAgentMessage(
    conversationId: string,
    message: string,
    messageId?: string,
    projectId = this.config.projectId,
    workloadRole?: LlmRoutingRole,
  ): Promise<{ queued: boolean }> {
    const requiredProjectId = requireValue(projectId, 'project id');
    return this.request<{ queued: boolean }>(
      `/api/v1/agent/conversations/${encodeURIComponent(conversationId)}/messages`,
      {
        method: 'POST',
        body: {
          project_id: requiredProjectId,
          message,
          message_id: messageId,
          ...(workloadRole ? { workload_role: workloadRole } : {}),
        },
      },
    );
  }

  async supportsAgentPlanWorkflow(signal?: AbortSignal): Promise<boolean> {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    const projectId = requireValue(this.config.projectId, 'project id');
    try {
      const payload = await this.request<unknown>(
        `/api/v1/tenants/${encodeURIComponent(tenantId)}/projects/${encodeURIComponent(
          projectId,
        )}/task-sessions/capabilities`,
        {
        signal,
        },
      );
      return isAtomicTaskSessionCapability(payload);
    } catch (error) {
      if (!(error instanceof DesktopApiError)) throw error;
      if (error.status === 404 || error.status === 405 || error.status === 501) return false;
      throw error;
    }
  }

  async switchPlanMode(
    conversationId: string,
    mode: AgentPlanMode,
  ): Promise<AgentPlanModeResponse> {
    return this.request<AgentPlanModeResponse>('/api/v1/agent/plan/mode', {
      method: 'POST',
      body: {
        conversation_id: conversationId,
        mode,
      },
    });
  }

  async approvePlanAndStart(
    input: ApprovePlanAndStartRequest,
  ): Promise<ApprovePlanAndStartResponse> {
    return this.request<ApprovePlanAndStartResponse>(
      '/api/v1/agent/plans/approve-and-start',
      {
        method: 'POST',
        body: {
          conversation_id: input.conversationId,
          project_id: input.projectId,
          plan_version_id: input.planVersionId,
          expected_plan_version: input.expectedPlanVersion,
          permission_profile: input.permissionProfile,
          message: input.message,
          message_id: input.messageId,
          idempotency_key: input.idempotencyKey,
          environment: { kind: input.environmentKind },
        },
      },
    );
  }

  async getPlanMode(conversationId: string): Promise<AgentPlanModeResponse> {
    return this.request<AgentPlanModeResponse>(
      `/api/v1/agent/plan/mode/${encodeURIComponent(conversationId)}`,
    );
  }

  async listAgentPlanTasks(
    conversationId: string,
    signal?: AbortSignal,
  ): Promise<AgentPlanTaskListResponse> {
    return this.request<AgentPlanTaskListResponse>(
      `/api/v1/agent/plan/tasks/${encodeURIComponent(conversationId)}`,
      { signal },
    );
  }

  async respondToHitl(submission: HitlResponseSubmission): Promise<HitlResponseOutcome> {
    return this.request<HitlResponseOutcome>('/api/v1/agent/hitl/respond', {
      method: 'POST',
      body: {
        request_id: submission.requestId,
        hitl_type: submission.hitlType,
        response_data: submission.responseData,
        ...(typeof submission.expectedRevision === 'number'
          ? { expected_revision: submission.expectedRevision }
          : {}),
        ...(submission.idempotencyKey
          ? { idempotency_key: submission.idempotencyKey }
          : {}),
      },
    });
  }

  async pauseRun(runId: string, expectedRevision: number): Promise<RunControlOutcome> {
    return this.runControl(runId, 'pause', expectedRevision);
  }

  async getRunChanges(runId: string, expectedRevision: number): Promise<ChangeSnapshot> {
    const params = new URLSearchParams({ expected_revision: String(expectedRevision) });
    return this.request<ChangeSnapshot>(
      `/api/v1/agent/runs/${encodeURIComponent(runId)}/changes?${params.toString()}`,
    );
  }

  async createRunInput(runId: string, input: CreateRunInputRequest): Promise<RunInputAck> {
    return this.request<RunInputAck>(
      `/api/v1/agent/runs/${encodeURIComponent(runId)}/inputs`,
      {
        method: 'POST',
        body: {
          expected_run_revision: input.expectedRunRevision,
          message: input.message,
          message_id: input.messageId,
          idempotency_key: input.idempotencyKey,
          delivery: input.delivery,
          references: input.references,
          context_items: input.contextItems,
        },
      },
    );
  }

  async listRunInputs(runId: string): Promise<{
    run_id: string;
    run_revision: number;
    inputs: DesktopRunInput[];
    total_count: number;
  }> {
    return this.request(`/api/v1/agent/runs/${encodeURIComponent(runId)}/inputs`);
  }

  async promoteRunInput(
    inputId: string,
    expectedSourceRunRevision: number,
    idempotencyKey: string,
  ): Promise<PromoteRunInputResponse> {
    return this.request<PromoteRunInputResponse>(
      `/api/v1/agent/run-inputs/${encodeURIComponent(inputId)}/promote-to-plan`,
      {
        method: 'POST',
        body: {
          expected_source_run_revision: expectedSourceRunRevision,
          idempotency_key: idempotencyKey,
        },
      },
    );
  }

  async resumeRun(runId: string, expectedRevision: number): Promise<RunControlOutcome> {
    return this.runControl(runId, 'resume', expectedRevision);
  }

  async forkRecoveryRun(
    runId: string,
    expectedRevision: number,
    idempotencyKey: string,
  ): Promise<ForkRecoveryOutcome> {
    return this.request<ForkRecoveryOutcome>(
      `/api/v1/agent/runs/${encodeURIComponent(runId)}/fork`,
      {
        method: 'POST',
        body: {
          expected_revision: expectedRevision,
          idempotency_key: idempotencyKey,
        },
      },
    );
  }

  async cancelRun(runId: string, expectedRevision: number): Promise<RunControlOutcome> {
    return this.runControl(runId, 'cancel', expectedRevision);
  }

  async reviewRun(runId: string, input: ReviewRunRequest): Promise<RunControlOutcome> {
    return this.request<RunControlOutcome>(
      `/api/v1/agent/runs/${encodeURIComponent(runId)}/review`,
      {
        method: 'POST',
        body: {
          action: input.action,
          expected_revision: input.expectedRevision,
          ...(input.feedback ? { feedback: input.feedback } : {}),
        },
      },
    );
  }

  async reviewArtifactVersion(
    artifactVersionId: string,
    input: ArtifactReviewRequest,
  ): Promise<ArtifactReviewOutcome> {
    return this.request<ArtifactReviewOutcome>(
      `/api/v1/agent/artifact-versions/${encodeURIComponent(artifactVersionId)}/review`,
      {
        method: 'POST',
        body: {
          action: input.action,
          expected_revision: input.expectedRevision,
          ...(typeof input.runExpectedRevision === 'number'
            ? { run_expected_revision: input.runExpectedRevision }
            : {}),
          ...(input.feedback ? { feedback: input.feedback } : {}),
        },
      },
    );
  }

  async deliverArtifactVersion(
    artifactVersionId: string,
    input: ArtifactDeliveryRequest,
  ): Promise<ArtifactDeliveryOutcome> {
    return this.request<ArtifactDeliveryOutcome>(
      `/api/v1/agent/artifact-versions/${encodeURIComponent(artifactVersionId)}/deliver`,
      {
        method: 'POST',
        body: {
          expected_revision: input.expectedRevision,
          idempotency_key: input.idempotencyKey,
          ...(input.destination ? { destination: input.destination } : {}),
        },
      },
    );
  }

  private async runControl(
    runId: string,
    action: 'pause' | 'resume' | 'cancel',
    expectedRevision: number,
  ): Promise<RunControlOutcome> {
    return this.request<RunControlOutcome>(
      `/api/v1/agent/runs/${encodeURIComponent(runId)}/${action}`,
      {
        method: 'POST',
        body: { expected_revision: expectedRevision },
      },
    );
  }

  async listLlmProviders(signal?: AbortSignal): Promise<ManagedLlmProvider[]> {
    const payload = await this.request<unknown>('/api/v1/llm-providers/?include_inactive=true', {
      signal,
    });
    return readArray<unknown>(payload, ['providers', 'items', 'data']).map(
      normalizeManagedLlmProvider,
    );
  }

  async getLlmProviderRoutingPolicy(
    projectId: string,
    workspaceId: string,
    signal?: AbortSignal,
  ): Promise<LlmProviderRoutingPolicy> {
    const params = new URLSearchParams({
      project_id: requireValue(projectId, 'project id'),
      workspace_id: requireValue(workspaceId, 'workspace id'),
    });
    const payload = await this.request<unknown>(
      `/api/v1/llm-providers/routing-policy?${params.toString()}`,
      { signal },
    );
    return normalizeLlmProviderRoutingPolicy(payload);
  }

  async updateLlmProviderRoutingPolicy(
    input: LlmProviderRoutingPolicyMutationInput,
  ): Promise<LlmProviderRoutingPolicy> {
    const payload = await this.request<unknown>('/api/v1/llm-providers/routing-policy', {
      method: 'PUT',
      body: {
        project_id: requireValue(input.projectId, 'project id'),
        workspace_id: requireValue(input.workspaceId, 'workspace id'),
        roles: input.roles,
        fallbacks: input.fallbacks,
        expected_revision: input.expectedRevision,
      },
    });
    return normalizeLlmProviderRoutingPolicy(payload);
  }

  async createLlmProvider(input: LlmProviderCreateInput): Promise<ManagedLlmProvider> {
    const payload = await this.request<unknown>('/api/v1/llm-providers/', {
      method: 'POST',
      body: {
        name: input.name,
        provider_type: input.providerType,
        base_url: input.baseUrl,
        llm_model: input.primaryModel,
        allowed_models: input.allowedModels,
        is_active: input.active,
        ...providerCredentialRequestBody(input),
      },
    });
    return normalizeManagedLlmProvider(payload);
  }

  async listLlmProviderTypes(signal?: AbortSignal): Promise<LlmProviderTypeDescriptor[]> {
    const payload = await this.request<unknown>('/api/v1/llm-providers/types', {
      signal,
    });
    return normalizeProviderTypeDescriptors(
      payload,
      this.config.mode === 'local' ? 'local_runtime' : 'cloud_api',
    );
  }

  async listLlmProviderModels(
    providerType: string,
    signal?: AbortSignal,
  ): Promise<LlmProviderModelCatalog> {
    const normalizedProviderType = requireValue(providerType, 'provider type');
    const payload = await this.request<unknown>(
      `/api/v1/llm-providers/models/${encodeURIComponent(normalizedProviderType)}`,
      { signal },
    );
    return normalizeProviderCatalog(payload, normalizedProviderType);
  }

  async discoverLlmProviderModels(
    providerId: string,
    expectedRevision: number,
    signal?: AbortSignal,
  ): Promise<LlmProviderModelCatalog> {
    const normalizedProviderId = requireValue(providerId, 'provider id');
    const payload = await this.request<unknown>(
      `/api/v1/llm-providers/${encodeURIComponent(normalizedProviderId)}/models/discover`,
      {
        method: 'POST',
        body: { expected_revision: expectedRevision },
        signal,
      },
    );
    return normalizeProviderCatalog(payload, '', normalizedProviderId);
  }

  async getLlmProviderUsage(providerId: string, signal?: AbortSignal): Promise<LlmProviderUsage> {
    const normalizedProviderId = requireValue(providerId, 'provider id');
    const payload = await this.request<unknown>(
      `/api/v1/llm-providers/${encodeURIComponent(normalizedProviderId)}/usage`,
      { signal },
    );
    return normalizeProviderUsage(payload, normalizedProviderId);
  }

  async testLlmProviderDraft(input: LlmProviderProbeInput): Promise<LlmProviderValidationOutcome> {
    const payload = await this.request<unknown>('/api/v1/llm-providers/test-connection', {
      method: 'POST',
      body: {
        name: input.name,
        provider_type: input.providerType,
        base_url: input.baseUrl,
        is_active: input.active,
        ...providerCredentialRequestBody(input),
      },
    });
    return normalizeProviderValidationOutcome(payload, input.providerType);
  }

  async updateLlmProvider(
    providerId: string,
    input: LlmProviderMutationInput,
  ): Promise<ManagedLlmProvider> {
    const payload = await this.request<unknown>(
      `/api/v1/llm-providers/${encodeURIComponent(providerId)}`,
      {
        method: 'PUT',
        body: {
          name: input.name,
          provider_type: input.providerType,
          base_url: input.baseUrl,
          llm_model: input.primaryModel,
          allowed_models: input.allowedModels,
          is_active: input.active,
          expected_revision: input.expectedRevision,
          ...providerCredentialRequestBody(input),
        },
      },
    );
    return normalizeManagedLlmProvider(payload);
  }

  async checkLlmProvider(
    providerId: string,
    expectedRevision: number,
  ): Promise<LlmProviderValidationOutcome> {
    const encodedProviderId = encodeURIComponent(providerId);
    const payload = await this.request<unknown>(
      `/api/v1/llm-providers/${encodedProviderId}/health-check`,
      {
        method: 'POST',
        body:
          this.config.mode === 'local'
            ? { expected_revision: expectedRevision }
            : {},
      },
    );
    return normalizeProviderValidationOutcome(payload);
  }

  async listManagedSkills(signal?: AbortSignal): Promise<ManagedSkill[]> {
    const params = new URLSearchParams({ limit: '100' });
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    if (this.config.projectId) params.set('project_id', this.config.projectId);
    const payload = await this.request<unknown>(`/api/v1/skills/?${params.toString()}`, {
      signal,
    });
    return readArray<ManagedSkill>(payload, ['skills', 'items', 'data']);
  }

  async setManagedSkillStatus(
    skillId: string,
    status: 'active' | 'disabled' | 'deprecated',
  ): Promise<ManagedSkill> {
    const params = new URLSearchParams({ status });
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    return this.request<ManagedSkill>(
      `/api/v1/skills/${encodeURIComponent(skillId)}/status?${params.toString()}`,
      { method: 'PATCH' },
    );
  }

  async createManagedSkill(input: ManagedSkillCreateMutation): Promise<ManagedSkill> {
    const params = this.managedSkillTenantParams();
    return this.request<ManagedSkill>(`/api/v1/skills/?${params.toString()}`, {
      method: 'POST',
      body: input,
    });
  }

  async getManagedSkillContent(skillId: string): Promise<ManagedSkillContent> {
    const params = this.managedSkillTenantParams();
    return this.request<ManagedSkillContent>(
      `/api/v1/skills/${encodeURIComponent(skillId)}/content?${params.toString()}`,
    );
  }

  async updateManagedSkill(
    skillId: string,
    input: Omit<ManagedSkillMutation, 'full_content'>,
  ): Promise<ManagedSkill> {
    const params = this.managedSkillTenantParams();
    return this.request<ManagedSkill>(
      `/api/v1/skills/${encodeURIComponent(skillId)}?${params.toString()}`,
      { method: 'PUT', body: input },
    );
  }

  async updateManagedSkillContent(skillId: string, fullContent: string): Promise<ManagedSkill> {
    const params = this.managedSkillTenantParams();
    return this.request<ManagedSkill>(
      `/api/v1/skills/${encodeURIComponent(skillId)}/content?${params.toString()}`,
      { method: 'PUT', body: { full_content: fullContent } },
    );
  }

  async deleteManagedSkill(skillId: string): Promise<void> {
    const params = this.managedSkillTenantParams();
    await this.request<void>(
      `/api/v1/skills/${encodeURIComponent(skillId)}?${params.toString()}`,
      { method: 'DELETE' },
    );
  }

  async importManagedSkillPackage(
    input: ManagedSkillImportInput,
  ): Promise<ManagedSkillLifecycle> {
    const params = this.managedSkillTenantParams();
    return this.request<ManagedSkillLifecycle>(`/api/v1/skills/import?${params.toString()}`, {
      method: 'POST',
      body: input,
    });
  }

  async importManagedSkillZip(
    archive: File,
    input: ManagedSkillZipImportInput = {},
  ): Promise<ManagedSkillLifecycle> {
    const params = this.managedSkillTenantParams();
    const formData = new FormData();
    formData.append('archive', archive);
    formData.append('scope', input.scope ?? 'tenant');
    formData.append('overwrite', String(input.overwrite ?? false));
    if (input.project_id) formData.append('project_id', input.project_id);
    if (input.change_summary) formData.append('change_summary', input.change_summary);
    return this.request<ManagedSkillLifecycle>(
      `/api/v1/skills/import/zip?${params.toString()}`,
      { method: 'POST', body: formData },
    );
  }

  async listManagedSkillVersions(
    skillId: string,
    signal?: AbortSignal,
  ): Promise<ManagedSkillVersionList> {
    const params = this.managedSkillTenantParams();
    params.set('limit', '50');
    return this.request<ManagedSkillVersionList>(
      `/api/v1/skills/${encodeURIComponent(skillId)}/versions?${params.toString()}`,
      { signal },
    );
  }

  async rollbackManagedSkill(skillId: string, versionNumber: number): Promise<ManagedSkill> {
    const params = this.managedSkillTenantParams();
    return this.request<ManagedSkill>(
      `/api/v1/skills/${encodeURIComponent(skillId)}/rollback?${params.toString()}`,
      { method: 'POST', body: { version_number: versionNumber } },
    );
  }

  async exportManagedSkillPackage(skillId: string): Promise<ManagedSkillPackage> {
    const params = this.managedSkillTenantParams();
    return this.request<ManagedSkillPackage>(
      `/api/v1/skills/${encodeURIComponent(skillId)}/export?${params.toString()}`,
    );
  }

  async getManagedSkillVersion(
    skillId: string,
    versionNumber: number,
  ): Promise<ManagedSkillVersionDetail> {
    const params = this.managedSkillTenantParams();
    return this.request<ManagedSkillVersionDetail>(
      `/api/v1/skills/${encodeURIComponent(skillId)}/versions/${versionNumber}?${params.toString()}`,
    );
  }

  async getManagedSkillEvolution(skillId: string): Promise<ManagedSkillEvolutionDetail> {
    const params = this.managedSkillTenantParams();
    return this.request<ManagedSkillEvolutionDetail>(
      `/api/v1/skills/${encodeURIComponent(skillId)}/evolution?${params.toString()}`,
    );
  }

  async runManagedSkillEvolution(skillId: string): Promise<ManagedSkillEvolutionRun> {
    const params = this.managedSkillTenantParams();
    return this.request<ManagedSkillEvolutionRun>(
      `/api/v1/skills/${encodeURIComponent(skillId)}/evolution/run?${params.toString()}`,
      { method: 'POST' },
    );
  }

  async applyManagedSkillEvolutionJob(jobId: string): Promise<ManagedSkillEvolutionJob> {
    return this.mutateManagedSkillEvolutionJob(jobId, 'apply');
  }

  async rejectManagedSkillEvolutionJob(jobId: string): Promise<ManagedSkillEvolutionJob> {
    return this.mutateManagedSkillEvolutionJob(jobId, 'reject');
  }

  private async mutateManagedSkillEvolutionJob(
    jobId: string,
    action: 'apply' | 'reject',
  ): Promise<ManagedSkillEvolutionJob> {
    const params = this.managedSkillTenantParams();
    return this.request<ManagedSkillEvolutionJob>(
      `/api/v1/skills/evolution/jobs/${encodeURIComponent(jobId)}/${action}?${params.toString()}`,
      { method: 'POST' },
    );
  }

  private managedSkillTenantParams(): URLSearchParams {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    return new URLSearchParams({ tenant_id: tenantId });
  }

  async listMCPApps(projectId: string): Promise<DesktopMCPAppSummary[]> {
    const scopedProjectId = requireValue(projectId, 'project id');
    const params = new URLSearchParams({ project_id: scopedProjectId });
    return this.request<DesktopMCPAppSummary[]>(`/api/v1/mcp/apps?${params.toString()}`);
  }

  async callMCPAppTool(
    appId: string,
    toolName: string,
    argumentsValue: Record<string, unknown>,
  ): Promise<DesktopMCPAppToolCallResponse> {
    return this.request<DesktopMCPAppToolCallResponse>(
      `/api/v1/mcp/apps/${encodeURIComponent(requireValue(appId, 'MCP App id'))}/tool-call`,
      {
        method: 'POST',
        body: {
          tool_name: requireValue(toolName, 'MCP tool name'),
          arguments: argumentsValue,
        },
      },
    );
  }

  async callMCPAppToolDirect(
    projectId: string,
    serverName: string,
    toolName: string,
    argumentsValue: Record<string, unknown>,
  ): Promise<DesktopMCPAppToolCallResponse> {
    return this.request<DesktopMCPAppToolCallResponse>('/api/v1/mcp/apps/proxy/tool-call', {
      method: 'POST',
      body: {
        project_id: requireValue(projectId, 'project id'),
        server_name: requireValue(serverName, 'MCP server name'),
        tool_name: requireValue(toolName, 'MCP tool name'),
        arguments: argumentsValue,
      },
    });
  }

  async readMCPAppResource(
    projectId: string,
    uri: string,
    serverName?: string | null,
  ): Promise<DesktopMCPAppResourceReadResponse> {
    return this.request<DesktopMCPAppResourceReadResponse>('/api/v1/mcp/apps/resources/read', {
      method: 'POST',
      body: {
        project_id: requireValue(projectId, 'project id'),
        uri: requireValue(uri, 'MCP resource URI'),
        ...(serverName?.trim() ? { server_name: serverName.trim() } : {}),
      },
    });
  }

  async listMCPAppResources(
    projectId: string,
    serverName?: string | null,
  ): Promise<DesktopMCPAppResourceListResponse> {
    return this.request<DesktopMCPAppResourceListResponse>('/api/v1/mcp/apps/resources/list', {
      method: 'POST',
      body: {
        project_id: requireValue(projectId, 'project id'),
        ...(serverName?.trim() ? { server_name: serverName.trim() } : {}),
      },
    });
  }

  async listManagedPlugins(signal?: AbortSignal): Promise<ManagedPlugin[]> {
    return (await this.getManagedPluginRuntime(signal)).items;
  }

  async getManagedPluginRuntime(signal?: AbortSignal): Promise<ManagedPluginRuntime> {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    const payload = await this.request<unknown>(
      `/api/v1/channels/tenants/${encodeURIComponent(tenantId)}/plugins`,
      { signal },
    );
    return {
      items: readArray<ManagedPlugin>(payload, ['items', 'plugins', 'data']).map((plugin) => ({
        ...plugin,
        id: plugin.id ?? plugin.name,
      })),
      diagnostics: readArray(payload, ['diagnostics']),
    };
  }

  async setManagedPluginEnabled(
    pluginId: string,
    enabled: boolean,
  ): Promise<PluginActionResponse> {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    return this.request<PluginActionResponse>(
      `/api/v1/channels/tenants/${encodeURIComponent(tenantId)}/plugins/${encodeURIComponent(
        pluginId,
      )}/${enabled ? 'enable' : 'disable'}`,
      { method: 'POST' },
    );
  }

  async installManagedPlugin(requirement: string): Promise<PluginActionResponse> {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    return this.request<PluginActionResponse>(
      `/api/v1/channels/tenants/${encodeURIComponent(tenantId)}/plugins/install`,
      { method: 'POST', body: { requirement: requirement.trim() } },
    );
  }

  async reloadManagedPlugins(): Promise<PluginActionResponse> {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    return this.request<PluginActionResponse>(
      `/api/v1/channels/tenants/${encodeURIComponent(tenantId)}/plugins/reload`,
      { method: 'POST' },
    );
  }

  async uninstallManagedPlugin(pluginId: string): Promise<PluginActionResponse> {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    return this.request<PluginActionResponse>(
      `/api/v1/channels/tenants/${encodeURIComponent(tenantId)}/plugins/${encodeURIComponent(
        pluginId,
      )}/uninstall`,
      { method: 'POST' },
    );
  }

  async getManagedPluginConfigSchema(pluginId: string): Promise<PluginConfigSchema> {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    return this.request<PluginConfigSchema>(
      `/api/v1/channels/tenants/${encodeURIComponent(tenantId)}/plugins/${encodeURIComponent(
        pluginId,
      )}/config-schema`,
    );
  }

  async getManagedPluginConfig(pluginId: string): Promise<PluginConfigRecord> {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    return this.request<PluginConfigRecord>(
      `/api/v1/channels/tenants/${encodeURIComponent(tenantId)}/plugins/${encodeURIComponent(
        pluginId,
      )}/config`,
    );
  }

  async updateManagedPluginConfig(
    pluginId: string,
    body: UpdatePluginConfigRequest,
  ): Promise<PluginConfigRecord> {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    return this.request<PluginConfigRecord>(
      `/api/v1/channels/tenants/${encodeURIComponent(tenantId)}/plugins/${encodeURIComponent(
        pluginId,
      )}/config`,
      { method: 'PUT', body },
    );
  }

  async listManagedChannelCatalog(signal?: AbortSignal): Promise<ManagedChannelPluginCatalogItem[]> {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    const payload = await this.request<unknown>(
      `/api/v1/channels/tenants/${encodeURIComponent(tenantId)}/plugins/channel-catalog`,
      { signal },
    );
    return readArray<ManagedChannelPluginCatalogItem>(payload, ['items', 'data']);
  }

  async getManagedChannelSchema(channelType: string): Promise<ManagedChannelPluginConfigSchema> {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    return this.request<ManagedChannelPluginConfigSchema>(
      `/api/v1/channels/tenants/${encodeURIComponent(tenantId)}/plugins/channel-catalog/${encodeURIComponent(
        channelType,
      )}/schema`,
    );
  }

  async listManagedChannelConfigs(signal?: AbortSignal): Promise<ManagedChannelConfig[]> {
    const projectId = requireValue(this.config.projectId, 'project id');
    const payload = await this.request<unknown>(
      `/api/v1/channels/projects/${encodeURIComponent(projectId)}/configs`,
      { signal },
    );
    return readArray<ManagedChannelConfig>(payload, ['items', 'data']);
  }

  async createManagedChannelConfig(
    body: CreateManagedChannelConfigRequest,
  ): Promise<ManagedChannelConfig> {
    const projectId = requireValue(this.config.projectId, 'project id');
    return this.request<ManagedChannelConfig>(
      `/api/v1/channels/projects/${encodeURIComponent(projectId)}/configs`,
      { method: 'POST', body },
    );
  }

  async updateManagedChannelConfig(
    configId: string,
    body: UpdateManagedChannelConfigRequest,
  ): Promise<ManagedChannelConfig> {
    return this.request<ManagedChannelConfig>(
      `/api/v1/channels/configs/${encodeURIComponent(configId)}`,
      { method: 'PUT', body },
    );
  }

  async testManagedChannelConfig(configId: string): Promise<ManagedChannelTestResult> {
    return this.request<ManagedChannelTestResult>(
      `/api/v1/channels/configs/${encodeURIComponent(configId)}/test`,
      { method: 'POST' },
    );
  }

  async deleteManagedChannelConfig(configId: string): Promise<void> {
    await this.request<unknown>(`/api/v1/channels/configs/${encodeURIComponent(configId)}`, {
      method: 'DELETE',
    });
  }

  async listManagedAgents(signal?: AbortSignal): Promise<ManagedAgentDefinition[]> {
    const params = new URLSearchParams({ limit: '100', enabled_only: 'false' });
    if (this.config.projectId) params.set('project_id', this.config.projectId);
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    const payload = await this.request<unknown>(
      `/api/v1/agent/definitions?${params.toString()}`,
      { signal },
    );
    return readArray<ManagedAgentDefinition>(payload, ['definitions', 'items', 'data']);
  }

  async setManagedAgentEnabled(
    definitionId: string,
    enabled: boolean,
  ): Promise<ManagedAgentDefinition> {
    const params = new URLSearchParams();
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    if (this.config.projectId) params.set('project_id', this.config.projectId);
    const query = params.toString();
    return this.request<ManagedAgentDefinition>(
      `/api/v1/agent/definitions/${encodeURIComponent(definitionId)}/enabled${
        query ? `?${query}` : ''
      }`,
      { method: 'PATCH', body: { enabled } },
    );
  }

  async createManagedAgentDefinition(
    body: ManagedAgentDefinitionMutation,
  ): Promise<ManagedAgentDefinition> {
    const params = new URLSearchParams();
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    const query = params.toString();
    return this.request<ManagedAgentDefinition>(
      `/api/v1/agent/definitions${query ? `?${query}` : ''}`,
      { method: 'POST', body },
    );
  }

  async updateManagedAgentDefinition(
    definitionId: string,
    body: ManagedAgentDefinitionMutation,
  ): Promise<ManagedAgentDefinition> {
    const params = new URLSearchParams();
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    const query = params.toString();
    return this.request<ManagedAgentDefinition>(
      `/api/v1/agent/definitions/${encodeURIComponent(definitionId)}${
        query ? `?${query}` : ''
      }`,
      { method: 'PUT', body },
    );
  }

  async deleteManagedAgentDefinition(
    definitionId: string,
  ): Promise<{ deleted: boolean; id: string }> {
    const params = new URLSearchParams();
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    const query = params.toString();
    return this.request<{ deleted: boolean; id: string }>(
      `/api/v1/agent/definitions/${encodeURIComponent(definitionId)}${
        query ? `?${query}` : ''
      }`,
      { method: 'DELETE' },
    );
  }

  async listManagedSubAgents(signal?: AbortSignal): Promise<ManagedSubAgent[]> {
    const params = new URLSearchParams({ limit: '100', include_filesystem: 'true' });
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    const payload = await this.request<unknown>(`/api/v1/subagents/?${params.toString()}`, {
      signal,
    });
    return readArray<ManagedSubAgent>(payload, ['subagents', 'items', 'data']);
  }

  async setManagedSubAgentEnabled(
    subagentId: string,
    enabled: boolean,
  ): Promise<ManagedSubAgent> {
    const params = new URLSearchParams({ enabled: String(enabled) });
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    return this.request<ManagedSubAgent>(
      `/api/v1/subagents/${encodeURIComponent(subagentId)}/enable?${params.toString()}`,
      { method: 'PATCH' },
    );
  }

  async listManagedSubAgentTemplates(signal?: AbortSignal): Promise<ManagedSubAgentTemplateList> {
    const params = new URLSearchParams({ limit: '100' });
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    return this.request<ManagedSubAgentTemplateList>(
      `/api/v1/subagents/templates/list?${params.toString()}`,
      { signal },
    );
  }

  async installManagedSubAgentTemplate(templateId: string): Promise<ManagedSubAgent> {
    const params = new URLSearchParams();
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    return this.request<ManagedSubAgent>(
      `/api/v1/subagents/templates/${encodeURIComponent(templateId)}/install?${params.toString()}`,
      { method: 'POST' },
    );
  }

  async importManagedFilesystemSubAgent(
    name: string,
    projectId?: string,
  ): Promise<ManagedSubAgent> {
    const params = new URLSearchParams();
    if (projectId) params.set('project_id', projectId);
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    return this.request<ManagedSubAgent>(
      `/api/v1/subagents/filesystem/${encodeURIComponent(name)}/import?${params.toString()}`,
      { method: 'POST' },
    );
  }

  async createManagedSubAgent(input: ManagedSubAgentMutation): Promise<ManagedSubAgent> {
    const params = new URLSearchParams();
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    return this.request<ManagedSubAgent>(`/api/v1/subagents/?${params.toString()}`, {
      method: 'POST',
      body: input,
    });
  }

  async updateManagedSubAgent(
    subagentId: string,
    input: ManagedSubAgentMutation,
  ): Promise<ManagedSubAgent> {
    const params = new URLSearchParams();
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    return this.request<ManagedSubAgent>(
      `/api/v1/subagents/${encodeURIComponent(subagentId)}?${params.toString()}`,
      { method: 'PUT', body: input },
    );
  }

  async deleteManagedSubAgent(subagentId: string): Promise<void> {
    const params = new URLSearchParams();
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    await this.request<void>(
      `/api/v1/subagents/${encodeURIComponent(subagentId)}?${params.toString()}`,
      { method: 'DELETE' },
    );
  }

  async listTasks(signal?: AbortSignal): Promise<WorkspaceTask[]> {
    const payload = await this.request<unknown>(this.workspaceRoot('/tasks'), { signal });
    return readArray<WorkspaceTask>(payload, ['tasks', 'items', 'data']);
  }

  async getPlanSnapshot(signal?: AbortSignal): Promise<PlanSnapshot> {
    return this.request<PlanSnapshot>(this.workspaceRoot('/plan'), { signal });
  }

  async getSandbox(signal?: AbortSignal): Promise<ProjectSandbox> {
    const projectId = requireValue(this.config.projectId, 'project id');
    return this.request<ProjectSandbox>(
      `/api/v1/projects/${encodeURIComponent(projectId)}/sandbox`,
      { signal },
    );
  }

  async uploadSandboxFile(
    file: Pick<File, 'name' | 'type' | 'size' | 'arrayBuffer'>,
  ): Promise<AgentInputFileMetadata> {
    const projectId = requireValue(this.config.projectId, 'project id');
    const filename = requireValue(file.name, 'filename');
    const contentBase64 = encodeArrayBufferAsBase64(await file.arrayBuffer());
    const timeout = Math.min(
      300,
      Math.max(60, Math.ceil(file.size / (1024 * 1024)) * 2),
    );
    const payload = await this.request<unknown>(
      `/api/v1/projects/${encodeURIComponent(projectId)}/sandbox/execute`,
      {
        method: 'POST',
        body: {
          tool_name: 'import_file',
          arguments: {
            filename,
            content_base64: contentBase64,
            destination: '/workspace/input',
            overwrite: true,
          },
          timeout,
        },
      },
    );
    return requireSandboxUploadMetadata(payload, {
      filename,
      mimeType: file.type || 'application/octet-stream',
      sizeBytes: file.size,
    });
  }

  async seedProxyAuthCookie(): Promise<void> {
    const projectId = requireValue(this.config.projectId, 'project id');
    await this.request<unknown>(
      `/api/v1/projects/${encodeURIComponent(projectId)}/sandbox/proxy-auth-cookie`,
      { method: 'POST' },
    );
  }

  async startTerminal(
    runId: string,
    expectedRunRevision: number,
  ): Promise<TerminalServiceResponse> {
    const projectId = requireValue(this.config.projectId, 'project id');
    return this.request<TerminalServiceResponse>(
      `/api/v1/projects/${encodeURIComponent(projectId)}/sandbox/terminal`,
      {
        method: 'POST',
        body: { run_id: runId, expected_run_revision: expectedRunRevision },
      },
    );
  }

  async loadRuntime(signal?: AbortSignal): Promise<RuntimeDataset> {
    const projectId = this.config.projectId.trim();
    const [
      workspaces,
      messages,
      tasks,
      plan,
      workspaceMembers,
      workspaceAgents,
      myWorkResult,
    ] = await Promise.all([
      this.listWorkspaces(signal),
      this.config.workspaceId ? this.listMessages(signal) : Promise.resolve([]),
      this.config.workspaceId ? this.listTasks(signal) : Promise.resolve([]),
      this.config.workspaceId
        ? this.getPlanSnapshot(signal).catch(() => null)
        : Promise.resolve(null),
      this.config.workspaceId
        ? loadWorkspaceAuthority(this.listWorkspaceMembers(signal))
        : Promise.resolve(unavailableWorkspaceAuthority<WorkspaceMemberSummary>()),
      this.config.workspaceId
        ? loadWorkspaceAuthority(this.listWorkspaceAgents(signal))
        : Promise.resolve(unavailableWorkspaceAuthority<WorkspaceAgentBinding>()),
      projectId
        ? this.listMyWork(projectId, signal)
            .then((response) => ({ items: response.items, error: null }))
            .catch((error) => ({
              items: [],
              error: error instanceof Error ? error.message : String(error),
            }))
        : Promise.resolve({ items: [], error: null }),
    ]);
    const conversations = await Promise.all(
      workspaces.map((workspace) =>
        this.listConversations(projectId, workspace.id, signal)
          .then((response) => [workspace.id, response.items] as const)
          .catch(() => [workspace.id, []] as const),
      ),
    );
    return {
      workspaces,
      workspacesByProject: projectId ? { [projectId]: workspaces } : {},
      conversationsByWorkspace: Object.fromEntries(conversations),
      nodeState: { projects: {}, workspaces: {} },
      messages,
      tasks,
      plan,
      workspaceMembers,
      workspaceAgents,
      sandbox: null,
      myWork: myWorkResult.items,
      myWorkError: myWorkResult.error,
    };
  }

  terminalProxyUrl(sessionId?: string | null, boundProjectId?: string | null): string {
    const projectId = requireValue(boundProjectId ?? this.config.projectId, 'project id');
    const path = `/api/v1/projects/${encodeURIComponent(projectId)}/sandbox/terminal/proxy/ws${
      sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''
    }`;
    return websocketUrl(this.config.apiBaseUrl, path);
  }

  agentWsUrl(sessionId: string): string {
    return websocketUrl(
      this.config.apiBaseUrl,
      `/api/v1/agent/ws?session_id=${encodeURIComponent(sessionId)}`,
    );
  }

  agentWsProtocols(): string[] {
    const credential = requireValue(this.config.apiKey.trim(), 'authenticated session');
    const launchCapability = desktopLaunchCapability(this.config);
    return launchCapability
      ? ['memstack.launch', launchCapability, 'memstack.auth', credential]
      : ['memstack.auth', credential];
  }

  private workspacePath(suffix: string): string {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    const projectId = requireValue(this.config.projectId, 'project id');
    const workspaceId = requireValue(this.config.workspaceId, 'workspace id');
    return `/api/v1/tenants/${encodeURIComponent(tenantId)}/projects/${encodeURIComponent(
      projectId,
    )}/workspaces/${encodeURIComponent(workspaceId)}${suffix}`;
  }

  private workspaceRoot(suffix: string): string {
    const workspaceId = requireValue(this.config.workspaceId, 'workspace id');
    return `/api/v1/workspaces/${encodeURIComponent(workspaceId)}${suffix}`;
  }

  private async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const headers = new Headers({ Accept: 'application/json' });
    const formDataBody =
      typeof FormData !== 'undefined' && options.body instanceof FormData
        ? options.body
        : null;
    if (options.body !== undefined && !formDataBody) {
      headers.set('Content-Type', options.contentType ?? 'application/json');
    }
    const credential = desktopApiCredential(this.config);
    if (!options.skipAuth && credential) {
      headers.set('Authorization', `Bearer ${credential}`);
    }
    const launchCapability = desktopLaunchCapability(this.config);
    if (launchCapability) {
      headers.set('X-Agistack-Launch', launchCapability);
    }

    const body = formDataBody
      ? formDataBody
      : options.body instanceof URLSearchParams
        ? options.body.toString()
        : options.body === undefined
          ? undefined
          : JSON.stringify(options.body);

    const response = await fetch(absoluteUrl(this.config.apiBaseUrl, path), {
      method: options.method ?? 'GET',
      headers,
      body,
      signal: options.signal,
    });

    const contentType = response.headers.get('content-type') ?? '';
    const payload = contentType.includes('application/json')
      ? await response.json().catch(() => null)
      : await response.text().catch(() => '');

    if (!response.ok) {
      const message =
        typeof payload === 'object' && payload && 'detail' in payload
          ? String((payload as { detail: unknown }).detail)
          : `HTTP ${response.status}`;
      throw new DesktopApiError(message, response.status, payload);
    }

    return payload as T;
  }
}

export function desktopApiCredential(config: DesktopRuntimeConfig): string {
  return config.apiKey.trim();
}

export function desktopLaunchCapability(config: DesktopRuntimeConfig): string {
  return config.mode === 'local' ? config.localApiToken.trim() : '';
}

export function absoluteUrl(baseUrl: string, path: string): string {
  const base = baseUrl.trim().replace(/\/+$/, '');
  const nextPath = path.startsWith('/') ? path : `/${path}`;
  return `${base}${nextPath}`;
}

export function websocketUrl(baseUrl: string, path: string): string {
  const url = new URL(absoluteUrl(baseUrl, path));
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString();
}

function encodeArrayBufferAsBase64(value: ArrayBuffer): string {
  const bytes = new Uint8Array(value);
  const chunks: string[] = [];
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    chunks.push(String.fromCharCode(...bytes.subarray(offset, offset + chunkSize)));
  }
  return btoa(chunks.join(''));
}

function requireSandboxUploadMetadata(
  payload: unknown,
  file: { filename: string; mimeType: string; sizeBytes: number },
): AgentInputFileMetadata {
  if (
    !isRecord(payload) ||
    payload.success !== true ||
    payload.is_error !== false ||
    !Array.isArray(payload.content)
  ) {
    throw invalidSandboxUploadResponse(payload);
  }
  const text = payload.content
    .filter(isRecord)
    .map((item) => item.text)
    .find((value): value is string => typeof value === 'string' && Boolean(value.trim()));
  if (!text) throw invalidSandboxUploadResponse(payload);
  let result: unknown;
  try {
    result = JSON.parse(text);
  } catch {
    throw invalidSandboxUploadResponse(payload);
  }
  if (
    !isRecord(result) ||
    result.success === false ||
    !isNonEmptyString(result.path) ||
    !isUnsignedSafeInteger(result.size_bytes) ||
    result.size_bytes !== file.sizeBytes
  ) {
    throw invalidSandboxUploadResponse(payload);
  }
  return {
    filename: file.filename,
    sandbox_path: result.path,
    mime_type: file.mimeType,
    size_bytes: result.size_bytes,
  };
}

function invalidSandboxUploadResponse(payload: unknown): DesktopApiError {
  return new DesktopApiError('Invalid sandbox upload response', 502, payload);
}

function readArray<T>(payload: unknown, keys: string[]): T[] {
  if (Array.isArray(payload)) return payload as T[];
  if (!payload || typeof payload !== 'object') return [];
  const objectPayload = payload as Record<string, unknown>;
  for (const key of keys) {
    const value = objectPayload[key];
    if (Array.isArray(value)) return value as T[];
  }
  return [];
}

async function loadPagedIdentityCatalog<T extends { id: string }>(
  label: string,
  itemKey: string,
  requestPage: (page: number, pageSize: number) => Promise<unknown>,
  normalizeItem: (value: unknown) => T | null,
): Promise<T[]> {
  const items: T[] = [];
  const seenIds = new Set<string>();
  let expectedTotal: number | null = null;

  for (let page = 1; page <= IDENTITY_CATALOG_MAX_PAGES; page += 1) {
    const payload = await requestPage(page, IDENTITY_CATALOG_PAGE_SIZE);
    const current = requireIdentityCatalogPage(
      payload,
      label,
      itemKey,
      page,
      IDENTITY_CATALOG_PAGE_SIZE,
      normalizeItem,
    );
    if (expectedTotal === null) {
      expectedTotal = current.total;
      if (
        Math.ceil(expectedTotal / IDENTITY_CATALOG_PAGE_SIZE) >
        IDENTITY_CATALOG_MAX_PAGES
      ) {
        throw invalidIdentityCatalogResponse(label, payload);
      }
    } else if (current.total !== expectedTotal) {
      throw invalidIdentityCatalogResponse(label, payload);
    }

    for (const item of current.items) {
      if (seenIds.has(item.id)) throw invalidIdentityCatalogResponse(label, payload);
      seenIds.add(item.id);
      items.push(item);
    }
    if (items.length === expectedTotal) return items;
    if (
      items.length > expectedTotal ||
      current.items.length === 0 ||
      current.items.length < IDENTITY_CATALOG_PAGE_SIZE
    ) {
      throw invalidIdentityCatalogResponse(label, payload);
    }
  }
  throw invalidIdentityCatalogResponse(label, {
    detail: 'identity_catalog_page_limit_exceeded',
  });
}

function requireIdentityCatalogPage<T>(
  payload: unknown,
  label: string,
  itemKey: string,
  expectedPage: number,
  expectedPageSize: number,
  normalizeItem: (value: unknown) => T | null,
): { items: T[]; total: number } {
  if (
    !isRecord(payload) ||
    !Array.isArray(payload[itemKey]) ||
    !isUnsignedSafeInteger(payload.total) ||
    payload.page !== expectedPage ||
    payload.page_size !== expectedPageSize ||
    payload[itemKey].length > expectedPageSize ||
    payload[itemKey].length > payload.total
  ) {
    throw invalidIdentityCatalogResponse(label, payload);
  }
  const items = payload[itemKey].map(normalizeItem);
  if (items.some((item) => item === null)) {
    throw invalidIdentityCatalogResponse(label, payload);
  }
  return { items: items as T[], total: payload.total };
}

function invalidIdentityCatalogResponse(label: string, payload: unknown): DesktopApiError {
  return new DesktopApiError(`Invalid ${label} response`, 502, payload);
}

function normalizeTenantSummary(value: unknown): TenantSummary | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value.id) ||
    !isNonEmptyString(value.name) ||
    !isOptionalString(value.slug) ||
    !isOptionalNullableString(value.description) ||
    !isOptionalString(value.owner_id) ||
    !isOptionalString(value.plan) ||
    !isOptionalString(value.created_at) ||
    !isOptionalNullableString(value.updated_at)
  ) {
    return null;
  }
  return {
    id: value.id,
    name: value.name,
    ...(value.slug === undefined ? {} : { slug: value.slug }),
    ...(value.description === undefined ? {} : { description: value.description }),
    ...(value.owner_id === undefined ? {} : { owner_id: value.owner_id }),
    ...(value.plan === undefined ? {} : { plan: value.plan }),
    ...(value.created_at === undefined ? {} : { created_at: value.created_at }),
    ...(value.updated_at === undefined ? {} : { updated_at: value.updated_at }),
  };
}

function normalizeProjectSummary(value: unknown, tenantId: string): ProjectSummary | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value.id) ||
    !isNonEmptyString(value.tenant_id) ||
    (tenantId && value.tenant_id !== tenantId) ||
    !isNonEmptyString(value.name) ||
    !isOptionalNullableString(value.description) ||
    !isOptionalString(value.owner_id) ||
    !isOptionalStringArray(value.member_ids) ||
    (value.is_public !== undefined && typeof value.is_public !== 'boolean') ||
    !isOptionalString(value.agent_conversation_mode) ||
    !isOptionalString(value.created_at) ||
    !isOptionalNullableString(value.updated_at) ||
    !isOptionalNullableRecord(value.stats)
  ) {
    return null;
  }
  return {
    id: value.id,
    tenant_id: value.tenant_id,
    name: value.name,
    ...(value.description === undefined ? {} : { description: value.description }),
    ...(value.owner_id === undefined ? {} : { owner_id: value.owner_id }),
    ...(value.member_ids === undefined ? {} : { member_ids: value.member_ids }),
    ...(value.is_public === undefined ? {} : { is_public: value.is_public }),
    ...(value.agent_conversation_mode === undefined
      ? {}
      : { agent_conversation_mode: value.agent_conversation_mode }),
    ...(value.created_at === undefined ? {} : { created_at: value.created_at }),
    ...(value.updated_at === undefined ? {} : { updated_at: value.updated_at }),
    ...(value.stats === undefined ? {} : { stats: value.stats }),
  };
}

async function loadScopedWorkspaceCatalog(
  tenantId: string,
  projectId: string,
  requestPage: (offset: number) => Promise<unknown>,
): Promise<WorkspaceSummary[]> {
  const items: WorkspaceSummary[] = [];
  const seenIds = new Set<string>();
  for (let pageNumber = 0; pageNumber < HIERARCHY_CATALOG_MAX_PAGES; pageNumber += 1) {
    const payload = await requestPage(pageNumber * HIERARCHY_CATALOG_PAGE_SIZE);
    if (!Array.isArray(payload) || payload.length > HIERARCHY_CATALOG_PAGE_SIZE) {
      throw invalidHierarchyCatalogResponse('workspace catalog', payload);
    }
    const page = payload.map((value) => normalizeWorkspaceSummary(value, tenantId, projectId));
    if (page.some((item) => item === null)) {
      throw invalidHierarchyCatalogResponse('workspace catalog', payload);
    }
    for (const item of page as WorkspaceSummary[]) {
      if (seenIds.has(item.id)) {
        throw invalidHierarchyCatalogResponse('workspace catalog', payload);
      }
      seenIds.add(item.id);
      items.push(item);
    }
    if (page.length < HIERARCHY_CATALOG_PAGE_SIZE) return items;
  }
  throw invalidHierarchyCatalogResponse('workspace catalog', {
    detail: 'hierarchy_catalog_page_limit_exceeded',
  });
}

function normalizeWorkspaceSummary(
  value: unknown,
  tenantId: string,
  projectId: string,
): WorkspaceSummary | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value.id) ||
    value.tenant_id !== tenantId ||
    value.project_id !== projectId ||
    !isNonEmptyString(value.name) ||
    !isOptionalString(value.title) ||
    !isOptionalString(value.created_by) ||
    !isOptionalNullableString(value.description) ||
    !isOptionalString(value.status) ||
    !isOptionalBoolean(value.is_archived) ||
    !isOptionalString(value.office_status) ||
    !isOptionalNullableRecord(value.hex_layout_config) ||
    !isOptionalString(value.created_at) ||
    !isOptionalNullableString(value.updated_at) ||
    !isOptionalNullableRecord(value.metadata)
  ) {
    return null;
  }
  return {
    id: value.id,
    tenant_id: value.tenant_id,
    project_id: value.project_id,
    name: value.name,
    ...(value.title === undefined ? {} : { title: value.title }),
    ...(value.created_by === undefined ? {} : { created_by: value.created_by }),
    ...(value.description === undefined ? {} : { description: value.description }),
    ...(value.status === undefined ? {} : { status: value.status }),
    ...(value.is_archived === undefined ? {} : { is_archived: value.is_archived }),
    ...(value.office_status === undefined ? {} : { office_status: value.office_status }),
    ...(value.hex_layout_config === undefined
      ? {}
      : { hex_layout_config: value.hex_layout_config }),
    ...(value.created_at === undefined ? {} : { created_at: value.created_at }),
    ...(value.updated_at === undefined ? {} : { updated_at: value.updated_at }),
    ...(value.metadata === undefined ? {} : { metadata: value.metadata }),
  };
}

const TASK_SESSION_REQUIRED_RESPONSE_KEYS = new Set([
  'replayed',
  'workspace',
  'conversation',
  'initial_message',
]);
const TASK_SESSION_OPTIONAL_RESPONSE_KEYS = new Set(['policy', 'capability_version']);
const TASK_SESSION_CAPABILITY_KEYS = new Set([
  'schema_version',
  'atomic_creation',
  'initial_conversation_mode',
  'initial_plan_mode',
]);
const TASK_SESSION_CAPABILITY_OPTIONAL_KEYS = new Set([
  'workspace_agent_policy',
  'capability_version',
]);

function requireCreateTaskSessionResponse(
  payload: unknown,
  tenantId: string,
  projectId: string,
  input: CreateTaskSessionRequest,
): CreateTaskSessionResponse {
  if (
    !isRecord(payload) ||
    !hasRequiredAndOptionalKeys(
      payload,
      TASK_SESSION_REQUIRED_RESPONSE_KEYS,
      TASK_SESSION_OPTIONAL_RESPONSE_KEYS,
    ) ||
    typeof payload.replayed !== 'boolean'
  ) {
    throw invalidTaskSessionResponse(payload);
  }
  const workspace = normalizeWorkspaceSummary(payload.workspace, tenantId, projectId);
  if (
    !workspace ||
    workspace.is_archived !== false ||
    (input.workspace.kind === 'existing' && workspace.id !== input.workspace.workspace_id)
  ) {
    throw invalidTaskSessionResponse(payload);
  }
  const conversation = normalizeAgentConversation(
    payload.conversation,
    tenantId,
    projectId,
    workspace.id,
  );
  if (
    !conversation ||
    conversation.title !== input.conversation.title ||
    conversation.status !== 'active' ||
    conversation.conversation_mode !== 'workspace' ||
    conversation.current_mode !== 'plan' ||
    conversation.workspace_id !== workspace.id ||
    !isRecord(conversation.agent_config) ||
    conversation.agent_config.selected_agent_id !== 'builtin:all-access' ||
    conversation.agent_config.capability_mode !== input.conversation.capability_mode
  ) {
    throw invalidTaskSessionResponse(payload);
  }
  const initialMessage = payload.initial_message;
  if (
    !isRecord(initialMessage) ||
    !isNonEmptyString(initialMessage.id) ||
    initialMessage.workspace_id !== workspace.id ||
    !isNonEmptyString(initialMessage.sender_id) ||
    initialMessage.sender_type !== 'human' ||
    initialMessage.content !== input.initial_message.content ||
    !Array.isArray(initialMessage.mentions) ||
    !initialMessage.mentions.every((mention) => typeof mention === 'string') ||
    initialMessage.parent_message_id !== null ||
    !isRecord(initialMessage.metadata) ||
    initialMessage.metadata.source !== 'task_session' ||
    initialMessage.metadata.conversation_id !== conversation.id ||
    !isNonEmptyString(initialMessage.created_at)
  ) {
    throw invalidTaskSessionResponse(payload);
  }
  return {
    replayed: payload.replayed,
    workspace,
    conversation,
    initial_message: {
      id: initialMessage.id,
      workspace_id: initialMessage.workspace_id,
      sender_id: initialMessage.sender_id,
      sender_type: initialMessage.sender_type,
      content: initialMessage.content,
      mentions: initialMessage.mentions,
      parent_message_id: initialMessage.parent_message_id,
      metadata: initialMessage.metadata,
      created_at: initialMessage.created_at,
    },
    ...(payload.policy === undefined
      ? {}
      : { policy: normalizeWorkspaceAgentPolicy(payload.policy) }),
    ...(typeof payload.capability_version === 'string'
      ? { capability_version: payload.capability_version }
      : {}),
  };
}

function isAtomicTaskSessionCapability(payload: unknown): boolean {
  return (
    isRecord(payload) &&
    hasRequiredAndOptionalKeys(
      payload,
      TASK_SESSION_CAPABILITY_KEYS,
      TASK_SESSION_CAPABILITY_OPTIONAL_KEYS,
    ) &&
    payload.schema_version === 1 &&
    payload.atomic_creation === true &&
    payload.initial_conversation_mode === 'workspace' &&
    payload.initial_plan_mode === 'plan'
  );
}

function invalidTaskSessionResponse(payload: unknown): DesktopApiError {
  return new DesktopApiError('Invalid task session response', 502, payload);
}

function requireConversationCatalogPage(
  payload: unknown,
  expectedOffset: number,
  tenantId: string,
  projectId: string,
  workspaceId: string | null,
): {
  items: AgentConversation[];
  total: number;
  hasMore: boolean;
  nextOffset: number;
} {
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.items) ||
    !isUnsignedSafeInteger(payload.total) ||
    typeof payload.has_more !== 'boolean' ||
    payload.offset !== expectedOffset ||
    payload.limit !== HIERARCHY_CATALOG_PAGE_SIZE ||
    (payload.next_offset !== null && !isUnsignedSafeInteger(payload.next_offset))
  ) {
    throw invalidHierarchyCatalogResponse('conversation catalog', payload);
  }
  const expectedItemCount = Math.min(
    HIERARCHY_CATALOG_PAGE_SIZE,
    Math.max(payload.total - expectedOffset, 0),
  );
  const expectedNextOffset = Math.min(
    expectedOffset + HIERARCHY_CATALOG_PAGE_SIZE,
    payload.total,
  );
  const expectedHasMore = expectedNextOffset < payload.total;
  if (
    payload.items.length !== expectedItemCount ||
    payload.has_more !== expectedHasMore ||
    (expectedHasMore && payload.next_offset !== expectedNextOffset) ||
    (!expectedHasMore &&
      payload.next_offset !== null &&
      payload.next_offset !== expectedNextOffset)
  ) {
    throw invalidHierarchyCatalogResponse('conversation catalog', payload);
  }
  const items = payload.items.map((value) =>
    normalizeAgentConversation(value, tenantId, projectId, workspaceId),
  );
  if (items.some((item) => item === null)) {
    throw invalidHierarchyCatalogResponse('conversation catalog', payload);
  }
  return {
    items: items as AgentConversation[],
    total: payload.total,
    hasMore: payload.has_more,
    nextOffset: expectedNextOffset,
  };
}

function normalizeAgentConversation(
  value: unknown,
  tenantId: string,
  projectId: string,
  workspaceId: string | null,
): AgentConversation | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value.id) ||
    value.tenant_id !== tenantId ||
    value.project_id !== projectId ||
    (workspaceId !== null && value.workspace_id !== workspaceId) ||
    !isNonEmptyString(value.user_id) ||
    !isNonEmptyString(value.title) ||
    value.status !== 'active' ||
    !isUnsignedSafeInteger(value.message_count) ||
    !isNonEmptyString(value.created_at) ||
    !isOptionalNullableString(value.updated_at) ||
    !isOptionalNullableString(value.summary) ||
    !isOptionalNullableRecord(value.agent_config) ||
    !isOptionalNullableRecord(value.metadata) ||
    !isOptionalNullableString(value.conversation_mode) ||
    !isOptionalNullableString(value.current_mode) ||
    !isOptionalNullableString(value.workspace_id) ||
    !isOptionalNullableString(value.linked_workspace_task_id) ||
    !isOptionalNullableString(value.workspace_name) ||
    !isOptionalStringArray(value.participant_agents) ||
    !isOptionalNullableString(value.coordinator_agent_id) ||
    !isOptionalNullableString(value.focused_agent_id)
  ) {
    return null;
  }
  return {
    id: value.id,
    tenant_id: value.tenant_id,
    project_id: value.project_id,
    user_id: value.user_id,
    title: value.title,
    status: value.status,
    message_count: value.message_count,
    created_at: value.created_at,
    ...(value.updated_at === undefined ? {} : { updated_at: value.updated_at }),
    ...(value.summary === undefined ? {} : { summary: value.summary }),
    ...(value.agent_config === undefined ? {} : { agent_config: value.agent_config }),
    ...(value.metadata === undefined ? {} : { metadata: value.metadata }),
    ...(value.conversation_mode === undefined
      ? {}
      : { conversation_mode: value.conversation_mode }),
    ...(value.current_mode === undefined
      ? {}
      : { current_mode: value.current_mode as AgentConversation['current_mode'] }),
    ...(value.workspace_id === undefined ? {} : { workspace_id: value.workspace_id }),
    ...(value.linked_workspace_task_id === undefined
      ? {}
      : { linked_workspace_task_id: value.linked_workspace_task_id }),
    ...(value.workspace_name === undefined ? {} : { workspace_name: value.workspace_name }),
    ...(value.participant_agents === undefined
      ? {}
      : { participant_agents: value.participant_agents }),
    ...(value.coordinator_agent_id === undefined
      ? {}
      : { coordinator_agent_id: value.coordinator_agent_id }),
    ...(value.focused_agent_id === undefined
      ? {}
      : { focused_agent_id: value.focused_agent_id }),
  };
}

function invalidHierarchyCatalogResponse(label: string, payload: unknown): DesktopApiError {
  return new DesktopApiError(`Invalid ${label} response`, 502, payload);
}

function requireWorkspaceRosterPage<T>(
  payload: unknown,
  label: string,
  workspaceId: string,
  isItem: (value: unknown, workspaceId: string) => value is T,
): T[] {
  if (Array.isArray(payload) && payload.every((item) => isItem(item, workspaceId))) {
    return payload;
  }
  throw new DesktopApiError(`Invalid ${label} response`, 502, payload);
}

const DEVICE_CODE_VIEW_KEYS = new Set([
  'device_code',
  'user_code',
  'verification_uri',
  'verification_uri_complete',
  'expires_in',
  'interval',
]);

const DEVICE_TOKEN_VIEW_KEYS = new Set(['access_token', 'token_type']);
const DEVICE_USER_CODE_ALPHABET = new Set('ABCDEFGHJKLMNPQRSTUVWXYZ23456789');

function requireDeviceCodeView(payload: unknown): DeviceCodeView {
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, DEVICE_CODE_VIEW_KEYS) ||
    !isNonEmptyString(payload.device_code) ||
    !isDeviceUserCode(payload.user_code) ||
    payload.verification_uri !== '/device' ||
    !isNonEmptyString(payload.verification_uri_complete) ||
    !isIntegerInRange(payload.expires_in, 1, 600) ||
    !isIntegerInRange(payload.interval, 1, 60)
  ) {
    throw new DesktopApiError('Invalid device code response', 502, {
      detail: 'invalid_device_code_response',
    });
  }
  return {
    device_code: payload.device_code,
    user_code: payload.user_code,
    verification_uri: payload.verification_uri,
    verification_uri_complete: payload.verification_uri_complete,
    expires_in: payload.expires_in,
    interval: payload.interval,
  };
}

function requireDeviceTokenView(payload: unknown): DeviceTokenView {
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, DEVICE_TOKEN_VIEW_KEYS) ||
    !isNonEmptyString(payload.access_token) ||
    typeof payload.token_type !== 'string' ||
    payload.token_type.toLowerCase() !== 'bearer'
  ) {
    throw new DesktopApiError('Invalid device token response', 502, {
      detail: 'invalid_device_token_response',
    });
  }
  return {
    access_token: payload.access_token,
    token_type: 'bearer',
  };
}

function isWorkspaceMemberSummary(
  value: unknown,
  workspaceId: string,
): value is WorkspaceMemberSummary {
  if (!isRecord(value)) return false;
  return (
    isNonEmptyString(value.id) &&
    value.workspace_id === workspaceId &&
    isNonEmptyString(value.user_id) &&
    isNonEmptyString(value.role) &&
    isOptionalNullableString(value.user_email) &&
    isOptionalNullableString(value.invited_by) &&
    isOptionalString(value.created_at) &&
    isOptionalNullableString(value.updated_at)
  );
}

function isWorkspaceAgentBinding(
  value: unknown,
  workspaceId: string,
): value is WorkspaceAgentBinding {
  if (!isRecord(value)) return false;
  return (
    isNonEmptyString(value.id) &&
    value.workspace_id === workspaceId &&
    isNonEmptyString(value.agent_id) &&
    typeof value.is_active === 'boolean' &&
    isOptionalNullableString(value.display_name) &&
    isOptionalNullableString(value.description) &&
    isOptionalNullableRecord(value.config) &&
    isOptionalNullableInteger(value.hex_q) &&
    isOptionalNullableInteger(value.hex_r) &&
    isOptionalNullableString(value.theme_color) &&
    isOptionalNullableString(value.label) &&
    isOptionalNullableString(value.status) &&
    isOptionalString(value.created_at) &&
    isOptionalNullableString(value.updated_at)
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function hasExactKeys(record: Record<string, unknown>, expected: ReadonlySet<string>): boolean {
  const keys = Object.keys(record);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function hasRequiredAndOptionalKeys(
  record: Record<string, unknown>,
  required: ReadonlySet<string>,
  optional: ReadonlySet<string>,
): boolean {
  const keys = Object.keys(record);
  return (
    [...required].every((key) => Object.hasOwn(record, key)) &&
    keys.every((key) => required.has(key) || optional.has(key))
  );
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function isDeviceUserCode(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.length === 8 &&
    Array.from(value).every((character) => DEVICE_USER_CODE_ALPHABET.has(character))
  );
}

function isIntegerInRange(value: unknown, minimum: number, maximum: number): value is number {
  return (
    typeof value === 'number' &&
    Number.isSafeInteger(value) &&
    value >= minimum &&
    value <= maximum
  );
}

function isUnsignedSafeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

function isOptionalString(value: unknown): value is string | undefined {
  return value === undefined || typeof value === 'string';
}

function isOptionalBoolean(value: unknown): value is boolean | undefined {
  return value === undefined || typeof value === 'boolean';
}

function isOptionalStringArray(value: unknown): value is string[] | undefined {
  return (
    value === undefined ||
    (Array.isArray(value) && value.every((item) => typeof item === 'string'))
  );
}

function isOptionalNullableString(value: unknown): value is string | null | undefined {
  return value === undefined || value === null || typeof value === 'string';
}

function isOptionalNullableInteger(value: unknown): value is number | null | undefined {
  return value === undefined || value === null || Number.isInteger(value);
}

function isOptionalNullableRecord(
  value: unknown,
): value is Record<string, unknown> | null | undefined {
  return value === undefined || value === null || isRecord(value);
}

function unavailableWorkspaceAuthority<T>(): WorkspaceAuthorityCollection<T> {
  return { status: 'unavailable', items: [], error: null };
}

async function loadWorkspaceAuthority<T>(
  request: Promise<T[]>,
): Promise<WorkspaceAuthorityCollection<T>> {
  try {
    return { status: 'ready', items: await request, error: null };
  } catch (error) {
    return {
      status: 'error',
      items: [],
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

function requireValue(value: string, label: string): string {
  const trimmed = value.trim();
  if (!trimmed) throw new Error(`Missing ${label}`);
  return trimmed;
}

function providerCredentialRequestBody(input: {
  authMethod: LlmProviderAuthMethod;
  apiKey?: string;
  environmentVariable?: string;
}): Record<string, string> {
  if (input.authMethod === 'oauth') {
    throw new DesktopApiError(
      'OAuth provider authentication is not available',
      422,
      { auth_method: 'oauth' },
    );
  }
  if (input.authMethod === 'api_key') {
    const apiKey = input.apiKey?.trim();
    return {
      auth_method: 'api_key',
      ...(apiKey ? { api_key: apiKey } : {}),
    };
  }
  if (input.authMethod === 'environment') {
    const environmentVariable = input.environmentVariable?.trim();
    return {
      auth_method: 'environment',
      ...(environmentVariable ? { environment_variable: environmentVariable } : {}),
    };
  }
  if (input.authMethod === 'none') return { auth_method: 'none' };
  throw new DesktopApiError('Unsupported provider authentication method', 422, null);
}

function normalizeManagedLlmProvider(payload: unknown): ManagedLlmProvider {
  if (!isRecord(payload)) {
    throw new DesktopApiError('Invalid provider response', 502, payload);
  }
  const id = readCompatString(payload, 'id');
  const name = readCompatString(payload, 'name');
  const providerType = readCompatString(payload, 'provider_type', 'providerType');
  if (!id || !name || !providerType) {
    throw new DesktopApiError('Invalid provider response', 502, payload);
  }

  const authMethod = readProviderAuthMethod(
    readCompatString(payload, 'auth_method', 'authMethod').toLowerCase(),
  );
  const maskedCredential = readCompatString(payload, 'api_key_masked', 'apiKeyMasked');
  const credentialConfigured = readCompatBoolean(
    payload,
    'credential_configured',
    'credentialConfigured',
  );
  const revision = readCompatInteger(payload, 'revision', 'version') ?? 0;

  return {
    id,
    tenant_id: readCompatString(payload, 'tenant_id', 'tenantId') || undefined,
    name,
    provider_type: providerType,
    operation_type: readCompatString(payload, 'operation_type', 'operationType') || undefined,
    auth_method: authMethod,
    is_active: readCompatBoolean(payload, 'is_active', 'isActive'),
    is_enabled: readCompatBoolean(payload, 'is_enabled', 'isEnabled'),
    base_url: readCompatNullableString(payload, 'base_url', 'baseUrl'),
    llm_model: readCompatNullableString(payload, 'llm_model', 'llmModel'),
    llm_small_model: readCompatNullableString(payload, 'llm_small_model', 'llmSmallModel'),
    embedding_model: readCompatNullableString(payload, 'embedding_model', 'embeddingModel'),
    reranker_model: readCompatNullableString(payload, 'reranker_model', 'rerankerModel'),
    allowed_models: readCompatStringArray(payload, 'allowed_models', 'allowedModels'),
    secondary_models: readCompatStringArray(payload, 'secondary_models', 'secondaryModels'),
    health_status: readCompatNullableString(payload, 'health_status', 'healthStatus'),
    credential_source:
      readCompatString(payload, 'credential_source', 'credentialSource') || undefined,
    credential_configured: credentialConfigured,
    environment_variable:
      authMethod === 'environment'
        ? readCompatString(payload, 'environment_variable', 'environmentVariable') || null
        : null,
    api_key_masked: credentialConfigured && maskedCredential ? '••••••••••••' : null,
    health_last_check: readCompatNullableString(
      payload,
      'health_last_check',
      'healthLastCheck',
    ),
    response_time_ms: readCompatNullableNumber(payload, 'response_time_ms', 'responseTimeMs'),
    error_message: readCompatNullableString(payload, 'error_message', 'errorMessage'),
    revision,
    updated_at: readCompatNullableString(payload, 'updated_at', 'updatedAt'),
  };
}

function normalizeLlmProviderRoutingPolicy(payload: unknown): LlmProviderRoutingPolicy {
  if (!isRecord(payload) || !isRecord(payload.roles) || !Array.isArray(payload.fallbacks)) {
    throw new DesktopApiError('Invalid provider routing policy response', 502, payload);
  }
  const tenantId = readCompatString(payload, 'tenant_id', 'tenantId');
  const projectId = readCompatString(payload, 'project_id', 'projectId');
  const workspaceId = readCompatString(payload, 'workspace_id', 'workspaceId');
  const revision = readCompatInteger(payload, 'revision');
  const updatedAt = readCompatString(payload, 'updated_at', 'updatedAt');
  if (!tenantId || !projectId || !workspaceId || revision == null || revision < 0 || !updatedAt) {
    throw new DesktopApiError('Invalid provider routing policy response', 502, payload);
  }
  return {
    tenant_id: tenantId,
    project_id: projectId,
    workspace_id: workspaceId,
    revision,
    roles: {
      default: normalizeLlmRouteTarget(payload.roles.default, payload),
      fast: normalizeLlmRouteTarget(payload.roles.fast, payload),
      coding: normalizeLlmRouteTarget(payload.roles.coding, payload),
      vision: normalizeLlmRouteTarget(payload.roles.vision, payload),
    },
    fallbacks: payload.fallbacks.map((target) => {
      const normalized = normalizeLlmRouteTarget(target, payload);
      if (!normalized) {
        throw new DesktopApiError('Invalid provider routing policy response', 502, payload);
      }
      return normalized;
    }),
    updated_at: updatedAt,
  };
}

function normalizeWorkspaceAgentPolicy(payload: unknown): WorkspaceAgentPolicy {
  const routing = normalizeLlmProviderRoutingPolicy(payload);
  if (!isRecord(payload)) {
    throw new DesktopApiError('Invalid workspace agent policy response', 502, payload);
  }
  const reasoningEffort = payload.reasoning_effort;
  const permissionMode = payload.permission_mode;
  const capabilityVersion = payload.capability_version;
  if (
    (reasoningEffort !== 'low' && reasoningEffort !== 'medium' && reasoningEffort !== 'high') ||
    (permissionMode !== 'ask' &&
      permissionMode !== 'automatic' &&
      permissionMode !== 'full_access') ||
    typeof capabilityVersion !== 'string' ||
    !capabilityVersion.trim()
  ) {
    throw new DesktopApiError('Invalid workspace agent policy response', 502, payload);
  }
  return {
    ...routing,
    reasoning_effort: reasoningEffort,
    permission_mode: permissionMode,
    capability_version: capabilityVersion,
  };
}

function normalizeWorkspaceToolGrant(payload: unknown): WorkspaceToolGrant {
  if (!isRecord(payload)) {
    throw new DesktopApiError('Invalid workspace tool grant response', 502, payload);
  }
  const id = readCompatString(payload, 'id');
  const workspaceId = readCompatString(payload, 'workspace_id', 'workspaceId');
  const canonicalToolName = readCompatString(
    payload,
    'canonical_tool_name',
    'canonicalToolName',
  );
  const sourceHitlRequestId = readCompatString(
    payload,
    'source_hitl_request_id',
    'sourceHitlRequestId',
  );
  const revision = readCompatInteger(payload, 'revision');
  const createdAt = readCompatString(payload, 'created_at', 'createdAt');
  if (
    !id ||
    !workspaceId ||
    !canonicalToolName ||
    !sourceHitlRequestId ||
    revision == null ||
    revision < 1 ||
    !createdAt
  ) {
    throw new DesktopApiError('Invalid workspace tool grant response', 502, payload);
  }
  return {
    id,
    workspace_id: workspaceId,
    canonical_tool_name: canonicalToolName,
    source_hitl_request_id: sourceHitlRequestId,
    revision,
    created_at: createdAt,
    ...(readCompatString(payload, 'created_by', 'createdBy')
      ? { created_by: readCompatString(payload, 'created_by', 'createdBy')! }
      : {}),
    ...(readCompatString(payload, 'granted_by', 'grantedBy')
      ? { granted_by: readCompatString(payload, 'granted_by', 'grantedBy')! }
      : {}),
    revoked_by: readCompatString(payload, 'revoked_by', 'revokedBy') || null,
    revoked_at: readCompatString(payload, 'revoked_at', 'revokedAt') || null,
  };
}

function normalizeLlmRouteTarget(
  value: unknown,
  payload: unknown,
): LlmProviderRoutingPolicy['roles']['default'] {
  if (value === null) return null;
  if (!isRecord(value)) {
    throw new DesktopApiError('Invalid provider routing policy response', 502, payload);
  }
  const providerId = readCompatString(value, 'provider_id', 'providerId');
  const modelId = readCompatString(value, 'model_id', 'modelId');
  if (!providerId || !modelId) {
    throw new DesktopApiError('Invalid provider routing policy response', 502, payload);
  }
  return { provider_id: providerId, model_id: modelId };
}

function normalizeProviderValidationOutcome(
  payload: unknown,
  fallbackProviderType = '',
): LlmProviderValidationOutcome {
  if (!isRecord(payload)) {
    throw new DesktopApiError('Invalid provider validation response', 502, payload);
  }
  const status = readCompatString(payload, 'status');
  if (!status || typeof payload.probed !== 'boolean') {
    throw new DesktopApiError('Invalid provider validation response', 502, payload);
  }
  const provider =
    payload.provider == null ? null : normalizeManagedLlmProvider(payload.provider);
  const providerType = provider?.provider_type || fallbackProviderType;
  return {
    provider,
    status,
    probed: payload.probed,
    detail: readCompatNullableString(payload, 'detail'),
    lastChecked: readCompatNullableString(payload, 'last_check', 'lastChecked'),
    responseTimeMs: readCompatNullableNumber(payload, 'response_time_ms', 'responseTimeMs'),
    errorMessage: readCompatNullableString(payload, 'error_message', 'errorMessage'),
    catalog:
      payload.catalog == null
        ? null
        : normalizeProviderCatalog(payload.catalog, providerType, provider?.id ?? ''),
  };
}

function readCompatString(
  record: Record<string, unknown>,
  snakeCaseKey: string,
  camelCaseKey?: string,
): string {
  const value = record[snakeCaseKey] ?? (camelCaseKey ? record[camelCaseKey] : undefined);
  return typeof value === 'string' ? value.trim() : '';
}

function readProviderAuthMethod(value: string): LlmProviderAuthMethod | undefined {
  return value === 'api_key' ||
    value === 'oauth' ||
    value === 'environment' ||
    value === 'none'
    ? value
    : undefined;
}

function readCompatBoolean(
  record: Record<string, unknown>,
  snakeCaseKey: string,
  camelCaseKey?: string,
): boolean | undefined {
  const value = record[snakeCaseKey] ?? (camelCaseKey ? record[camelCaseKey] : undefined);
  return typeof value === 'boolean' ? value : undefined;
}

function readCompatInteger(
  record: Record<string, unknown>,
  snakeCaseKey: string,
  camelCaseKey?: string,
): number | undefined {
  const value = record[snakeCaseKey] ?? (camelCaseKey ? record[camelCaseKey] : undefined);
  return Number.isInteger(value) && typeof value === 'number' ? value : undefined;
}

function readCompatStringArray(
  record: Record<string, unknown>,
  snakeCaseKey: string,
  camelCaseKey?: string,
): string[] | null {
  const value = record[snakeCaseKey] ?? (camelCaseKey ? record[camelCaseKey] : undefined);
  if (!Array.isArray(value)) return null;
  return value
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter(Boolean);
}

function readCompatNullableString(
  record: Record<string, unknown>,
  snakeCaseKey: string,
  camelCaseKey?: string,
): string | null {
  const value = record[snakeCaseKey] ?? (camelCaseKey ? record[camelCaseKey] : undefined);
  return typeof value === 'string' ? value : null;
}

function readCompatNullableNumber(
  record: Record<string, unknown>,
  snakeCaseKey: string,
  camelCaseKey?: string,
): number | null {
  const value = record[snakeCaseKey] ?? (camelCaseKey ? record[camelCaseKey] : undefined);
  return typeof value === 'number' ? value : null;
}

function normalizeProviderTypeDescriptors(
  payload: unknown,
  source: LlmProviderTypeDescriptor['source'],
): LlmProviderTypeDescriptor[] {
  const descriptors: LlmProviderTypeDescriptor[] = [];
  const seen = new Set<string>();
  for (const value of readArray<unknown>(payload, ['types', 'items', 'data'])) {
    const providerType =
      typeof value === 'string'
        ? value.trim()
        : value && typeof value === 'object' && !Array.isArray(value)
          ? readTrimmedString(value as Record<string, unknown>, 'provider_type')
          : '';
    if (!providerType || seen.has(providerType)) continue;
    const authMethods =
      value && typeof value === 'object' && !Array.isArray(value)
        ? readProviderAuthMethods((value as Record<string, unknown>).auth_methods)
        : [];
    const explicitlyUnavailableAuthMethods =
      value && typeof value === 'object' && !Array.isArray(value)
        ? readProviderAuthMethods(
            (value as Record<string, unknown>).unavailable_auth_methods,
          )
        : [];
    const unavailableAuthMethods = Array.from(
      new Set<LlmProviderAuthMethod>([
        ...explicitlyUnavailableAuthMethods,
        ...authMethods.filter((method) => method === 'oauth'),
      ]),
    );
    const explicitOperationType =
      value && typeof value === 'object' && !Array.isArray(value)
        ? readTrimmedString(value as Record<string, unknown>, 'operation_type')
        : '';
    const operationType = providerOperationType(providerType, explicitOperationType);
    const probeSupported =
      !value ||
      typeof value !== 'object' ||
      Array.isArray(value) ||
      (value as Record<string, unknown>).probe_supported !== false;
    seen.add(providerType);
    descriptors.push({
      providerType,
      authMethods,
      unavailableAuthMethods,
      operationType,
      probeSupported,
      source,
    });
  }
  return descriptors;
}

function providerOperationType(
  providerType: string,
  explicitOperationType: string,
): LlmProviderTypeDescriptor['operationType'] {
  if (explicitOperationType === 'embedding' || explicitOperationType === 'rerank') {
    return explicitOperationType;
  }
  if (providerType.endsWith('_embedding')) return 'embedding';
  if (providerType.endsWith('_reranker') || providerType.endsWith('_rerank')) return 'rerank';
  return 'llm';
}

function readProviderAuthMethods(value: unknown): LlmProviderAuthMethod[] {
  if (!Array.isArray(value)) return [];
  const methods: LlmProviderAuthMethod[] = [];
  for (const candidate of value) {
    const method =
      typeof candidate === 'string'
        ? readProviderAuthMethod(candidate.trim().toLowerCase())
        : undefined;
    if (method && !methods.includes(method)) methods.push(method);
  }
  return methods;
}

function readTrimmedString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  return typeof value === 'string' ? value.trim() : '';
}

function unavailableProviderCatalog(
  providerType: string,
  providerId = '',
  detail: string | null = null,
): LlmProviderModelCatalog {
  return {
    providerType,
    providerId: providerId || null,
    availability: 'unavailable',
    source: null,
    discoveredAt: null,
    detail,
    models: [],
  };
}

function normalizeProviderCatalog(
  payload: unknown,
  fallbackProviderType: string,
  fallbackProviderId = '',
): LlmProviderModelCatalog {
  if (!payload || typeof payload !== 'object') {
    return unavailableProviderCatalog(fallbackProviderType, fallbackProviderId);
  }
  const record = payload as Record<string, unknown>;
  const providerType = readCompatString(record, 'provider_type', 'providerType') || fallbackProviderType;
  const providerId =
    readCompatString(record, 'provider_id', 'providerId') || fallbackProviderId || null;
  const detail = readCompatNullableString(record, 'detail');
  const availability = readCompatString(record, 'availability');
  if (!record.models || typeof record.models !== 'object' || Array.isArray(record.models)) {
    return unavailableProviderCatalog(providerType, providerId ?? '', detail);
  }
  const categorized = record.models as Record<string, unknown>;
  const models: LlmProviderModelCatalog['models'] = [];
  for (const capability of ['chat', 'embedding', 'rerank'] as const) {
    const candidates = categorized[capability];
    if (!Array.isArray(candidates)) continue;
    const seen = new Set<string>();
    for (const candidate of candidates) {
      if (typeof candidate !== 'string') continue;
      const id = candidate.trim();
      if (!id || seen.has(id)) continue;
      seen.add(id);
      models.push({ id, capability });
    }
  }
  const source = typeof record.source === 'string' ? record.source.trim() || null : null;
  const discoveredAt = readCompatNullableString(record, 'discovered_at', 'discoveredAt');
  if (availability === 'unavailable') {
    return {
      providerType,
      providerId,
      availability: 'unavailable',
      source,
      discoveredAt,
      detail,
      models,
    };
  }
  if (models.length === 0 && source === null && availability !== 'available') {
    return unavailableProviderCatalog(providerType, providerId ?? '', detail);
  }
  return {
    providerType,
    providerId,
    availability: 'available',
    source,
    discoveredAt,
    detail,
    models,
  };
}

function unavailableProviderUsage(providerId: string): LlmProviderUsage {
  return {
    provider_id: providerId,
    tenant_id: null,
    availability: 'unavailable',
    statistics: [],
  };
}

function normalizeProviderUsage(payload: unknown, providerId: string): LlmProviderUsage {
  if (!payload || typeof payload !== 'object') return unavailableProviderUsage(providerId);
  const record = payload as Record<string, unknown>;
  if (
    typeof record.provider_id !== 'string' ||
    !Array.isArray(record.statistics) ||
    (record.tenant_id !== null && typeof record.tenant_id !== 'string')
  ) {
    return unavailableProviderUsage(providerId);
  }
  if (
    record.availability !== undefined &&
    record.availability !== 'available' &&
    record.availability !== 'unavailable'
  ) {
    return unavailableProviderUsage(providerId);
  }
  if (record.availability === 'unavailable') {
    return {
      provider_id: record.provider_id,
      tenant_id: record.tenant_id,
      availability: 'unavailable',
      statistics: [],
    };
  }
  const statistics = record.statistics.filter(isLlmProviderUsageStatistic);
  if (statistics.length !== record.statistics.length) return unavailableProviderUsage(providerId);
  return {
    provider_id: record.provider_id,
    tenant_id: record.tenant_id,
    availability: 'available',
    statistics,
  };
}

function isLlmProviderUsageStatistic(value: unknown): value is LlmProviderUsageStatistic {
  if (!value || typeof value !== 'object') return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.provider_id === 'string' &&
    (record.tenant_id === null || typeof record.tenant_id === 'string') &&
    (record.operation_type === null || typeof record.operation_type === 'string') &&
    typeof record.total_requests === 'number' &&
    typeof record.total_prompt_tokens === 'number' &&
    typeof record.total_completion_tokens === 'number' &&
    typeof record.total_tokens === 'number' &&
    (record.total_cost_usd === null || typeof record.total_cost_usd === 'number') &&
    (record.avg_response_time_ms === null || typeof record.avg_response_time_ms === 'number') &&
    (record.first_request_at === null || typeof record.first_request_at === 'string') &&
    (record.last_request_at === null || typeof record.last_request_at === 'string')
  );
}
