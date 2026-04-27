export type WorkspaceMemberRole = 'owner' | 'editor' | 'viewer';

export type BlackboardPostStatus = 'open' | 'archived';

export type WorkspaceTaskStatus = 'todo' | 'in_progress' | 'blocked' | 'done';
export type WorkspaceTaskPriority = '' | 'P1' | 'P2' | 'P3' | 'P4';
export type WorkspaceType = 'general' | 'software_development' | 'research' | 'operations';
export type WorkspaceUseCase =
  | 'general'
  | 'programming'
  | 'conversation'
  | 'research'
  | 'operations';
export type WorkspaceVerificationGrade = 'pass' | 'warn' | 'fail';
export type WorkspaceCollaborationMode =
  | 'single_agent'
  | 'multi_agent_shared'
  | 'multi_agent_isolated'
  | 'autonomous';

export interface WorkspaceCompletionPolicyOverride {
  allow_internal_task_artifacts?: boolean | undefined;
  required_artifact_prefixes?: string[] | undefined;
  requires_external_artifact?: boolean | undefined;
  minimum_verification_grade?: WorkspaceVerificationGrade | undefined;
  stream_completion_reports_success?: boolean | undefined;
}

export interface WorkspaceAutonomyProfile {
  workspace_type?: WorkspaceType | undefined;
  completion_policy?: WorkspaceCompletionPolicyOverride | undefined;
}

export interface WorkspaceCodeContext {
  sandbox_code_root?: string | undefined;
  loaded_agents_files?: string[] | undefined;
  agents_digest?: string | undefined;
  agents_excerpt?: string | undefined;
}

export type WorkspaceMetadata = Record<string, unknown> & {
  workspace_use_case?: WorkspaceUseCase | undefined;
  workspace_type?: WorkspaceType | undefined;
  collaboration_mode?: WorkspaceCollaborationMode | undefined;
  agent_conversation_mode?: WorkspaceCollaborationMode | undefined;
  autonomy_profile?: WorkspaceAutonomyProfile | undefined;
  sandbox_code_root?: string | undefined;
  code_context?: WorkspaceCodeContext | undefined;
};

export type TopologyNodeType =
  | 'user'
  | 'agent'
  | 'task'
  | 'note'
  | 'corridor'
  | 'human_seat'
  | 'objective';

export interface Workspace {
  id: string;
  tenant_id: string;
  project_id: string;
  name: string;
  created_by: string;
  description?: string | undefined;
  is_archived?: boolean | undefined;
  metadata?: WorkspaceMetadata | undefined;
  office_status?: string | undefined;
  hex_layout_config?: Record<string, unknown> | undefined;
  created_at: string;
  updated_at?: string | undefined;
}

export interface WorkspaceMember {
  id: string;
  workspace_id: string;
  user_id: string;
  user_email?: string | undefined;
  role: WorkspaceMemberRole;
  invited_by?: string | undefined;
  created_at: string;
  updated_at?: string | undefined;
}

export interface WorkspaceAgent {
  id: string;
  workspace_id: string;
  agent_id: string;
  display_name?: string | undefined;
  description?: string | undefined;
  config?: Record<string, unknown> | undefined;
  is_active: boolean;
  hex_q?: number | undefined;
  hex_r?: number | undefined;
  theme_color?: string | undefined;
  label?: string | undefined;
  status?: string | undefined;
  created_at: string;
  updated_at?: string | undefined;
}

export interface BlackboardPost {
  id: string;
  workspace_id: string;
  author_id: string;
  title: string;
  content: string;
  status: BlackboardPostStatus;
  is_pinned: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at?: string | undefined;
}

export interface BlackboardReply {
  id: string;
  post_id: string;
  workspace_id: string;
  author_id: string;
  content: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at?: string | undefined;
}

export interface WorkspaceTask {
  id: string;
  workspace_id: string;
  title: string;
  description?: string | undefined;
  created_by?: string | undefined;
  assignee_user_id?: string | undefined;
  assignee_agent_id?: string | undefined;
  workspace_agent_id?: string | undefined;
  current_attempt_id?: string | undefined;
  current_attempt_number?: number | undefined;
  current_attempt_conversation_id?: string | undefined;
  current_attempt_worker_binding_id?: string | undefined;
  current_attempt_worker_agent_id?: string | undefined;
  last_attempt_status?: string | undefined;
  pending_leader_adjudication?: boolean | undefined;
  last_worker_report_type?: string | undefined;
  last_worker_report_summary?: string | undefined;
  last_worker_report_artifacts?: string[] | undefined;
  last_worker_report_verifications?: string[] | undefined;
  status: WorkspaceTaskStatus;
  priority?: WorkspaceTaskPriority | undefined;
  estimated_effort?: string | undefined;
  blocker_reason?: string | undefined;
  completed_at?: string | undefined;
  archived_at?: string | undefined;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at?: string | undefined;
}

export type WorkspacePlanStatus = 'draft' | 'active' | 'suspended' | 'completed' | 'abandoned';
export type WorkspacePlanNodeKind = 'goal' | 'milestone' | 'task' | 'verify';
export type WorkspacePlanTaskIntent = 'todo' | 'in_progress' | 'blocked' | 'done';
export type WorkspacePlanTaskExecution =
  | 'idle'
  | 'dispatched'
  | 'running'
  | 'reported'
  | 'verifying';

export interface WorkspacePlanAcceptanceCriterion {
  kind: string;
  spec: Record<string, unknown>;
  required: boolean;
  description?: string | null | undefined;
}

export interface WorkspacePlanCapabilityHint {
  name: string;
  weight: number;
}

export interface WorkspacePlanActionCapability {
  enabled: boolean;
  label: string;
  reason?: string | null | undefined;
  requires_confirmation: boolean;
}

export interface WorkspacePlanNode {
  id: string;
  parent_id: string | null;
  kind: WorkspacePlanNodeKind;
  title: string;
  description: string;
  depends_on: string[];
  acceptance_criteria: WorkspacePlanAcceptanceCriterion[];
  recommended_capabilities: WorkspacePlanCapabilityHint[];
  intent: WorkspacePlanTaskIntent;
  execution: WorkspacePlanTaskExecution;
  progress: {
    percent: number;
    confidence: number;
    note: string;
  };
  assignee_agent_id: string | null;
  current_attempt_id: string | null;
  workspace_task_id: string | null;
  priority: number;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at?: string | null | undefined;
  completed_at?: string | null | undefined;
  actions?: Record<string, WorkspacePlanActionCapability> | undefined;
}

export interface WorkspacePlan {
  id: string;
  workspace_id: string;
  goal_id: string;
  status: WorkspacePlanStatus;
  created_at: string;
  updated_at?: string | null | undefined;
  nodes: WorkspacePlanNode[];
  counts: Record<string, number>;
}

export interface WorkspacePlanBlackboardEntry {
  plan_id: string;
  key: string;
  value: unknown;
  published_by: string;
  version: number;
  schema_ref?: string | null | undefined;
  metadata: Record<string, unknown>;
}

export interface WorkspacePlanOutboxItem {
  id: string;
  plan_id: string;
  workspace_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  status: string;
  attempt_count: number;
  max_attempts: number;
  lease_owner?: string | null | undefined;
  lease_expires_at?: string | null | undefined;
  last_error?: string | null | undefined;
  next_attempt_at?: string | null | undefined;
  processed_at?: string | null | undefined;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at?: string | null | undefined;
  actions?: Record<string, WorkspacePlanActionCapability> | undefined;
}

export interface WorkspacePlanEvent {
  id: string;
  plan_id: string;
  workspace_id: string;
  node_id?: string | null | undefined;
  attempt_id?: string | null | undefined;
  event_type: string;
  source: string;
  actor_id?: string | null | undefined;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface WorkspacePlanSnapshot {
  workspace_id: string;
  plan: WorkspacePlan | null;
  root_goal?: WorkspacePlanRootGoal | null | undefined;
  blackboard: WorkspacePlanBlackboardEntry[];
  outbox: WorkspacePlanOutboxItem[];
  events: WorkspacePlanEvent[];
}

export interface WorkspacePlanRootGoal {
  id: string;
  title: string;
  status: string;
  blocker_reason?: string | null | undefined;
  goal_health?: string | null | undefined;
  remediation_status?: string | null | undefined;
  remediation_summary?: string | null | undefined;
  evidence_grade?: string | null | undefined;
  completion_blocker_reason?: string | null | undefined;
  updated_at?: string | null | undefined;
  completed_at?: string | null | undefined;
}

export interface WorkspacePlanActionResult {
  ok: boolean;
  message: string;
  plan_id: string;
  node_id?: string | null | undefined;
  outbox_id?: string | null | undefined;
}

export type WorkspaceExecutionDiagnosticsRow = Record<string, unknown> & {
  task_id?: string | null | undefined;
  title?: string | null | undefined;
  reason?: string | null | undefined;
  attempt_id?: string | null | undefined;
  tool_execution_id?: string | null | undefined;
  tool_name?: string | null | undefined;
  status?: string | null | undefined;
  error?: string | null | undefined;
  completed_at?: string | null | undefined;
};

export interface WorkspaceExecutionDiagnostics {
  workspace_id: string;
  generated_at: string;
  task_status_counts: Record<string, number>;
  attempt_status_counts: Record<string, number>;
  tool_status_counts: Record<string, number>;
  tasks: WorkspaceExecutionDiagnosticsRow[];
  blockers: WorkspaceExecutionDiagnosticsRow[];
  pending_adjudications: WorkspaceExecutionDiagnosticsRow[];
  evidence_gaps: WorkspaceExecutionDiagnosticsRow[];
  recent_tool_failures: WorkspaceExecutionDiagnosticsRow[];
}

export interface TopologyNode {
  id: string;
  workspace_id: string;
  node_type: TopologyNodeType;
  ref_id?: string | undefined;
  title: string;
  position_x: number;
  position_y: number;
  hex_q?: number | undefined;
  hex_r?: number | undefined;
  status?: string | undefined;
  tags?: string[] | undefined;
  data: Record<string, unknown>;
  created_at?: string | undefined;
  updated_at?: string | undefined;
}

export interface TopologyEdge {
  id: string;
  workspace_id: string;
  source_node_id: string;
  target_node_id: string;
  label?: string | undefined;
  source_hex_q?: number | undefined;
  source_hex_r?: number | undefined;
  target_hex_q?: number | undefined;
  target_hex_r?: number | undefined;
  direction?: string | undefined;
  auto_created?: boolean | undefined;
  data: Record<string, unknown>;
  created_at?: string | undefined;
  updated_at?: string | undefined;
}

export interface WorkspaceCreateRequest {
  name: string;
  description?: string | undefined;
  metadata?: WorkspaceMetadata | undefined;
  use_case?: WorkspaceUseCase | undefined;
  collaboration_mode?: WorkspaceCollaborationMode | undefined;
  autonomy_profile?: WorkspaceAutonomyProfile | undefined;
  sandbox_code_root?: string | undefined;
}

export interface WorkspaceUpdateRequest {
  name?: string | undefined;
  description?: string | undefined;
  is_archived?: boolean | undefined;
  metadata?: WorkspaceMetadata | undefined;
}

export type CyberObjectiveType = 'objective' | 'key_result';

export interface CyberObjective {
  id: string;
  workspace_id: string;
  title: string;
  description?: string | undefined;
  obj_type: CyberObjectiveType;
  parent_id?: string | undefined;
  progress: number;
  created_by?: string | undefined;
  created_at: string;
  updated_at?: string | undefined;
}

export interface PresenceUser {
  user_id: string;
  display_name: string;
  joined_at: string;
  last_heartbeat: string;
}

export interface PresenceAgent {
  agent_id: string;
  display_name: string;
  status: string;
}

export interface WorkspacePresenceEvent {
  type: string;
  routing_key: string;
  workspace_id: string;
  data: Record<string, unknown>;
  event_id: string;
  timestamp: string;
}

export type CyberGeneCategory = 'skill' | 'knowledge' | 'tool' | 'workflow';

export interface CyberGene {
  id: string;
  workspace_id: string;
  name: string;
  category: CyberGeneCategory;
  description?: string | undefined;
  config_json?: string | undefined;
  version: string;
  is_active: boolean;
  created_by: string;
  created_at: string;
  updated_at?: string | undefined;
}

export type MessageSenderType = 'human' | 'agent';

export interface WorkspaceMessage {
  id: string;
  workspace_id: string;
  sender_id: string;
  sender_type: MessageSenderType;
  content: string;
  mentions: string[];
  parent_message_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface SendMessageRequest {
  content: string;
  sender_type?: string;
  parent_message_id?: string | null;
}

export interface MessageListResponse {
  items: WorkspaceMessage[];
}
