import type {
  AgentConversation,
  CurrentUser,
  DesktopRuntimeConfig,
  DesktopServiceResponse,
  LoginOutcome,
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
    const payload = await this.request<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/projects/${encodeURIComponent(
        projectId,
      )}/workspaces`,
      { signal },
    );
    return readArray<WorkspaceSummary>(payload, ['workspaces', 'items', 'data']);
  }

  async createWorkspace(name: string, description?: string): Promise<WorkspaceSummary> {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    const projectId = requireValue(this.config.projectId, 'project id');
    return this.request<WorkspaceSummary>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/projects/${encodeURIComponent(
        projectId,
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

  async createAgentConversation(title: string): Promise<AgentConversation> {
    const projectId = requireValue(this.config.projectId, 'project id');
    return this.request<AgentConversation>('/api/v1/agent/conversations', {
      method: 'POST',
      body: {
        project_id: projectId,
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
  ): Promise<AgentConversation> {
    const projectId = requireValue(this.config.projectId, 'project id');
    return this.request<AgentConversation>(
      `/api/v1/agent/conversations/${encodeURIComponent(
        conversationId,
      )}/mode?project_id=${encodeURIComponent(projectId)}`,
      {
        method: 'PATCH',
        body: payload,
      },
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
    return { workspaces, messages, tasks, plan, sandbox: null };
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
