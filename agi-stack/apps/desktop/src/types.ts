export type RuntimeMode = 'local' | 'cloud';

export type ConnectionState = 'idle' | 'loading' | 'ready' | 'error';

export type BoardMode = 'flow' | 'list';

export type StatusTab = 'overview' | 'plan' | 'sandbox' | 'memory' | 'events';

export type AuthStatus = 'signed_out' | 'signing_in' | 'signed_in' | 'manual';

export type CredentialKind = 'cloud_session' | 'manual_api_key' | 'local_session';

export type WorkbenchSection =
  | 'workspace'
  | 'automations'
  | 'review'
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
  localApiToken: string;
  tenantId: string;
  projectId: string;
  workspaceId: string;
  mode: RuntimeMode;
  llmProvider: 'mock' | 'openai' | 'anthropic' | string;
  llmBaseUrl: string;
  llmModel: string;
  llmApiKey: string;
  workspaceRoot: string;
};

export type LocalRuntimeStatus = {
  running: boolean;
  api_base_url: string;
  api_token: string;
  workspace_root: string;
  tool_count: number;
  tools: string[];
  config: {
    provider: string;
    base_url: string;
    model: string;
    workspace_root: string;
  };
};

export function mergeLocalRuntimeStatus(
  config: DesktopRuntimeConfig,
  status: LocalRuntimeStatus,
): DesktopRuntimeConfig {
  return {
    ...config,
    apiBaseUrl: status.api_base_url || config.apiBaseUrl,
    localApiToken: status.api_token,
    tenantId: config.tenantId.trim() || 'local',
    projectId: config.projectId.trim() || 'local-project',
    workspaceRoot: config.workspaceRoot.trim() || status.workspace_root || config.workspaceRoot,
    llmProvider: config.llmProvider || status.config.provider || 'unconfigured',
    llmBaseUrl: config.llmBaseUrl || status.config.base_url || DEFAULT_CONFIG.llmBaseUrl,
    llmModel: config.llmModel || status.config.model || '',
    llmApiKey: config.llmApiKey,
  };
}

export type HitlType =
  | 'clarification'
  | 'decision'
  | 'env_var'
  | 'permission'
  | 'a2ui_action';

export type HitlResponseSubmission = {
  requestId: string;
  hitlType: HitlType;
  responseData: Record<string, unknown>;
  expectedRevision?: number;
  idempotencyKey?: string;
};

export type HitlResponseOutcome = {
  success?: boolean;
  status?: string;
  message?: string;
};

export type LoginOutcome = {
  access_token: string;
  token_type: string;
  must_change_password: boolean;
  session?: AuthSessionDescriptor;
  context?: WorkspaceContextSnapshot;
};

export type AuthSessionDescriptor = {
  session_id: string;
  auth_method: 'password' | 'workspace_sso' | 'api_key' | 'local' | string;
  expires_at: string | null;
  trusted_device: boolean;
};

export type WorkspaceContextSnapshot = {
  tenant_id: string;
  project_id: string;
  revision: number;
  updated_at: string;
};

export type WorkspaceContextResponse = {
  context: WorkspaceContextSnapshot;
  membership_role: string;
};

export type WorkspaceContextSwitchOutcome = {
  context: WorkspaceContextSnapshot;
  changed: boolean;
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
  credentialKind: CredentialKind | null;
  session: AuthSessionDescriptor | null;
  context: WorkspaceContextSnapshot | null;
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
  created_by?: string;
  description?: string | null;
  status?: string;
  is_archived?: boolean;
  office_status?: string;
  hex_layout_config?: Record<string, unknown> | null;
  created_at?: string;
  updated_at?: string | null;
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
  conversation_id?: string;
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
  plan_version_id?: string;
  plan_version?: number;
  plan_status?: 'draft' | 'approved';
  run_id?: string | null;
  run_status?: DesktopRunStatus | null;
  run_revision?: number | null;
  source?: 'agent_plan_task' | string;
  task?: Record<string, unknown>;
};

export type WorkspaceConversationExecution = {
  conversation_id: string;
  title?: string;
  capability_mode?: AgentCapabilityMode | string;
  current_mode?: AgentPlanMode | string;
  updated_at?: string;
  plan?: DesktopPlanVersion | null;
  run?: DesktopRun | null;
  pending_hitl?: Record<string, unknown>[];
  artifacts?: DesktopArtifactVersion[];
  delivery?: DesktopArtifactDelivery[];
};

export type PlanSnapshot = {
  workspace_id?: string;
  project_id?: string;
  conversation_id?: string;
  plan?: DesktopPlanVersion | Record<string, unknown> | null;
  conversation_plans?: WorkspaceConversationExecution[];
  plan_history?: Array<DesktopPlanVersion | Record<string, unknown>>;
  run_health?: DesktopRun[];
  pending_hitl?: Record<string, unknown>[];
  delivery?: DesktopArtifactDelivery[];
  artifact_index?: DesktopArtifactVersion[];
  [key: string]: unknown;
};

export type AgentPlanMode = 'plan' | 'build';
export type AgentCapabilityMode = 'work' | 'code';

export type AgentPlanModeResponse = {
  conversation_id: string;
  mode: AgentPlanMode;
  switched_at?: string;
};

export type AgentPlanTask = {
  id: string;
  conversation_id: string;
  content: string;
  status: string;
  priority: string;
  order_index: number;
  created_at: string;
  updated_at: string;
};

export type AgentPlanTaskListResponse = {
  conversation_id: string;
  tasks: AgentPlanTask[];
  total_count: number;
  plan_version?: DesktopPlanVersion | null;
};

export type DesktopPlanVersion = {
  id: string;
  conversation_id: string;
  version: number;
  status: 'draft' | 'approved';
  tasks: AgentPlanTask[];
  created_at: string;
  approved_at?: string | null;
};

export type DesktopRunStatus =
  | 'queued'
  | 'running'
  | 'needs_input'
  | 'needs_approval'
  | 'paused'
  | 'ready_review'
  | 'completed'
  | 'failed'
  | 'disconnected'
  | 'interrupted'
  | 'cancelled';

export type DesktopExecutionEnvironmentKind = 'local' | 'worktree';
export type DesktopPermissionProfile = 'read_only' | 'workspace_write' | 'full_access';

export type DesktopExecutionEnvironment = {
  id: string;
  kind: DesktopExecutionEnvironmentKind;
  label: string;
  workspace_path: string;
  repository_root?: string | null;
  branch?: string | null;
  base_commit?: string | null;
  source_run_id?: string | null;
  created_at: string;
};

export type DesktopRun = {
  id: string;
  conversation_id: string;
  project_id: string;
  plan_version_id: string;
  idempotency_key: string;
  message_id: string;
  request_message: string;
  status: DesktopRunStatus;
  revision: number;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  last_heartbeat_at?: string | null;
  error?: string | null;
  environment?: DesktopExecutionEnvironment | null;
  permission_profile?: 'read_only' | 'workspace_write' | 'full_access';
  authorization_snapshot: Record<string, unknown>;
};

export type ChangeSnapshotStatus = 'ready' | 'unattributed' | 'unavailable' | 'failed';
export type ChangeLineKind = 'context' | 'addition' | 'deletion';

export type ChangeLine = {
  kind: ChangeLineKind;
  old_line?: number | null;
  new_line?: number | null;
  text: string;
};

export type ChangeHunk = {
  header: string;
  old_start: number;
  new_start: number;
  lines: ChangeLine[];
};

export type ChangeFile = {
  path: string;
  old_path?: string | null;
  status: string;
  additions: number;
  deletions: number;
  binary: boolean;
  untracked: boolean;
  patch_digest: string;
  hunks: ChangeHunk[];
};

export type ChangeSnapshot = {
  id: string;
  run_id: string;
  conversation_id: string;
  run_revision: number;
  environment_id?: string | null;
  repository_root?: string | null;
  workspace_path?: string | null;
  branch?: string | null;
  base_revision?: string | null;
  head_revision?: string | null;
  status: ChangeSnapshotStatus;
  reason?: string | null;
  additions: number;
  deletions: number;
  files_changed: number;
  truncated: boolean;
  captured_at: string;
  files: ChangeFile[];
};

export type RunInputDelivery = 'steer_now' | 'queue_next';
export type RunInputStatus =
  | 'pending_boundary'
  | 'queued'
  | 'applied'
  | 'ready'
  | 'blocked'
  | 'promoted_to_plan';
export type ChangeReferenceSide = 'old' | 'new';

export type CodeRangeReference = {
  type: 'code_range';
  snapshot_id: string;
  environment_id: string;
  path: string;
  start_line: number;
  end_line: number;
  side: ChangeReferenceSide;
  patch_digest: string;
};

export type RunInputReference = CodeRangeReference;

export type CreateRunInputRequest = {
  expectedRunRevision: number;
  message: string;
  messageId: string;
  idempotencyKey: string;
  delivery: RunInputDelivery;
  references: RunInputReference[];
};

export type DesktopRunInput = {
  id: string;
  conversation_id: string;
  run_id: string;
  expected_run_revision: number;
  message_id: string;
  idempotency_key: string;
  delivery: RunInputDelivery;
  status: RunInputStatus;
  sequence: number;
  queue_position?: number | null;
  content: string;
  references: RunInputReference[];
  applied_round?: number | null;
  applied_at?: string | null;
  promotion_idempotency_key?: string | null;
  promoted_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type RunInputAck = {
  accepted: boolean;
  created: boolean;
  action: 'send_message';
  conversation_id: string;
  message_id: string;
  delivery_mode: RunInputDelivery;
  run_id: string;
  run_revision: number;
  queue_position?: number | null;
  input: DesktopRunInput;
};

export type PromoteRunInputResponse = {
  accepted: boolean;
  created: boolean;
  action: 'start_plan_turn';
  input: DesktopRunInput;
  conversation: AgentConversation;
  source_run: DesktopRun;
};

export type MyWorkGroup = 'needs_input' | 'needs_approval' | 'running' | 'ready_review';

export type ProjectWorkItem = {
  id: string;
  run_id: string;
  conversation_id: string;
  workspace_id?: string | null;
  project_id: string;
  title: string;
  capability_mode: AgentCapabilityMode;
  group: MyWorkGroup;
  status: DesktopRunStatus;
  required_action:
    | 'provide_input'
    | 'review_approval'
    | 'observe'
    | 'resume'
    | 'reattach'
    | 'inspect_failure'
    | 'review_result';
  revision: number;
  permission_profile: DesktopPermissionProfile;
  environment?: DesktopExecutionEnvironment | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
  last_heartbeat_at?: string | null;
};

export type ProjectMyWorkResponse = {
  project_id: string;
  items: ProjectWorkItem[];
  total: number;
};

export type DesktopToolInvocation = {
  invocation_id: string;
  grant_id?: string | null;
  run_id: string;
  plan_version_id: string;
  run_revision: number;
  environment_id: string;
  tool_name: string;
  target: unknown;
  effect: 'read' | 'mutate';
  input_digest: string;
  redacted_input: unknown;
  status: 'prepared' | 'executing' | 'completed' | 'failed' | 'unknown_outcome';
  prepared_at_ms: number;
  started_at_ms?: number | null;
  finished_at_ms?: number | null;
};

export type ApprovePlanAndStartRequest = {
  conversationId: string;
  projectId: string;
  planVersionId: string;
  expectedPlanVersion: number;
  permissionProfile: DesktopPermissionProfile;
  message: string;
  messageId: string;
  idempotencyKey: string;
  environmentKind: DesktopExecutionEnvironmentKind;
};

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
  current_mode?: AgentPlanMode | null;
  workspace_id?: string | null;
  linked_workspace_task_id?: string | null;
  workspace_name?: string | null;
  participant_agents?: string[];
  coordinator_agent_id?: string | null;
  focused_agent_id?: string | null;
};

export type ApprovePlanAndStartResponse = {
  queued: boolean;
  created: boolean;
  conversation: AgentConversation;
  plan_version: DesktopPlanVersion;
  run: DesktopRun;
};

export type RunControlOutcome = {
  accepted: boolean;
  status: string;
  run: DesktopRun;
};

export type ForkRecoveryOutcome = RunControlOutcome & {
  created: boolean;
  source_run: DesktopRun;
};

export type ReviewRunRequest = {
  action: 'approve' | 'request_changes';
  expectedRevision: number;
  feedback?: string;
};

export type ManagedLlmProvider = {
  id: string;
  name: string;
  provider_type: string;
  operation_type?: string;
  auth_method?: 'api_key' | 'none' | string;
  is_active?: boolean;
  is_enabled?: boolean;
  base_url?: string | null;
  llm_model?: string | null;
  llm_small_model?: string | null;
  embedding_model?: string | null;
  reranker_model?: string | null;
  allowed_models?: string[] | null;
  secondary_models?: string[] | null;
  health_status?: string | null;
  credential_configured?: boolean;
  runtime_selected?: boolean;
  api_key_masked?: string | null;
  health_last_check?: string | null;
  response_time_ms?: number | null;
  error_message?: string | null;
  revision?: number;
  updated_at?: string | null;
  [key: string]: unknown;
};

export type LlmProviderMutationInput = {
  name: string;
  providerType: string;
  authMethod: 'api_key' | 'none';
  baseUrl: string;
  primaryModel: string;
  allowedModels: string[];
  active: boolean;
  expectedRevision: number;
  apiKey?: string;
};

export type LlmProviderCreateInput = Omit<LlmProviderMutationInput, 'expectedRevision'>;

export type LlmProviderAuthMethod = 'api_key' | 'none';

export type LlmProviderTypeDescriptor = {
  providerType: string;
  authMethods: LlmProviderAuthMethod[];
  source: 'local_runtime' | 'cloud_api';
};

export type LlmProviderCatalogModel = {
  id: string;
  capability: 'chat' | 'embedding' | 'rerank';
};

export type LlmProviderModelCatalog = {
  providerType: string;
  availability: 'available' | 'unavailable';
  source: string | null;
  models: LlmProviderCatalogModel[];
};

export type LlmProviderUsageStatistic = {
  provider_id: string;
  tenant_id: string | null;
  operation_type: string | null;
  total_requests: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  total_cost_usd: number | null;
  avg_response_time_ms: number | null;
  first_request_at: string | null;
  last_request_at: string | null;
};

export type LlmProviderUsage = {
  provider_id: string;
  tenant_id: string | null;
  availability: 'available' | 'unavailable';
  statistics: LlmProviderUsageStatistic[];
};

export type LlmProviderValidationOutcome = {
  provider: ManagedLlmProvider | null;
  status: string;
  probed: boolean;
  detail: string | null;
  lastChecked?: string | null;
  responseTimeMs?: number | null;
  errorMessage?: string | null;
};

export type ManagedSkill = {
  id: string;
  name: string;
  description: string;
  status: string;
  scope: string;
  tools: string[];
  current_version?: number;
  is_system_skill?: boolean;
  updated_at?: string | null;
  [key: string]: unknown;
};

export type ManagedPlugin = {
  id: string;
  name: string;
  source: string;
  package?: string;
  version?: string;
  kind?: string;
  enabled: boolean;
  discovered: boolean;
  providers?: string[];
  skills?: string[];
  channel_types?: string[];
  tool_definitions?: Array<Record<string, unknown>>;
  [key: string]: unknown;
};

export type ManagedAgentDefinition = {
  id: string;
  name: string;
  display_name?: string | null;
  system_prompt?: string | null;
  enabled?: boolean;
  status?: string;
  model_name?: string | null;
  allowed_tools?: string[];
  allowed_skills?: string[];
  allowed_mcp_servers?: string[];
  updated_at?: string | null;
  [key: string]: unknown;
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
  options?: unknown[];
  allowCustom?: boolean;
  fields?: unknown[];
  action?: string;
  resource?: string;
  reason?: string;
  riskLevel?: string;
  description?: string;
  allowRemember?: boolean;
  answered?: boolean;
  artifactId?: string;
  filename?: string;
  error?: string;
  payload?: unknown;
  metadata?: Record<string, unknown> | null;
  [key: string]: unknown;
};

export type DecisionRiskLevel = 'low' | 'medium' | 'high';
export type DecisionReversibilityMode = 'reversible' | 'partial' | 'irreversible';

export type DecisionContext = {
  action: { name: string; label: string };
  target: {
    kind: string;
    id: string;
    version_id?: string | null;
    path?: string | null;
  };
  data: {
    summary: string;
    redacted_fields?: string[];
  };
  reason: string;
  risk: {
    level: DecisionRiskLevel;
    rationale: string;
  };
  reversibility: {
    mode: DecisionReversibilityMode;
    recovery?: string | null;
  };
  scope: {
    kind: string;
    ids: string[];
  };
  evidence: Array<{
    kind: string;
    id: string;
    label: string;
    uri?: string | null;
    digest?: string | null;
  }>;
};

export type DesktopApprovalRequest = {
  id: string;
  conversation_id: string;
  run_id?: string | null;
  run_revision?: number | null;
  round: number;
  kind: Extract<HitlType, 'decision' | 'permission'>;
  prompt: string;
  decision?: DecisionContext | null;
  status: 'pending' | 'responded';
  created_at: string;
  responded_at?: string | null;
  response_data?: Record<string, unknown> | null;
  response_actor?: string | null;
  response_revision?: number | null;
  idempotency_key?: string | null;
};

export type DesktopArtifactStatus =
  | 'draft'
  | 'ready'
  | 'approved'
  | 'delivered'
  | 'superseded';

export type DesktopArtifactVersion = {
  id: string;
  artifact_id: string;
  source_artifact_id: string;
  conversation_id: string;
  run_id?: string | null;
  version: number;
  status: DesktopArtifactStatus;
  revision: number;
  filename: string;
  mime_type: string;
  path: string;
  relative_path: string;
  bytes: number;
  sources: unknown[];
  checks: unknown[];
  created_at: string;
  updated_at: string;
  approved_at?: string | null;
  delivered_at?: string | null;
  superseded_at?: string | null;
  feedback?: string | null;
};

export type DesktopArtifactDelivery = {
  id: string;
  artifact_version_id: string;
  artifact_id: string;
  conversation_id: string;
  run_id?: string | null;
  destination: string;
  receipt: Record<string, unknown>;
  idempotency_key: string;
  created_at: string;
};

export type ArtifactReviewRequest = {
  action: 'approve' | 'request_changes';
  expectedRevision: number;
  runExpectedRevision?: number;
  feedback?: string;
};

export type ArtifactDeliveryRequest = {
  expectedRevision: number;
  idempotencyKey: string;
  destination?: string;
};

export type ArtifactReviewOutcome = {
  accepted: boolean;
  status: string;
  artifact_version: DesktopArtifactVersion;
  run?: DesktopRun | null;
};

export type ArtifactDeliveryOutcome = {
  accepted: boolean;
  status: 'delivered' | string;
  artifact_version: DesktopArtifactVersion;
  delivery: DesktopArtifactDelivery;
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
  approval_requests?: DesktopApprovalRequest[];
  artifact_versions?: DesktopArtifactVersion[];
  artifact_deliveries?: DesktopArtifactDelivery[];
  tool_invocations?: DesktopToolInvocation[];
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
  approvalRequests: DesktopApprovalRequest[];
  artifactVersions: DesktopArtifactVersion[];
  artifactDeliveries: DesktopArtifactDelivery[];
  toolInvocations: DesktopToolInvocation[];
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
  run_id?: string | null;
  run_revision?: number | null;
  conversation_id?: string | null;
  project_id?: string | null;
  environment_id?: string | null;
  created_at?: string | null;
  expires_at?: string | null;
  resumable?: boolean;
  cwd?: string | null;
  environment?: DesktopExecutionEnvironment | null;
};

export type TerminalConnectionStatus =
  | 'idle'
  | 'connecting'
  | 'connected'
  | 'closed'
  | 'error';

export type AutomationConfig = {
  kind: string;
  config: Record<string, unknown>;
};

export type AutomationTrigger =
  | { kind: 'manual' }
  | { kind: 'schedule'; schedule: AutomationConfig }
  | {
      kind: 'event';
      source_id?: string | null;
      event_type: string;
      filters?: Array<Record<string, unknown>>;
    }
  | { kind: 'unknown'; raw_kind?: string | null };

export type AutomationActionCapability = {
  allowed: boolean;
  reason_code: string;
};

export type AutomationCapabilities = {
  schema_version: number;
  read: boolean;
  revision_guarded: boolean;
  idempotency_guarded: boolean;
  durable_execution: boolean;
  supported_read_trigger_kinds: string[];
  create: AutomationActionCapability;
  edit: AutomationActionCapability;
  toggle: AutomationActionCapability;
  run_now: AutomationActionCapability;
  delete: AutomationActionCapability;
};

export type AutomationJob = {
  id: string;
  project_id: string;
  tenant_id: string;
  name: string;
  description?: string | null;
  enabled: boolean;
  delete_after_run: boolean;
  revision: number;
  schedule_revision: number;
  trigger?: AutomationTrigger;
  schedule: AutomationConfig;
  payload: AutomationConfig;
  delivery: AutomationConfig;
  conversation_mode: string;
  conversation_id?: string | null;
  timezone: string;
  stagger_seconds: number;
  timeout_seconds: number;
  max_retries: number;
  state: Record<string, unknown>;
  created_by?: string | null;
  created_at: string;
  updated_at?: string | null;
};

export type AutomationJobListResponse = {
  items: AutomationJob[];
  total: number;
};

export type AutomationRun = {
  id: string;
  job_id: string;
  project_id: string;
  status: string;
  trigger_type: string;
  started_at: string;
  finished_at?: string | null;
  duration_ms?: number | null;
  error_message?: string | null;
  result_summary: Record<string, unknown>;
  conversation_id?: string | null;
};

export type AutomationRunListResponse = {
  items: AutomationRun[];
  total: number;
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
  myWork: ProjectWorkItem[];
  myWorkError: string | null;
};

export const LOCAL_DEV_SERVER_PRESETS = [
  {
    id: 'memstack-python',
    label: 'MemStack reference :8000',
    apiBaseUrl: 'http://127.0.0.1:8000',
  },
  {
    id: 'agistack-rust',
    label: 'agi-stack strangler :8088',
    apiBaseUrl: 'http://127.0.0.1:8088',
  },
] as const;

export const DEFAULT_CONFIG: DesktopRuntimeConfig = {
  apiBaseUrl: LOCAL_DEV_SERVER_PRESETS[0].apiBaseUrl,
  apiKey: '',
  localApiToken: '',
  tenantId: 'default',
  projectId: '',
  workspaceId: '',
  mode: 'local',
  llmProvider: 'unconfigured',
  llmBaseUrl: 'http://127.0.0.1:11434/v1',
  llmModel: '',
  llmApiKey: '',
  workspaceRoot: '',
};
