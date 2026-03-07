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
export interface TriggerPattern {
  pattern: string;
  weight: number;
  examples?: string[] | undefined;
}

/**
 * Skill response from API
 */
export interface SkillResponse {
  id: string;
  tenant_id: string;
  project_id: string | null;
  name: string;
  description: string;
  trigger_type: 'keyword' | 'semantic' | 'hybrid';
  trigger_patterns: TriggerPattern[];
  tools: string[];
  prompt_template: string | null;
  full_content: string | null;
  status: 'active' | 'disabled' | 'deprecated';
  scope: 'system' | 'tenant' | 'project';
  is_system_skill: boolean;
  success_rate: number;
  success_count: number;
  failure_count: number;
  usage_count: number;
  created_at: string;
  updated_at: string;
  metadata?: Record<string, unknown> | undefined;
  current_version: number;
  version_label: string | null;
}

/**
 * Skill create request
 */
export interface SkillCreate {
  name: string;
  description: string;
  trigger_type: 'keyword' | 'semantic' | 'hybrid';
  trigger_patterns: TriggerPattern[];
  tools: string[];
  prompt_template?: string | undefined;
  full_content?: string | undefined;
  project_id?: string | undefined;
  scope?: 'tenant' | 'project' | undefined;
  metadata?: Record<string, unknown> | undefined;
}

/**
 * Skill update request
 */
export interface SkillUpdate {
  name?: string | undefined;
  description?: string | undefined;
  trigger_type?: 'keyword' | 'semantic' | 'hybrid' | undefined;
  trigger_patterns?: TriggerPattern[] | undefined;
  tools?: string[] | undefined;
  prompt_template?: string | undefined;
  full_content?: string | undefined;
  status?: 'active' | 'disabled' | 'deprecated' | undefined;
  metadata?: Record<string, unknown> | undefined;
}

/**
 * Skill list response
 */
export interface SkillsListResponse {
  skills: SkillResponse[];
  total: number;
}

/**
 * Skill match response
 */
export interface SkillMatchResponse {
  skills: SkillResponse[];
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
