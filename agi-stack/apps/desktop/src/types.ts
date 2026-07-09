export type RuntimeMode = 'local' | 'cloud';

export type ConnectionState = 'idle' | 'loading' | 'ready' | 'error';

export type BoardMode = 'flow' | 'list';

export type StatusTab = 'overview' | 'plan' | 'sandbox' | 'memory' | 'events';

export type AuthStatus = 'signed_out' | 'signing_in' | 'signed_in' | 'manual';

export type WorkbenchSection =
  | 'workspace'
  | 'chat'
  | 'board'
  | 'status'
  | 'sandbox'
  | 'memory'
  | 'terminal'
  | 'settings';

export type DesktopRuntimeConfig = {
  apiBaseUrl: string;
  apiKey: string;
  tenantId: string;
  projectId: string;
  workspaceId: string;
  mode: RuntimeMode;
};

export type LoginOutcome = {
  access_token: string;
  token_type: string;
  must_change_password: boolean;
};

export type CurrentUser = {
  user_id: string;
  email: string;
  name: string;
  roles: string[];
  is_active: boolean;
  created_at: string;
  profile: Record<string, unknown>;
  preferred_language?: string | null;
};

export type TenantSummary = {
  id: string;
  name: string;
  slug?: string;
  description?: string | null;
  owner_id?: string;
  plan?: string;
  created_at?: string;
  updated_at?: string | null;
};

export type ProjectSummary = {
  id: string;
  tenant_id: string;
  name: string;
  description?: string | null;
  owner_id?: string;
  member_ids?: string[];
  is_public?: boolean;
  agent_conversation_mode?: string;
  created_at?: string;
  updated_at?: string | null;
  stats?: Record<string, unknown> | null;
};

export type AuthState = {
  status: AuthStatus;
  user: CurrentUser | null;
  tenants: TenantSummary[];
  projects: ProjectSummary[];
  mustChangePassword: boolean;
  error: string | null;
};

export type WorkspaceSummary = {
  id: string;
  tenant_id?: string;
  project_id?: string;
  name?: string;
  title?: string;
  description?: string | null;
  status?: string;
  created_at?: string;
  updated_at?: string;
  metadata?: Record<string, unknown> | null;
};

export type WorkspaceMessage = {
  id: string;
  workspace_id?: string;
  parent_message_id?: string | null;
  sender_type?: string;
  sender_id?: string | null;
  content: string;
  mentions?: string[];
  created_at?: string;
  metadata?: Record<string, unknown> | null;
};

export type WorkspaceTask = {
  id: string;
  workspace_id?: string;
  title?: string;
  summary?: string | null;
  description?: string | null;
  status?: string;
  owner?: string | null;
  assignee_user_id?: string | null;
  priority?: string | number | null;
  progress?: number | null;
  created_at?: string;
  updated_at?: string;
  metadata?: Record<string, unknown> | null;
};

export type PlanSnapshot = Record<string, unknown>;

export type AgentConversation = {
  id: string;
  project_id: string;
  tenant_id: string;
  user_id: string;
  title: string;
  status: string;
  message_count: number;
  created_at: string;
  updated_at?: string | null;
  summary?: string | null;
  agent_config?: Record<string, unknown> | null;
  metadata?: Record<string, unknown> | null;
  conversation_mode?: string | null;
  workspace_id?: string | null;
  linked_workspace_task_id?: string | null;
  workspace_name?: string | null;
  participant_agents?: string[];
  coordinator_agent_id?: string | null;
  focused_agent_id?: string | null;
};

export type PaginatedConversationsResponse = {
  items: AgentConversation[];
  total: number;
  has_more: boolean;
  offset: number;
  limit: number;
  next_offset?: number | null;
};

export type AgentTimelineItem = {
  id: string;
  type: string;
  eventTimeUs: number;
  eventCounter: number;
  timestamp?: number | null;
  message_id?: string | null;
  role?: string;
  content?: string;
  toolName?: string;
  toolInput?: unknown;
  toolOutput?: unknown;
  display?: ToolDisplayData;
  fileMetadata?: ToolFileMetadata;
  isError?: boolean;
  requestId?: string;
  question?: string;
  answered?: boolean;
  artifactId?: string;
  filename?: string;
  error?: string;
  payload?: unknown;
  metadata?: Record<string, unknown> | null;
  [key: string]: unknown;
};

export type ToolDisplayData = {
  title?: string;
  summary?: string;
  status?: string;
  kind?: string;
  details?: unknown;
  metadata?: Record<string, unknown> | null;
  [key: string]: unknown;
};

export type ToolFileMetadata = {
  operation?: 'read' | 'write' | 'edit' | 'list' | 'search' | 'create' | 'delete' | string;
  paths?: ToolFilePathMetadata[];
  diffStat?: { filesChanged?: number; additions?: number; deletions?: number };
  matches?: Array<{ path?: string; lineNumber?: number; preview?: string }>;
  matchCount?: number;
  truncated?: boolean;
  workspaceRoot?: string;
  [key: string]: unknown;
};

export type ToolFilePathMetadata = {
  path?: string;
  relativePath?: string;
  language?: string;
  mimeType?: string;
  existsBefore?: boolean;
  existsAfter?: boolean;
  bytesRead?: number;
  bytesWritten?: number;
  lineStart?: number;
  lineEnd?: number;
  lineCount?: number;
  changed?: boolean;
  created?: boolean;
  deleted?: boolean;
  [key: string]: unknown;
};

export type ConversationMessagesResponse = {
  conversationId: string;
  timeline: AgentTimelineItem[];
  total: number;
  has_more: boolean;
  first_time_us?: number | null;
  first_counter?: number | null;
  last_time_us?: number | null;
  last_counter?: number | null;
};

export type ConversationTimelineState = {
  conversationId: string | null;
  items: AgentTimelineItem[];
  loading: boolean;
  loadingEarlier: boolean;
  error: string | null;
  hasMore: boolean;
  firstCursor: { timeUs: number; counter: number } | null;
  lastCursor: { timeUs: number; counter: number } | null;
};

export type ProjectSandbox = {
  sandbox_id: string;
  project_id: string;
  tenant_id?: string;
  status?: string;
  endpoint?: string | null;
  websocket_url?: string | null;
  desktop_port?: number | null;
  terminal_port?: number | null;
  desktop_url?: string | null;
  terminal_url?: string | null;
  is_healthy?: boolean;
  error_message?: string | null;
};

export type DesktopServiceResponse = {
  success: boolean;
  url?: string | null;
  display?: string;
  resolution?: string;
  port?: number;
  audio_enabled?: boolean;
  dynamic_resize?: boolean;
  encoding?: string;
};

export type TerminalServiceResponse = {
  success: boolean;
  url?: string | null;
  port?: number;
  session_id?: string | null;
};

export type AgentWsEvent = {
  type?: string;
  event_type?: string;
  workspace_id?: string;
  project_id?: string;
  sandbox_id?: string;
  payload?: unknown;
  [key: string]: unknown;
};

export type LocalMemoryRecord = {
  id?: string;
  project_id?: string;
  content?: string;
  score?: number;
  created_at?: string;
  [key: string]: unknown;
};

export type LocalMemoryResult = {
  label: string;
  data: unknown;
  usedFallback: boolean;
};

export type RuntimeNodeState = {
  loading: boolean;
  error: string | null;
};

export type RuntimeNodeLoadState = {
  projects: Record<string, RuntimeNodeState>;
  workspaces: Record<string, RuntimeNodeState>;
};

export type RuntimeDataset = {
  workspaces: WorkspaceSummary[];
  workspacesByProject: Record<string, WorkspaceSummary[]>;
  conversationsByWorkspace: Record<string, AgentConversation[]>;
  nodeState: RuntimeNodeLoadState;
  messages: WorkspaceMessage[];
  tasks: WorkspaceTask[];
  plan: PlanSnapshot | null;
  sandbox: ProjectSandbox | null;
};

export const LOCAL_DEV_SERVER_PRESETS = [
  {
    id: 'agistack-rust',
    label: 'agi-stack :8088',
    apiBaseUrl: 'http://127.0.0.1:8088',
  },
  {
    id: 'memstack-python',
    label: 'MemStack :8000',
    apiBaseUrl: 'http://127.0.0.1:8000',
  },
] as const;

export const DEFAULT_CONFIG: DesktopRuntimeConfig = {
  apiBaseUrl: LOCAL_DEV_SERVER_PRESETS[0].apiBaseUrl,
  apiKey: '',
  tenantId: 'default',
  projectId: '',
  workspaceId: '',
  mode: 'local',
};
