import type {
  AgentConversation,
  ConversationMessagesResponse,
  CurrentUser,
  DesktopRuntimeConfig,
  DesktopServiceResponse,
  LoginOutcome,
  PaginatedConversationsResponse,
  PlanSnapshot,
  ProjectSummary,
  ProjectSandbox,
  RuntimeDataset,
  TenantSummary,
  TerminalServiceResponse,
  WorkspaceMessage,
  WorkspaceSummary,
  WorkspaceTask,
} from '../types';

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
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
          use_case: 'conversation',
          collaboration_mode: 'multi_agent_shared',
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
  ): Promise<AgentConversation> {
    const requiredProjectId = requireValue(projectId, 'project id');
    return this.request<AgentConversation>('/api/v1/agent/conversations', {
      method: 'POST',
      body: {
        project_id: requiredProjectId,
        title,
        agent_config: {
          selected_agent_id: 'builtin:all-access',
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

  async startTerminal(): Promise<TerminalServiceResponse> {
    const projectId = requireValue(this.config.projectId, 'project id');
    return this.request<TerminalServiceResponse>(
      `/api/v1/projects/${encodeURIComponent(projectId)}/sandbox/terminal`,
      { method: 'POST' },
    );
  }

  async loadRuntime(signal?: AbortSignal): Promise<RuntimeDataset> {
    const [workspaces, messages, tasks, plan] = await Promise.all([
      this.listWorkspaces(signal),
      this.config.workspaceId ? this.listMessages(signal) : Promise.resolve([]),
      this.config.workspaceId ? this.listTasks(signal) : Promise.resolve([]),
      this.config.workspaceId
        ? this.getPlanSnapshot(signal).catch(() => null)
        : Promise.resolve(null),
    ]);
    const projectId = this.config.projectId.trim();
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
    };
  }

  desktopProxyUrl(): string {
    const projectId = requireValue(this.config.projectId, 'project id');
    return absoluteUrl(
      this.config.apiBaseUrl,
      `/api/v1/projects/${encodeURIComponent(projectId)}/sandbox/desktop/proxy/`,
    );
  }

  terminalProxyUrl(sessionId?: string | null): string {
    const projectId = requireValue(this.config.projectId, 'project id');
    const path = `/api/v1/projects/${encodeURIComponent(projectId)}/sandbox/terminal/proxy/ws${
      sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''
    }`;
    return websocketUrl(this.config.apiBaseUrl, path);
  }

  agentWsUrl(sessionId: string): string {
    const token = requireValue(this.config.apiKey, 'api key');
    return websocketUrl(
      this.config.apiBaseUrl,
      `/api/v1/agent/ws?token=${encodeURIComponent(token)}&session_id=${encodeURIComponent(
        sessionId,
      )}`,
    );
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
    if (!options.skipAuth && this.config.apiKey.trim()) {
      headers.set('Authorization', `Bearer ${this.config.apiKey.trim()}`);
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
