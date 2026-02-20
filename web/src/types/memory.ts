export interface MemoryRulesConfig {
  max_episodes: number;
  retention_days: number;
  auto_refresh: boolean;
  refresh_interval: number;
}

export interface GraphConfig {
  max_nodes: number;
  max_edges: number;
  similarity_threshold: number;
  community_detection: boolean;
}

export type ProcessingStatus = 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED';
export type DataStatus = 'ENABLED' | 'DISABLED';

export interface Entity {
  id: string;
  name: string;
  type: string;
  properties: Record<string, any>;
  confidence: number;
}

export interface Relationship {
  id: string;
  source_id: string;
  target_id: string;
  type: string;
  properties: Record<string, any>;
  confidence: number;
}

export interface GraphData {
  entities: Entity[];
  relationships: Relationship[];
}

export interface Tenant {
  id: string;
  name: string;
  description?: string;
  owner_id: string;
  plan: 'free' | 'basic' | 'premium' | 'enterprise';
  max_projects: number;
  max_users: number;
  max_storage: number;
  created_at: string;
  updated_at?: string;
}

export interface ProjectStats {
  memory_count: number;
  storage_used: number;
  node_count: number;
  member_count: number;
  last_active: string | null;
}

export interface Project {
  id: string;
  tenant_id: string;
  name: string;
  description?: string;
  owner_id: string;
  member_ids: string[];
  memory_rules: MemoryRulesConfig;
  graph_config: GraphConfig;
  is_public: boolean;
  created_at: string;
  updated_at?: string;
  stats?: ProjectStats;
}

export interface Memory {
  id: string;
  project_id: string;
  title: string;
  content: string;
  content_type: 'text' | 'document' | 'image' | 'video';
  tags: string[];
  entities: Entity[];
  relationships: Relationship[];
  version: number;
  author_id: string;
  collaborators: string[];
  is_public: boolean;
  status: DataStatus;
  processing_status: ProcessingStatus;
  metadata: Record<string, any>;
  created_at: string;
  updated_at?: string;
  task_id?: string; // Task ID for SSE progress tracking
}

export interface MemoryCreate {
  title: string;
  content: string;
  content_type?: string;
  project_id: string;
  tags?: string[];
  entities?: Entity[];
  relationships?: Relationship[];
  collaborators?: string[];
  is_public?: boolean;
  metadata?: Record<string, any>;
}

export interface MemoryUpdate {
  title?: string;
  content?: string;
  tags?: string[];
  entities?: Entity[];
  relationships?: Relationship[];
  collaborators?: string[];
  is_public?: boolean;
  metadata?: Record<string, any>;
  version: number; // Required for optimistic locking
}

export interface MemoryQuery {
  query: string;
  project_id?: string;
  tenant_id?: string;
  limit?: number;
  content_type?: string;
  tags?: string[];
  author_id?: string;
  is_public?: boolean;
  created_after?: string;
  created_before?: string;
  include_entities?: boolean;
  include_relationships?: boolean;
}

export interface MemoryItem {
  id: string;
  title: string;
  content: string;
  content_type: string;
  project_id: string;
  tags: string[];
  entities: Entity[];
  relationships: Relationship[];
  author_id: string;
  collaborators: string[];
  is_public: boolean;
  status: DataStatus;
  processing_status: ProcessingStatus;
  score: number;
  metadata: Record<string, any>;
  created_at: string;
  updated_at?: string;
}

export interface MemorySearchResponse {
  results: MemoryItem[];
  total: number;
  query: string;
  filters_applied: Record<string, any>;
  search_metadata: Record<string, any>;
}

export interface MemoryListResponse {
  memories: Memory[];
  total: number;
  page: number;
  page_size: number;
}

export interface TenantCreate {
  name: string;
  description?: string;
  plan?: string;
  max_projects?: number;
  max_users?: number;
  max_storage?: number;
}

export interface TenantUpdate {
  name?: string;
  description?: string;
  plan?: string;
  max_projects?: number;
  max_users?: number;
  max_storage?: number;
}

export interface TenantListResponse {
  tenants: Tenant[];
  total: number;
  page: number;
  page_size: number;
}

export interface ProjectCreate {
  name: string;
  description?: string;
  tenant_id: string;
  memory_rules?: MemoryRulesConfig;
  graph_config?: GraphConfig;
  is_public?: boolean;
}

export interface ProjectUpdate {
  name?: string;
  description?: string;
  memory_rules?: MemoryRulesConfig;
  graph_config?: GraphConfig;
  is_public?: boolean;
}

export interface ProjectListResponse {
  projects: Project[];
  total: number;
  page: number;
  page_size: number;
}

export interface UserProfile {
  job_title?: string;
  department?: string;
  bio?: string;
  phone?: string;
  location?: string;
  language?: string;
  timezone?: string;
  avatar_url?: string;
}

export interface UserUpdate {
  name?: string;
  profile?: UserProfile;
}

export interface User {
  id: string;
  email: string;
  name: string;
  roles: string[];
  is_active: boolean;
  created_at: string;
  tenant_id?: string; // Keep for compatibility if needed, but backend removed it from response? No, backend removed it.
  profile?: UserProfile;
}

export interface UserTenant {
  id: string;
  user_id: string;
  tenant_id: string;
  role: 'owner' | 'admin' | 'member' | 'guest';
  permissions: Record<string, unknown>;
  created_at: string;
}

export interface UserProject {
  id: string;
  user_id: string;
  project_id: string;
  role: 'owner' | 'admin' | 'member' | 'viewer';
  permissions: Record<string, unknown>;
  created_at: string;
}

// LLM Provider Types
export type ProviderType =
  | 'openai'
  | 'dashscope'
  | 'kimi'
  | 'gemini'
  | 'anthropic'
  | 'groq'
  | 'azure_openai'
  | 'cohere'
  | 'mistral'
  | 'bedrock'
  | 'vertex'
  | 'deepseek'
  | 'zai'
  | 'ollama'
  | 'lmstudio';
export type ProviderStatus = 'healthy' | 'degraded' | 'unhealthy';

export interface EmbeddingConfig {
  model?: string;
  dimensions?: number;
  encoding_format?: 'float' | 'base64';
  user?: string;
  timeout?: number;
  provider_options?: Record<string, any>;
}

// Circuit breaker state enum
export type CircuitBreakerState = 'closed' | 'open' | 'half_open';

// Rate limiter statistics
export interface RateLimitStats {
  current_concurrent: number;
  max_concurrent: number;
  total_requests: number;
  requests_per_minute: number;
  max_rpm?: number;
}

// Provider resilience status
export interface ResilienceStatus {
  circuit_breaker_state: CircuitBreakerState;
  failure_count: number;
  success_count: number;
  rate_limit: RateLimitStats;
  can_execute: boolean;
}

export interface ProviderConfig {
  id: string;
  name: string;
  provider_type: ProviderType;
  base_url?: string;
  llm_model: string;
  llm_small_model?: string;
  embedding_model?: string;
  embedding_config?: EmbeddingConfig;
  reranker_model?: string;
  config: Record<string, any>;
  is_active: boolean;
  is_default: boolean;
  api_key_masked: string;
  created_at: string;
  updated_at: string;
  health_status?: ProviderStatus;
  health_last_check?: string;
  response_time_ms?: number;
  error_message?: string;
  // Resilience status (circuit breaker + rate limiter)
  resilience?: ResilienceStatus;
}

export interface ProviderCreate {
  name: string;
  provider_type: ProviderType;
  api_key: string;
  base_url?: string;
  llm_model: string;
  llm_small_model?: string;
  embedding_model?: string;
  embedding_config?: EmbeddingConfig;
  reranker_model?: string;
  config?: Record<string, any>;
  is_active?: boolean;
  is_default?: boolean;
}

export interface ProviderUpdate {
  name?: string;
  provider_type?: ProviderType;
  api_key?: string;
  base_url?: string;
  llm_model?: string;
  llm_small_model?: string;
  embedding_model?: string;
  embedding_config?: EmbeddingConfig;
  reranker_model?: string;
  config?: Record<string, any>;
  is_active?: boolean;
  is_default?: boolean;
}

export interface ProviderListResponse {
  providers: ProviderConfig[];
  total: number;
}

// System-wide resilience status
export interface SystemResilienceStatus {
  providers: Record<
    string,
    {
      circuit_breaker: {
        state: CircuitBreakerState;
        failure_count: number;
        success_count: number;
        can_execute: boolean;
      };
      rate_limiter: RateLimitStats;
      health: {
        status: string;
      };
    }
  >;
  summary: {
    total_providers: number;
    healthy_count: number;
  };
}

export interface ProviderUsageStats {
  provider_id: string;
  tenant_id?: string;
  operation_type?: string;
  total_requests: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  total_cost_usd?: number;
  avg_response_time_ms?: number;
  first_request_at?: string;
  last_request_at?: string;
}

export interface TenantProviderMapping {
  id: string;
  tenant_id: string;
  provider_id: string;
  priority: number;
  created_at: string;
}

// Task API types (placeholders for types that may be defined elsewhere)
export interface TaskStats {
  total: number;
  pending: number;
  running: number;
  completed: number;
  failed: number;
}

export interface QueueDepth {
  depth: number;
  timestamp: string;
}

export interface RecentTask {
  id: string;
  task_type: string;
  status: string;
  created_at: string;
}

export interface StatusBreakdown {
  total: number;
  by_status: Record<string, number>;
}

// Schema API types (placeholders)
export interface SchemaEntityType {
  id: string;
  name: string;
  display_name?: string;
  description?: string;
  properties?: Record<string, unknown>;
  project_id: string;
}

export interface SchemaEdgeType {
  id: string;
  name: string;
  display_name?: string;
  description?: string;
  source_entity_type: string;
  target_entity_type: string;
  project_id: string;
}

export interface EdgeMapping {
  id: string;
  name: string;
  source_entity_type_id: string;
  target_entity_type_id: string;
  project_id: string;
}
