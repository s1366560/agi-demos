import { httpClient } from './client/httpClient';

export type ProjectWorkGroup = 'needs_input' | 'needs_approval' | 'running' | 'ready_review';
export type ProjectWorkStatus =
  | 'running'
  | 'ready_review'
  | 'failed'
  | 'needs_input'
  | 'needs_approval'
  | 'completed';

export interface RunSummary {
  run_id: string;
  tenant_id: string;
  project_id: string;
  conversation_id: string;
  status: string;
  revision: number;
  summary_state: 'recorded' | 'partial';
  reason_code?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  duration_ms?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  cost_usd?: number | null;
  model_breakdown: Array<Record<string, unknown>>;
  completion_summary?: string | null;
  artifact_count?: number | null;
  checks_passed?: number | null;
  checks_failed?: number | null;
  files_changed?: number | null;
  lines_added?: number | null;
  lines_deleted?: number | null;
  evidence_references: Array<Record<string, unknown>>;
}

export interface ProjectWorkItem {
  id: string;
  authority_kind: 'desktop_run' | 'agent_run' | 'workspace_attempt' | 'hitl_request';
  authority_id: string;
  run_id?: string | null;
  conversation_id: string;
  workspace_id: string | null;
  project_id: string;
  title: string;
  capability_mode?: 'work' | 'code' | null;
  group: ProjectWorkGroup;
  status: ProjectWorkStatus;
  required_action: 'provide_input' | 'review_approval' | 'observe' | 'inspect_failure';
  revision?: number | null;
  permission_profile?: 'read_only' | 'workspace_write' | 'full_access' | null;
  environment?: string | null;
  error?: string | null;
  attempt_number?: number | null;
  created_at: string;
  updated_at: string;
  last_heartbeat_at?: string | null;
  workspace_name?: string | null;
  summary?: string | null;
  phase?: string | null;
  progress?: number | null;
  run_summary?: RunSummary | null;
}

export interface ProjectMyWorkResponse {
  project_id: string;
  items: ProjectWorkItem[];
  total: number;
}

export interface ActivityReadReceipt {
  entry_id: string;
  entry_revision: number;
  read_at: string;
}

export interface ActivityReadState {
  project_id: string;
  authority_revision: number;
  entries: ActivityReadReceipt[];
}

export interface UpdateActivityReadStateRequest {
  expected_authority_revision: number;
  entries: ActivityReadReceipt[];
}

const projectPath = (projectId: string): string =>
  `/projects/${encodeURIComponent(projectId)}`;

export const projectWorkService = {
  list(projectId: string): Promise<ProjectMyWorkResponse> {
    return httpClient.get(`${projectPath(projectId)}/my-work`);
  },

  getReadState(projectId: string): Promise<ActivityReadState> {
    return httpClient.get(`${projectPath(projectId)}/activity/read-state`);
  },

  updateReadState(
    projectId: string,
    request: UpdateActivityReadStateRequest
  ): Promise<ActivityReadState> {
    return httpClient.put(`${projectPath(projectId)}/activity/read-state`, request);
  },
};
