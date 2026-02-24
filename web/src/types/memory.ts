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
  description?: string | undefined;
  owner_id: string;
  plan: 'free' | 'basic' | 'premium' | 'enterprise';
  max_projects: number;
  max_users: number;
  max_storage: number;
  created_at: string;
  updated_at?: string | undefined;
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
  description?: string | undefined;
  owner_id: string;
  member_ids: string[];
  memory_rules: MemoryRulesConfig;
  graph_config: GraphConfig;
  is_public: boolean;
  created_at: string;
  updated_at?: string | undefined;
  stats?: ProjectStats | undefined;
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
  updated_at?: string | undefined;
  task_id?: string | undefined; // Task ID for SSE progress tracking
}

export interface MemoryCreate {
  title: string;
  content: string;
  content_type?: string | undefined;
  project_id: string;
  tags?: string[] | undefined;
  entities?: Entity[] | undefined;
  relationships?: Relationship[] | undefined;
  collaborators?: string[] | undefined;
  is_public?: boolean | undefined;
  metadata?: Record<string, any> | undefined;
}

export interface MemoryUpdate {
  title?: string | undefined;
  content?: string | undefined;
  tags?: string[] | undefined;
  entities?: Entity[] | undefined;
  relationships?: Relationship[] | undefined;
  collaborators?: string[] | undefined;
  is_public?: boolean | undefined;
  metadata?: Record<string, any> | undefined;
  version: number; // Required for optimistic locking
}

export interface MemoryQuery {
  query: string;
  project_id?: string | undefined;
  tenant_id?: string | undefined;
  limit?: number | undefined;
  content_type?: string | undefined;
  tags?: string[] | undefined;
  author_id?: string | undefined;
  is_public?: boolean | undefined;
  created_after?: string | undefined;
  created_before?: string | undefined;
  include_entities?: boolean | undefined;
  include_relationships?: boolean | undefined;
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
  updated_at?: string | undefined;
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
  description?: string | undefined;
  plan?: string | undefined;
  max_projects?: number | undefined;
  max_users?: number | undefined;
  max_storage?: number | undefined;
}

export interface TenantUpdate {
  name?: string | undefined;
  description?: string | undefined;
  plan?: string | undefined;
  max_projects?: number | undefined;
  max_users?: number | undefined;
  max_storage?: number | undefined;
}

export interface TenantListResponse {
  tenants: Tenant[];
  total: number;
  page: number;
  page_size: number;
}

export interface ProjectCreate {
  name: string;
  description?: string | undefined;
  tenant_id: string;
  memory_rules?: MemoryRulesConfig | undefined;
  graph_config?: GraphConfig | undefined;
  is_public?: boolean | undefined;
}

export interface ProjectUpdate {
  name?: string | undefined;
  description?: string | undefined;
  memory_rules?: MemoryRulesConfig | undefined;
  graph_config?: GraphConfig | undefined;
  is_public?: boolean | undefined;
}

export interface ProjectListResponse {
  projects: Project[];
  total: number;
  page: number;
  page_size: number;
}

export interface UserProfile {
  job_title?: string | undefined;
  department?: string | undefined;
  bio?: string | undefined;
  phone?: string | undefined;
  location?: string | undefined;
  language?: string | undefined;
  timezone?: string | undefined;
  avatar_url?: string | undefined;
}

export interface UserUpdate {
  name?: string | undefined;
  profile?: UserProfile | undefined;
}

export interface User {
  id: string;
  email: string;
  name: string;
  roles: string[];
  is_active: boolean;
  created_at: string;
  tenant_id?: string | undefined; // Keep for compatibility if needed, but backend removed it from response? No, backend removed it.
  profile?: UserProfile | undefined;
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
  | 'minimax'
  | 'zai'
  | 'ollama'
  | 'lmstudio';
export type ProviderStatus = 'healthy' | 'degraded' | 'unhealthy';

export interface EmbeddingConfig {
  model?: string | undefined;
  dimensions?: number | undefined;
  encoding_format?: 'float' | 'base64' | undefined;
  user?: string | undefined;
  timeout?: number | undefined;
  provider_options?: Record<string, any> | undefined;
}

// Circuit breaker state enum
export type CircuitBreakerState = 'closed' | 'open' | 'half_open';

// Rate limiter statistics
export interface RateLimitStats {
  current_concurrent: number;
  max_concurrent: number;
  total_requests: number;
  requests_per_minute: number;
  max_rpm?: number | undefined;
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
  base_url?: string | undefined;
  llm_model: string;
  llm_small_model?: string | undefined;
  embedding_model?: string | undefined;
  embedding_config?: EmbeddingConfig | undefined;
  reranker_model?: string | undefined;
  config: Record<string, any>;
  is_active: boolean;
  is_default: boolean;
  api_key_masked: string;
  created_at: string;
  updated_at: string;
  health_status?: ProviderStatus | undefined;
  health_last_check?: string | undefined;
  response_time_ms?: number | undefined;
  error_message?: string | undefined;
  // Resilience status (circuit breaker + rate limiter)
  resilience?: ResilienceStatus | undefined;
}

export interface ProviderCreate {
  name: string;
  provider_type: ProviderType;
  api_key: string;
  base_url?: string | undefined;
  llm_model: string;
  llm_small_model?: string | undefined;
  embedding_model?: string | undefined;
  embedding_config?: EmbeddingConfig | undefined;
  reranker_model?: string | undefined;
  config?: Record<string, any> | undefined;
  is_active?: boolean | undefined;
  is_default?: boolean | undefined;
}

export interface ProviderUpdate {
  name?: string | undefined;
  provider_type?: ProviderType | undefined;
  api_key?: string | undefined;
  base_url?: string | undefined;
  llm_model?: string | undefined;
  llm_small_model?: string | undefined;
  embedding_model?: string | undefined;
  embedding_config?: EmbeddingConfig | undefined;
  reranker_model?: string | undefined;
  config?: Record<string, any> | undefined;
  is_active?: boolean | undefined;
  is_default?: boolean | undefined;
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
  tenant_id?: string | undefined;
  operation_type?: string | undefined;
  total_requests: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  total_cost_usd?: number | undefined;
  avg_response_time_ms?: number | undefined;
  first_request_at?: string | undefined;
  last_request_at?: string | undefined;
}

export interface TenantProviderMapping {
  id: string;
  tenant_id: string;
  provider_id: string;
  priority: number;
  operation_type: 'llm' | 'embedding' | 'rerank';
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
  display_name?: string | undefined;
  description?: string | undefined;
  properties?: Record<string, unknown> | undefined;
  project_id: string;
}

export interface SchemaEdgeType {
  id: string;
  name: string;
  display_name?: string | undefined;
  description?: string | undefined;
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
