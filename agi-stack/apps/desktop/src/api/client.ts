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
  ApprovePlanAndStartRequest,
  ApprovePlanAndStartResponse,
  AutomationCapabilities,
  AutomationJob,
  AutomationJobListResponse,
  AutomationRunListResponse,
  ConversationMessagesResponse,
  ChangeSnapshot,
  CreateRunInputRequest,
  CurrentUser,
  DesktopRuntimeConfig,
  DesktopServiceResponse,
  ForkRecoveryOutcome,
  HitlResponseOutcome,
  HitlResponseSubmission,
  LoginOutcome,
  LlmProviderAuthMethod,
  LlmProviderCreateInput,
  LlmProviderModelCatalog,
  LlmProviderMutationInput,
  LlmProviderTypeDescriptor,
  LlmProviderUsage,
  LlmProviderUsageStatistic,
  LlmProviderValidationOutcome,
  ManagedAgentDefinition,
  ManagedLlmProvider,
  ManagedPlugin,
  ManagedSkill,
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
  WorkspaceSummary,
  WorkspaceTask,
} from '../types';

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  contentType?: string;
  signal?: AbortSignal;
  skipAuth?: boolean;
};

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

export function isLegacyWorkspaceContextRouteMissing(error: unknown): boolean {
  if (!(error instanceof DesktopApiError) || error.status !== 404) return false;
  if (typeof error.payload !== 'object' || error.payload === null) return false;
  return (error.payload as { detail?: unknown }).detail === 'Not Found';
}

export function isLegacyConversationSessionRouteMissing(error: unknown): boolean {
  if (!(error instanceof DesktopApiError) || error.status !== 404) return false;
  if (typeof error.payload !== 'object' || error.payload === null) return false;
  const detail = (error.payload as { detail?: unknown }).detail;
  return detail === 'Not Found' || detail === 'Not found';
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
    const payload = await this.request<unknown>('/api/v1/tenants', { signal });
    return readArray<TenantSummary>(payload, ['tenants', 'items', 'data']);
  }

  async listProjects(tenantId?: string, signal?: AbortSignal): Promise<ProjectSummary[]> {
    const params = new URLSearchParams();
    if (tenantId) params.set('tenant_id', tenantId);
    const query = params.toString();
    const payload = await this.request<unknown>(`/api/v1/projects${query ? `?${query}` : ''}`, {
      signal,
    });
    return readArray<ProjectSummary>(payload, ['projects', 'items', 'data']);
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
    const payload = await this.request<unknown>(
      `/api/v1/tenants/${encodeURIComponent(requiredTenantId)}/projects/${encodeURIComponent(
        requiredProjectId,
      )}/workspaces`,
      { signal },
    );
    return readArray<WorkspaceSummary>(payload, ['workspaces', 'items', 'data']);
  }

  async createWorkspace(name: string, description?: string): Promise<WorkspaceSummary> {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    const projectId = requireValue(this.config.projectId, 'project id');
    return this.createWorkspaceForProject(projectId, name, description, tenantId);
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

  async sendMessage(content: string, parentMessageId?: string): Promise<WorkspaceMessage> {
    const path = this.workspacePath('/messages');
    return this.request<WorkspaceMessage>(path, {
      method: 'POST',
      body: {
        content,
        sender_type: 'human',
        parent_message_id: parentMessageId || undefined,
        mentions: [],
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
    const requiredProjectId = requireValue(projectId, 'project id');
    const items: AgentConversation[] = [];
    let offset = 0;
    let total = 0;
    let hasMore = true;
    let nextOffset: number | null | undefined = null;

    while (hasMore) {
      const params = new URLSearchParams({
        project_id: requiredProjectId,
        status: 'active',
        limit: '100',
        offset: String(offset),
      });
      if (workspaceId) params.set('workspace_id', workspaceId);
      const page = await this.request<PaginatedConversationsResponse>(
        `/api/v1/agent/conversations?${params.toString()}`,
        { signal },
      );
      const pageItems = Array.isArray(page.items) ? page.items : [];
      items.push(...pageItems);
      total = typeof page.total === 'number' ? page.total : items.length;
      nextOffset =
        typeof page.next_offset === 'number' ? page.next_offset : offset + pageItems.length;
      hasMore = Boolean(page.has_more) && nextOffset > offset;
      offset = nextOffset ?? offset;
    }

    return {
      items,
      total,
      has_more: false,
      offset: 0,
      limit: Math.max(items.length, 100),
      next_offset: null,
    };
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
        },
      },
    );
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
    return this.request<ManagedLlmProvider[]>('/api/v1/llm-providers/?include_inactive=true', {
      signal,
    });
  }

  async createLlmProvider(input: LlmProviderCreateInput): Promise<ManagedLlmProvider> {
    const apiKey = input.apiKey?.trim();
    const commonBody = {
      name: input.name,
      provider_type: input.providerType,
      base_url: input.baseUrl,
      llm_model: input.primaryModel,
      allowed_models: input.allowedModels,
      is_active: input.active,
    };
    return this.request<ManagedLlmProvider>('/api/v1/llm-providers/', {
      method: 'POST',
      body:
        this.config.mode === 'local'
          ? {
              ...commonBody,
              auth_method: input.authMethod,
              ...(input.authMethod === 'api_key' && apiKey ? { api_key: apiKey } : {}),
            }
          : { ...commonBody, ...(apiKey ? { api_key: apiKey } : {}) },
    });
  }

  async listLlmProviderTypes(signal?: AbortSignal): Promise<LlmProviderTypeDescriptor[]> {
    const payload = await this.request<unknown>('/api/v1/llm-providers/types', { signal });
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
    if (this.config.mode === 'local') {
      return unavailableProviderCatalog(normalizedProviderType);
    }
    const payload = await this.request<unknown>(
      `/api/v1/llm-providers/models/${encodeURIComponent(normalizedProviderType)}`,
      { signal },
    );
    return normalizeProviderCatalog(payload, normalizedProviderType);
  }

  async getLlmProviderUsage(
    providerId: string,
    signal?: AbortSignal,
  ): Promise<LlmProviderUsage> {
    const normalizedProviderId = requireValue(providerId, 'provider id');
    if (this.config.mode === 'local') {
      return unavailableProviderUsage(normalizedProviderId);
    }
    const payload = await this.request<unknown>(
      `/api/v1/llm-providers/${encodeURIComponent(normalizedProviderId)}/usage`,
      { signal },
    );
    return normalizeProviderUsage(payload, normalizedProviderId);
  }

  async testLlmProviderDraft(
    input: LlmProviderCreateInput,
  ): Promise<LlmProviderValidationOutcome> {
    if (this.config.mode === 'local') {
      return validateLocalProviderDraft(input);
    }
    const apiKey = input.apiKey?.trim();
    const health = await this.request<{
      status: string;
      last_check?: string | null;
      response_time_ms?: number | null;
      error_message?: string | null;
    }>('/api/v1/llm-providers/test-connection', {
      method: 'POST',
      body: {
        name: input.name,
        provider_type: input.providerType,
        base_url: input.baseUrl,
        llm_model: input.primaryModel,
        allowed_models: input.allowedModels,
        is_active: input.active,
        ...(apiKey ? { api_key: apiKey } : {}),
      },
    });
    return {
      provider: null,
      status: health.status,
      probed: true,
      detail: null,
      lastChecked: health.last_check ?? null,
      responseTimeMs: health.response_time_ms ?? null,
      errorMessage: health.error_message ?? null,
    };
  }

  async updateLlmProvider(
    providerId: string,
    input: LlmProviderMutationInput,
  ): Promise<ManagedLlmProvider> {
    const commonBody = {
      name: input.name,
      provider_type: input.providerType,
      base_url: input.baseUrl,
      llm_model: input.primaryModel,
      allowed_models: input.allowedModels,
      is_active: input.active,
      ...(input.apiKey ? { api_key: input.apiKey } : {}),
    };
    const local = this.config.mode === 'local';
    return this.request<ManagedLlmProvider>(
      `/api/v1/llm-providers/${encodeURIComponent(providerId)}`,
      {
        method: local ? 'PATCH' : 'PUT',
        body: local
          ? {
              ...commonBody,
              auth_method: input.authMethod,
              expected_revision: input.expectedRevision,
            }
          : commonBody,
      },
    );
  }

  async checkLlmProvider(providerId: string): Promise<LlmProviderValidationOutcome> {
    const encodedProviderId = encodeURIComponent(providerId);
    if (this.config.mode === 'local') {
      return this.request<LlmProviderValidationOutcome>(
        `/api/v1/llm-providers/${encodedProviderId}/test`,
        { method: 'POST', body: {} },
      );
    }
    const health = await this.request<{
      status: string;
      last_check?: string | null;
      response_time_ms?: number | null;
      error_message?: string | null;
    }>(`/api/v1/llm-providers/${encodedProviderId}/health-check`, {
      method: 'POST',
      body: {},
    });
    return {
      provider: null,
      status: health.status,
      probed: true,
      detail: null,
      lastChecked: health.last_check ?? null,
      responseTimeMs: health.response_time_ms ?? null,
      errorMessage: health.error_message ?? null,
    };
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

  async listManagedPlugins(signal?: AbortSignal): Promise<ManagedPlugin[]> {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    const payload = await this.request<unknown>(
      `/api/v1/channels/tenants/${encodeURIComponent(tenantId)}/plugins`,
      { signal },
    );
    return readArray<ManagedPlugin>(payload, ['items', 'plugins', 'data']).map((plugin) => ({
      ...plugin,
      id: plugin.id ?? plugin.name,
    }));
  }

  async setManagedPluginEnabled(pluginId: string, enabled: boolean): Promise<unknown> {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    return this.request<unknown>(
      `/api/v1/channels/tenants/${encodeURIComponent(tenantId)}/plugins/${encodeURIComponent(
        pluginId,
      )}/${enabled ? 'enable' : 'disable'}`,
      { method: 'POST' },
    );
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

  async ensureSandbox(signal?: AbortSignal): Promise<ProjectSandbox> {
    const projectId = requireValue(this.config.projectId, 'project id');
    return this.request<ProjectSandbox>(
      `/api/v1/projects/${encodeURIComponent(projectId)}/sandbox`,
      {
        method: 'POST',
        body: { auto_create: true },
        signal,
      },
    );
  }

  async seedProxyAuthCookie(): Promise<void> {
    const projectId = requireValue(this.config.projectId, 'project id');
    await this.request<unknown>(
      `/api/v1/projects/${encodeURIComponent(projectId)}/sandbox/proxy-auth-cookie`,
      { method: 'POST' },
    );
  }

  async startDesktop(resolution = '1440x900'): Promise<DesktopServiceResponse> {
    const projectId = requireValue(this.config.projectId, 'project id');
    const path = `/api/v1/projects/${encodeURIComponent(
      projectId,
    )}/sandbox/desktop?resolution=${encodeURIComponent(resolution)}`;
    return this.request<DesktopServiceResponse>(path, { method: 'POST' });
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
    const [workspaces, messages, tasks, plan, myWorkResult] = await Promise.all([
      this.listWorkspaces(signal),
      this.config.workspaceId ? this.listMessages(signal) : Promise.resolve([]),
      this.config.workspaceId ? this.listTasks(signal) : Promise.resolve([]),
      this.config.workspaceId
        ? this.getPlanSnapshot(signal).catch(() => null)
        : Promise.resolve(null),
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
      sandbox: null,
      myWork: myWorkResult.items,
      myWorkError: myWorkResult.error,
    };
  }

  desktopProxyUrl(): string {
    const projectId = requireValue(this.config.projectId, 'project id');
    return absoluteUrl(
      this.config.apiBaseUrl,
      `/api/v1/projects/${encodeURIComponent(projectId)}/sandbox/desktop/proxy/`,
    );
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
    if (options.body !== undefined) {
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

    const body =
      options.body instanceof URLSearchParams
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

function requireValue(value: string, label: string): string {
  const trimmed = value.trim();
  if (!trimmed) throw new Error(`Missing ${label}`);
  return trimmed;
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
    seen.add(providerType);
    descriptors.push({ providerType, authMethods, source });
  }
  return descriptors;
}

function readProviderAuthMethods(value: unknown): LlmProviderAuthMethod[] {
  if (!Array.isArray(value)) return [];
  const methods: LlmProviderAuthMethod[] = [];
  for (const candidate of value) {
    if (
      (candidate === 'api_key' || candidate === 'none') &&
      !methods.includes(candidate)
    ) {
      methods.push(candidate);
    }
  }
  return methods;
}

function readTrimmedString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  return typeof value === 'string' ? value.trim() : '';
}

function unavailableProviderCatalog(providerType: string): LlmProviderModelCatalog {
  return {
    providerType,
    availability: 'unavailable',
    source: null,
    models: [],
  };
}

function normalizeProviderCatalog(
  payload: unknown,
  providerType: string,
): LlmProviderModelCatalog {
  if (!payload || typeof payload !== 'object') return unavailableProviderCatalog(providerType);
  const record = payload as Record<string, unknown>;
  if (!record.models || typeof record.models !== 'object' || Array.isArray(record.models)) {
    return unavailableProviderCatalog(providerType);
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
  return {
    providerType,
    availability: 'available',
    source: typeof record.source === 'string' ? record.source : null,
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

function validateLocalProviderDraft(
  input: LlmProviderCreateInput,
): LlmProviderValidationOutcome {
  const supportedProviderTypes = new Set(['openai', 'openai_compatible', 'anthropic']);
  if (!supportedProviderTypes.has(input.providerType.trim())) {
    return localDraftValidationFailure('unsupported_provider_type');
  }
  if (!input.name.trim() || !input.primaryModel.trim()) {
    return localDraftValidationFailure('missing_required_fields');
  }
  try {
    const url = new URL(input.baseUrl.trim());
    if (url.protocol !== 'http:' && url.protocol !== 'https:') {
      return localDraftValidationFailure('invalid_base_url');
    }
  } catch {
    return localDraftValidationFailure('invalid_base_url');
  }
  if (input.authMethod === 'api_key' && !input.apiKey?.trim()) {
    return localDraftValidationFailure('missing_api_key');
  }
  return {
    provider: null,
    status: 'configuration_valid',
    probed: false,
    detail: 'configuration_only',
  };
}

function localDraftValidationFailure(errorMessage: string): LlmProviderValidationOutcome {
  return {
    provider: null,
    status: 'configuration_invalid',
    probed: false,
    detail: 'configuration_only',
    errorMessage,
  };
}
