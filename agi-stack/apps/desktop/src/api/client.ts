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
  CreateTaskSessionRequest,
  CreateTaskSessionResponse,
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
  LlmProviderProbeInput,
  LlmProviderRoutingPolicy,
  LlmProviderRoutingPolicyMutationInput,
  LlmRoutingRole,
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
  WorkspaceAgentBinding,
  WorkspaceAuthorityCollection,
  WorkspaceMemberSummary,
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

const WORKSPACE_ROSTER_PAGE_SIZE = 500;

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

export function isWorkspaceContextUnavailableError(error: unknown): boolean {
  if (!(error instanceof DesktopApiError) || error.status !== 404) return false;
  if (!isRecord(error.payload)) return false;
  const detail = error.payload.detail;
  return isRecord(detail) && detail.code === 'workspace_context_unavailable';
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
    return this.request<CreateTaskSessionResponse>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/projects/${encodeURIComponent(
        projectId,
      )}/task-sessions`,
      {
        method: 'POST',
        body: input,
      },
    );
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
    try {
      // Schema validation proves the mutation route exists without creating a conversation or plan.
      await this.request<unknown>('/api/v1/agent/plan/mode', {
        method: 'POST',
        body: {},
        signal,
      });
      return true;
    } catch (error) {
      if (!(error instanceof DesktopApiError)) throw error;
      if (error.status === 422) return true;
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
    const apiKey = input.apiKey?.trim();
    const commonBody = {
      name: input.name,
      provider_type: input.providerType,
      base_url: input.baseUrl,
      llm_model: input.primaryModel,
      allowed_models: input.allowedModels,
      is_active: input.active,
    };
    const payload = await this.request<unknown>('/api/v1/llm-providers/', {
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
    const apiKey = input.apiKey?.trim();
    const payload = await this.request<unknown>('/api/v1/llm-providers/test-connection', {
      method: 'POST',
      body: {
        name: input.name,
        provider_type: input.providerType,
        base_url: input.baseUrl,
        is_active: input.active,
        ...(this.config.mode === 'local' ? { auth_method: input.authMethod } : {}),
        ...(apiKey ? { api_key: apiKey } : {}),
      },
    });
    return normalizeProviderValidationOutcome(payload, input.providerType);
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
      expected_revision: input.expectedRevision,
      ...(input.apiKey ? { api_key: input.apiKey } : {}),
    };
    const local = this.config.mode === 'local';
    const payload = await this.request<unknown>(
      `/api/v1/llm-providers/${encodeURIComponent(providerId)}`,
      {
        method: 'PUT',
        body: local
          ? {
              ...commonBody,
              auth_method: input.authMethod,
            }
          : commonBody,
      },
    );
    return normalizeManagedLlmProvider(payload);
  }

  async selectLlmRuntimeProvider(
    providerId: string,
    expectedRevision: number,
    expectedPolicyRevision: number,
  ): Promise<ManagedLlmProvider> {
    const normalizedProviderId = requireValue(providerId, 'provider id');
    const payload = await this.request<unknown>(
      `/api/v1/llm-providers/${encodeURIComponent(normalizedProviderId)}/runtime-selection`,
      {
        method: 'PUT',
        body: {
          expected_revision: expectedRevision,
          expected_policy_revision: expectedPolicyRevision,
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

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function isOptionalString(value: unknown): value is string | undefined {
  return value === undefined || typeof value === 'string';
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
  const runtimeSelected =
    readCompatBoolean(payload, 'runtime_selected', 'runtimeSelected') ?? false;
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
    runtime_selected: runtimeSelected,
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
  return value === 'api_key' || value === 'none' ? value : undefined;
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
    descriptors.push({ providerType, authMethods, operationType, probeSupported, source });
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
    if ((candidate === 'api_key' || candidate === 'none') && !methods.includes(candidate)) {
      methods.push(candidate);
    }
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
