export type SpawnMode = 'run' | 'session';

export type AgentSource = 'filesystem' | 'database';

export type SpawnStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface AgentTrigger {
  keyword?: string[] | undefined;
  semantic?: string | undefined;
  mode?: 'keyword' | 'semantic' | 'hybrid' | undefined;
}

export interface WorkspaceConfig {
  type?: 'shared' | 'isolated' | 'inherited' | undefined;
  base_dir?: string | undefined;
}

export interface AgentBinding {
  id: string;
  tenant_id: string;
  agent_id: string;
  channel_type: string | null;
  channel_id: string | null;
  account_id: string | null;
  peer_id: string | null;
  priority: number;
  enabled: boolean;
  created_at: string;
  specificity_score: number;
}

export interface AgentDefinition {
  id: string;
  tenant_id: string;
  project_id: string | null;
  name: string;
  display_name: string | null;
  system_prompt: string | null;
  trigger: AgentTrigger | null;
  persona_files: string[];
  model: string | null;
  temperature: number | null;
  max_tokens: number | null;
  max_iterations: number;
  allowed_tools: string[] | null;
  allowed_skills: string[] | null;
  allowed_mcp_servers: string[] | null;
  bindings: AgentBinding[];
  workspace_dir: string | null;
  workspace_config: WorkspaceConfig | null;
  can_spawn: boolean;
  max_spawn_depth: number;
  agent_to_agent_enabled: boolean;
  discoverable: boolean;
  source: AgentSource;
  enabled: boolean;
  max_retries: number;
  fallback_models: string[];
  total_invocations: number;
  avg_execution_time_ms: number | null;
  success_rate: number | null;
  created_at: string;
  updated_at: string | null;
  metadata: Record<string, unknown>;
}

export interface SpawnRecord {
  id: string;
  parent_agent_id: string;
  child_agent_id: string;
  child_session_id: string;
  project_id: string;
  mode: SpawnMode;
  task_summary: string | null;
  status: SpawnStatus;
  created_at: string;
}

export interface CreateBindingRequest {
  agent_id: string;
  channel_type?: string | undefined;
  channel_id?: string | undefined;
  account_id?: string | undefined;
  peer_id?: string | undefined;
  priority?: number | undefined;
}

export interface SetEnabledRequest {
  enabled: boolean;
}

export interface DeleteBindingResponse {
  deleted: boolean;
  id: string;
}

// ---------------------------------------------------------------------------
// Agent Definition CRUD request/response types
// ---------------------------------------------------------------------------

export interface CreateDefinitionRequest {
  name: string;
  display_name: string;
  system_prompt: string;
  project_id?: string | undefined;
  trigger_description?: string | undefined;
  trigger_examples?: string[] | undefined;
  trigger_keywords?: string[] | undefined;
  persona_files?: string[] | undefined;
  model?: string | undefined;
  temperature?: number | undefined;
  max_tokens?: number | undefined;
  max_iterations?: number | undefined;
  allowed_tools?: string[] | undefined;
  allowed_skills?: string[] | undefined;
  allowed_mcp_servers?: string[] | undefined;
  workspace_dir?: string | undefined;
  workspace_config?: WorkspaceConfig | undefined;
  can_spawn?: boolean | undefined;
  max_spawn_depth?: number | undefined;
  agent_to_agent_enabled?: boolean | undefined;
  discoverable?: boolean | undefined;
  max_retries?: number | undefined;
  fallback_models?: string[] | undefined;
  metadata?: Record<string, unknown> | undefined;
}

export interface UpdateDefinitionRequest {
  name?: string | undefined;
  display_name?: string | undefined;
  system_prompt?: string | undefined;
  project_id?: string | undefined;
  trigger_description?: string | undefined;
  trigger_examples?: string[] | undefined;
  trigger_keywords?: string[] | undefined;
  persona_files?: string[] | undefined;
  model?: string | undefined;
  temperature?: number | undefined;
  max_tokens?: number | undefined;
  max_iterations?: number | undefined;
  allowed_tools?: string[] | undefined;
  allowed_skills?: string[] | undefined;
  allowed_mcp_servers?: string[] | undefined;
  workspace_dir?: string | undefined;
  workspace_config?: WorkspaceConfig | undefined;
  can_spawn?: boolean | undefined;
  max_spawn_depth?: number | undefined;
  agent_to_agent_enabled?: boolean | undefined;
  discoverable?: boolean | undefined;
  max_retries?: number | undefined;
  fallback_models?: string[] | undefined;
  metadata?: Record<string, unknown> | undefined;
}

export interface DeleteDefinitionResponse {
  deleted: boolean;
  id: string;
}

export interface AgentNode {
  agentId: string;
  name: string | null;
  parentAgentId: string | null;
  sessionId: string | null;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'stopped';
  taskSummary: string | null;
  result: string | null;
  success: boolean | null;
  artifacts: string[];
  children: string[];
  createdAt: number;
  lastUpdateAt: number;
}
