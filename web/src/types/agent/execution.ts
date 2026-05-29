// ============================================
// SubAgent Types (L3 - Specialized Agent System)
// ============================================

/**
 * SubAgent trigger configuration
 */
export interface SubAgentTrigger {
  description: string;
  examples: string[];
  keywords: string[];
}

/**
 * Spawn policy configuration for SubAgent delegation control.
 * Governs when and how SubAgents may be spawned.
 */
export interface SpawnPolicyConfig {
  max_depth: number;
  max_active_runs: number;
  max_children_per_requester: number;
  allowed_subagents: string[] | null;
}

/**
 * Tool policy configuration for SubAgent tool access control.
 * DENY_FIRST: deny wins on conflict; unlisted tools are allowed.
 * ALLOW_FIRST: allow wins on conflict; unlisted tools are allowed unless in deny.
 */
export interface ToolPolicyConfig {
  allow: string[];
  deny: string[];
  precedence: 'allow_first' | 'deny_first';
}

/**
 * Agent identity configuration for nested agent spawning.
 * Defines the identity of a SubAgent when it spawns child agents.
 */
export interface AgentIdentityConfig {
  agent_id: string;
  name: string;
  description: string;
  system_prompt: string;
  model: string;
  allowed_tools: string[];
  allowed_skills: string[];
  spawn_policy: SpawnPolicyConfig | null;
  tool_policy: ToolPolicyConfig | null;
  metadata: Record<string, string>;
}

/**
 * SubAgent response from API
 */
export interface SubAgentResponse {
  id: string;
  tenant_id: string;
  project_id: string | null;
  name: string;
  display_name: string;
  system_prompt: string;
  trigger: SubAgentTrigger;
  model: string;
  color: string;
  allowed_tools: string[];
  allowed_skills: string[];
  allowed_mcp_servers: string[];
  max_tokens: number;
  temperature: number;
  max_iterations: number;
  enabled: boolean;
  total_invocations: number;
  avg_execution_time_ms: number;
  success_rate: number;
  created_at: string;
  updated_at: string;
  metadata?: Record<string, unknown> | undefined;
  source?: 'filesystem' | 'database' | undefined;
  file_path?: string | null | undefined;
  // Multi-agent policy fields
  spawn_policy?: SpawnPolicyConfig | null | undefined;
  tool_policy?: ToolPolicyConfig | null | undefined;
  identity?: AgentIdentityConfig | null | undefined;
  max_retries?: number | undefined;
  fallback_models?: string[] | undefined;
}

/**
 * SubAgent create request
 */
export interface SubAgentCreate {
  name: string;
  display_name: string;
  system_prompt: string;
  trigger_description: string;
  trigger_examples?: string[] | undefined;
  trigger_keywords?: string[] | undefined;
  model?: string | undefined;
  color?: string | undefined;
  allowed_tools?: string[] | undefined;
  allowed_skills?: string[] | undefined;
  allowed_mcp_servers?: string[] | undefined;
  max_tokens?: number | undefined;
  temperature?: number | undefined;
  max_iterations?: number | undefined;
  project_id?: string | undefined;
  metadata?: Record<string, unknown> | undefined;
  // Multi-agent policy fields
  spawn_policy?: SpawnPolicyConfig | undefined;
  tool_policy?: ToolPolicyConfig | undefined;
  identity?: Partial<AgentIdentityConfig> | undefined;
  max_retries?: number | undefined;
  fallback_models?: string[] | undefined;
}

/**
 * SubAgent update request
 */
export interface SubAgentUpdate {
  name?: string | undefined;
  display_name?: string | undefined;
  system_prompt?: string | undefined;
  trigger_description?: string | undefined;
  trigger_examples?: string[] | undefined;
  trigger_keywords?: string[] | undefined;
  model?: string | undefined;
  color?: string | undefined;
  allowed_tools?: string[] | undefined;
  allowed_skills?: string[] | undefined;
  allowed_mcp_servers?: string[] | undefined;
  max_tokens?: number | undefined;
  temperature?: number | undefined;
  max_iterations?: number | undefined;
  metadata?: Record<string, unknown> | undefined;
  // Multi-agent policy fields
  spawn_policy?: SpawnPolicyConfig | null | undefined;
  tool_policy?: ToolPolicyConfig | null | undefined;
  identity?: Partial<AgentIdentityConfig> | null | undefined;
  max_retries?: number | undefined;
  fallback_models?: string[] | undefined;
}

/**
 * SubAgent template for quick creation
 */
export interface SubAgentTemplate {
  name: string;
  display_name: string;
  description: string;
  category?: string | undefined;
}

/**
 * SubAgent templates list response
 */
export interface SubAgentTemplatesResponse {
  templates: SubAgentTemplate[];
}

/**
 * SubAgent list response
 */
export interface SubAgentsListResponse {
  subagents: SubAgentResponse[];
  total: number;
}

/**
 * SubAgent stats response
 */
export interface SubAgentStatsResponse {
  id: string;
  total_invocations: number;
  success_rate: number;
  avg_execution_time_ms: number;
  last_invoked_at: string | null;
}

/**
 * SubAgent match response
 */
export interface SubAgentMatchResponse {
  subagent: SubAgentResponse | null;
  confidence: number;
}

// ============================================
// Skill Types (L2 - Agent Skill System)
// ============================================

/**
 * Trigger pattern for skill matching
 */
/**
 * Skill response from API
 */
export interface SkillResponse {
  id: string;
  tenant_id: string;
  project_id: string | null;
  name: string;
  description: string;
  tools: string[];
  full_content: string | null;
  status: 'active' | 'disabled' | 'deprecated';
  scope: 'system' | 'tenant' | 'project';
  is_system_skill: boolean;
  source?: 'filesystem' | 'database' | 'hybrid' | 'plugin' | undefined;
  file_path?: string | null | undefined;
  created_at: string;
  updated_at: string;
  metadata?: Record<string, unknown> | undefined;
  agent_modes: string[];
  license?: string | null;
  compatibility?: string | null;
  allowed_tools_raw?: string | null;
  spec_version: string;
  current_version: number;
  version_label: string | null;
}

/**
 * Skill create request
 */
export interface SkillCreate {
  name: string;
  description: string;
  tools: string[];
  full_content?: string | undefined;
  project_id?: string | null | undefined;
  scope?: 'tenant' | 'project' | undefined;
  metadata?: Record<string, unknown> | undefined;
  license?: string | null | undefined;
  compatibility?: string | null | undefined;
  allowed_tools_raw?: string | null | undefined;
  spec_version?: string | null | undefined;
}

/**
 * Skill update request
 */
export interface SkillUpdate {
  name?: string | undefined;
  description?: string | undefined;
  tools?: string[] | undefined;
  full_content?: string | undefined;
  status?: 'active' | 'disabled' | 'deprecated' | undefined;
  metadata?: Record<string, unknown> | undefined;
  license?: string | null | undefined;
  compatibility?: string | null | undefined;
  allowed_tools_raw?: string | null | undefined;
  spec_version?: string | null | undefined;
}

/**
 * Skill list response
 */
export interface SkillsListResponse {
  skills: SkillResponse[];
  total: number;
}

/**
 * Skill content response
 */
export interface SkillContentResponse {
  skill_id: string;
  name: string;
  full_content: string | null;
  scope: 'system' | 'tenant' | 'project';
  is_system_skill: boolean;
}

export interface SkillVersionResponse {
  id: string;
  skill_id: string;
  version_number: number;
  version_label: string | null;
  change_summary: string | null;
  created_by: string;
  created_at: string;
}

export interface SkillVersionDetailResponse extends SkillVersionResponse {
  skill_md_content: string;
  resource_files: Record<string, unknown> | null;
}

export interface SkillVersionListResponse {
  versions: SkillVersionResponse[];
  total: number;
}

export interface SkillEvolutionJobResponse {
  id: string;
  skill_name: string;
  action: string;
  status: string;
  rationale: string | null;
  session_ids: string[];
  skill_version_id: string | null;
  created_at: string;
  applied_at: string | null;
}

export interface SkillEvolutionRouteEntry {
  kind: 'version' | 'evolution_job';
  id: string;
  label: string;
  status: string | null;
  action: string | null;
  version_number: number | null;
  version_label: string | null;
  skill_version_id: string | null;
  change_summary: string | null;
  rationale: string | null;
  created_by: string | null;
  created_at: string;
}

export interface SkillEvolutionTriggerResponse {
  capture_hook: string;
  capture_timing: string;
  scheduled_timing: string;
  manual_trigger: string;
  min_sessions_per_skill: number;
  min_avg_score: number;
  max_sessions_per_batch: number;
  publish_mode: string;
  auto_apply: boolean;
  enabled: boolean;
}

export interface SkillEvolutionDetailResponse {
  skill_id: string;
  skill_name: string;
  captured_session_count: number;
  jobs: SkillEvolutionJobResponse[];
  route: SkillEvolutionRouteEntry[];
  trigger: SkillEvolutionTriggerResponse;
}

export interface SkillEvolutionRunResponse {
  skill_id: string;
  skill_name: string;
  result: Record<string, unknown>;
}

export interface SkillPackagePayload {
  skill_md_content: string;
  resource_files?: Record<string, string> | undefined;
}

export interface SkillImportRequest extends SkillPackagePayload {
  scope?: 'tenant' | 'project' | undefined;
  project_id?: string | null | undefined;
  overwrite?: boolean | undefined;
  change_summary?: string | null | undefined;
}

export interface SkillZipImportRequest {
  scope?: 'tenant' | 'project' | undefined;
  project_id?: string | null | undefined;
  overwrite?: boolean | undefined;
  change_summary?: string | null | undefined;
}

export interface SkillLifecycleResponse {
  action: string;
  skill: SkillResponse;
  version_number: number | null;
  version_label: string | null;
}

export interface SkillPackageResponse extends SkillPackagePayload {
  format: string;
  skill: SkillResponse;
  version_number: number | null;
  version_label: string | null;
}

/**
 * Tenant skill config response
 */
export interface TenantSkillConfigResponse {
  id: string;
  tenant_id: string;
  system_skill_name: string;
  action: 'disable' | 'override';
  override_skill_id: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Tenant skill config list response
 */
export interface TenantSkillConfigListResponse {
  configs: TenantSkillConfigResponse[];
  total: number;
}

/**
 * Skill status for a system skill
 */
export interface SystemSkillStatus {
  system_skill_name: string;
  status: 'enabled' | 'disabled' | 'overridden';
  action: 'disable' | 'override' | null;
  override_skill_id: string | null;
}
