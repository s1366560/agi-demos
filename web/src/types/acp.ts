export const ACP_SECRET_UNCHANGED_SENTINEL = '__MEMSTACK_SECRET_UNCHANGED__';

export type ACPTransport = 'stdio' | 'websocket';
export type ACPConfigValueType = 'env_ref' | 'secret';

export interface ACPConfigValue {
  type: ACPConfigValueType;
  value?: string | null | undefined;
  has_value?: boolean | undefined;
}

export interface TenantExternalACPAgent {
  id: string;
  agentKey: string;
  name: string;
  transport: ACPTransport;
  command?: string | null | undefined;
  args: string[];
  url?: string | null | undefined;
  env: Record<string, ACPConfigValue>;
  headers: Record<string, ACPConfigValue>;
  runnerPoolKey?: string | null | undefined;
  requiredLabels?: Record<string, string> | undefined;
  cwdPolicy?: Record<string, unknown> | undefined;
  enabled: boolean;
  source: string;
  available: boolean;
  missingEnv: string[];
  activeSessions: number;
  totalSessions: number;
  promptCount: number;
  updateCount: number;
  lastLatencyMs?: number | null | undefined;
  lastError?: string | null | undefined;
  lastActivity?: string | null | undefined;
  createdAt?: string | null | undefined;
  updatedAt?: string | null | undefined;
}

export interface ACPExternalSession {
  session_id: string;
  remote_session_id: string;
  agent_id: string;
  owner_user_id: string;
  tenant_id?: string | null | undefined;
  created_at: string;
  last_activity: string;
}

export interface ACPOperationEvent {
  tenant_id?: string | null | undefined;
  agent_id: string;
  action: string;
  status: 'success' | 'error';
  timestamp: string;
  duration_ms?: number | null | undefined;
  error?: string | null | undefined;
}

export interface TenantACPStatus {
  enabled: boolean;
  websocketEnabled: boolean;
  httpBaseUrl: string;
  externalAgentsConfigPath?: string | null | undefined;
  agentCount: number;
  availableCount: number;
  missingEnvCount: number;
  activeSessionCount: number;
  agents: TenantExternalACPAgent[];
  sessions: ACPExternalSession[];
  recentEvents: ACPOperationEvent[];
}

export interface UpsertTenantACPAgentRequest {
  agentKey?: string | undefined;
  name: string;
  transport: ACPTransport;
  command?: string | null | undefined;
  args?: string[] | undefined;
  url?: string | null | undefined;
  env?: Record<string, ACPConfigValue> | undefined;
  headers?: Record<string, ACPConfigValue> | undefined;
  runnerPoolKey?: string | null | undefined;
  requiredLabels?: Record<string, string> | undefined;
  cwdPolicy?: Record<string, unknown> | undefined;
  enabled?: boolean | undefined;
}

export type ACPRunnerPoolMode = 'kubernetes' | 'self_hosted';

export interface ACPRunnerPool {
  id: string;
  tenantId: string;
  clusterId: string;
  poolKey: string;
  name: string;
  mode: ACPRunnerPoolMode;
  enabled: boolean;
  labels: Record<string, string>;
  capacityPolicy: Record<string, unknown>;
  schedulingPolicy: Record<string, unknown>;
  runnerCount: number;
  readyRunnerCount: number;
  activeSessionCount: number;
  createdAt?: string | null | undefined;
  updatedAt?: string | null | undefined;
}

export interface ACPRunnerInstance {
  id: string;
  tenantId: string;
  poolId: string;
  runnerId: string;
  status: string;
  version?: string | null | undefined;
  capabilities: Record<string, unknown>;
  currentSessions: number;
  maxSessions: number;
  lastHeartbeatAt?: string | null | undefined;
  connectionId?: string | null | undefined;
  lastError?: string | null | undefined;
}

export interface UpsertACPRunnerPoolRequest {
  poolKey?: string | undefined;
  name: string;
  mode: ACPRunnerPoolMode;
  enabled: boolean;
  labels?: Record<string, string> | undefined;
  capacityPolicy?: Record<string, unknown> | undefined;
  schedulingPolicy?: Record<string, unknown> | undefined;
}

export interface ACPRunnerTokenResponse {
  token: string;
  expiresAt?: string | null | undefined;
  connectUrl: string;
  installCommand: string;
}

export interface TenantACPSessionRequest {
  cwd: string;
  additionalDirectories?: string[] | null | undefined;
  mcpServers?: Array<Record<string, unknown>> | undefined;
  projectId?: string | null | undefined;
  _meta?: Record<string, unknown> | null | undefined;
}

export interface ExternalACPSessionResult {
  session_id: string;
  remote_session_id: string;
}

export interface ExternalACPPromptResult {
  result?: Record<string, unknown> | null | undefined;
  updates: Array<Record<string, unknown>>;
}

export interface TenantACPTestRequest extends TenantACPSessionRequest {
  prompt: string;
  timeoutSeconds?: number | undefined;
}

export interface TenantACPTestResponse {
  success: boolean;
  sessionId?: string | null | undefined;
  remoteSessionId?: string | null | undefined;
  assistantText: string;
  updatesCount: number;
  durationMs: number;
  error?: string | null | undefined;
}
