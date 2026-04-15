export type WorkspaceMemberRole = 'owner' | 'editor' | 'viewer';

export type BlackboardPostStatus = 'open' | 'archived';

export type WorkspaceTaskStatus = 'todo' | 'in_progress' | 'blocked' | 'done';
export type WorkspaceTaskPriority = '' | 'P1' | 'P2' | 'P3' | 'P4';

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
  metadata?: Record<string, unknown> | undefined;
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
  metadata?: Record<string, unknown> | undefined;
}

export interface WorkspaceUpdateRequest {
  name?: string | undefined;
  description?: string | undefined;
  is_archived?: boolean | undefined;
  metadata?: Record<string, unknown> | undefined;
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
