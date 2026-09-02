import type { ProjectMyWorkResponse, RunSummary } from '../../types';

export type {
  ProjectMyWorkResponse,
  ProjectWorkItem,
  RunSummary,
} from '../../types';

export type CloudAgentAuthorityScope = Readonly<{
  authority: 'cloud';
  principalId: string;
  tenantId: string;
  projectId: string;
}>;

export type LocalActivityAuthorityScope = Readonly<{
  authority: 'local';
  principalId: string;
  tenantId: string;
  projectId: string;
}>;

export type ActivityAuthorityScope =
  | CloudAgentAuthorityScope
  | LocalActivityAuthorityScope;

export type ActivityReadEntry = Readonly<{
  entry_id: string;
  entry_revision: number;
  read_at: string;
}>;

export type ActivityReadState = Readonly<{
  project_id: string;
  authority_revision: number;
  entries: readonly ActivityReadEntry[];
}>;

export type UpdateActivityReadStateRequest = Readonly<{
  expected_authority_revision: number;
  entries: readonly ActivityReadEntry[];
}>;

export type ActivityReadUpdateResult =
  | Readonly<{ kind: 'synced'; state: ActivityReadState }>
  | Readonly<{
      kind: 'queued_offline';
      availability: 'degraded';
      reasonCode:
        | 'cloud_activity_read_state_offline_retry_pending'
        | 'local_activity_read_state_offline_retry_pending';
      expectedAuthorityRevision: number;
      entries: readonly ActivityReadEntry[];
    }>;

export type RunChangeScope = 'turn' | 'run' | 'session';
export type RunChangeSnapshotStatus =
  | 'ready'
  | 'unattributed'
  | 'unavailable'
  | 'failed';

export type RunChangeLine = Readonly<{
  kind: 'context' | 'addition' | 'deletion';
  old_line: number | null;
  new_line: number | null;
  text: string;
}>;

export type RunChangeHunk = Readonly<{
  header: string;
  old_start: number;
  new_start: number;
  lines: readonly RunChangeLine[];
}>;

export type RunChangeFile = Readonly<{
  path: string;
  old_path: string | null;
  status: string;
  additions: number;
  deletions: number;
  binary: boolean;
  untracked: boolean;
  patch_digest: string;
  hunks: readonly RunChangeHunk[];
}>;

export type RunChangeAttribution = Readonly<{
  file_path: string | null;
  hunk_id: string | null;
  attribution: 'attributed' | 'unattributed';
  turn_id: string | null;
  event_id: string;
  event_revision: string;
  payload: Readonly<Record<string, unknown>>;
}>;

export type RunChanges = Readonly<{
  id: string;
  run_id: string;
  conversation_id: string;
  run_revision: number;
  environment_id: string | null;
  repository_root: string | null;
  workspace_path: string | null;
  branch: string | null;
  base_revision: string | null;
  head_revision: string | null;
  status: RunChangeSnapshotStatus;
  reason: string | null;
  additions: number;
  deletions: number;
  files_changed: number;
  truncated: boolean;
  captured_at: string;
  files: readonly RunChangeFile[];
  scope: RunChangeScope;
  turn_id: string | null;
  snapshot_revision: string;
  attribution: readonly RunChangeAttribution[];
}>;

export type GetRunChangesOptions = Readonly<{
  scope: RunChangeScope;
  expected_revision: number;
  turn_id?: string;
  signal?: AbortSignal;
}>;

export type AgentAuthorityReadOptions = Readonly<{ signal?: AbortSignal }>;

export interface ActivityReadRetryStore {
  load(scope: ActivityAuthorityScope): readonly ActivityReadEntry[];
  save(
    scope: ActivityAuthorityScope,
    entries: readonly ActivityReadEntry[],
  ): void;
  clear(scope: ActivityAuthorityScope): void;
}

export interface DesktopActivityAuthorityClient {
  getActivityReadState(
    scope: ActivityAuthorityScope,
    options?: AgentAuthorityReadOptions,
  ): Promise<ActivityReadState>;
  putActivityReadState(
    scope: ActivityAuthorityScope,
    request: UpdateActivityReadStateRequest,
    options?: AgentAuthorityReadOptions,
  ): Promise<ActivityReadUpdateResult>;
  flushPendingActivityReadState(
    scope: ActivityAuthorityScope,
    options?: AgentAuthorityReadOptions,
  ): Promise<ActivityReadUpdateResult>;
}

export interface DesktopCloudAgentAuthorityClient
  extends DesktopActivityAuthorityClient {
  listMyWork(
    scope: CloudAgentAuthorityScope,
    options?: AgentAuthorityReadOptions,
  ): Promise<ProjectMyWorkResponse>;
  getRunSummary(
    scope: CloudAgentAuthorityScope,
    runId: string,
    options?: AgentAuthorityReadOptions,
  ): Promise<RunSummary>;
  getRunChanges(
    scope: CloudAgentAuthorityScope,
    runId: string,
    options: GetRunChangesOptions,
  ): Promise<RunChanges>;
}

export type DesktopAgentAuthorityAction =
  | 'list_my_work'
  | 'read_activity'
  | 'write_activity'
  | 'review_run_summary'
  | 'review_run_changes';

export type DesktopAgentAuthorityAdapter =
  | Readonly<{
      authority: 'cloud';
      availability: 'available';
      reasonCode: null;
      allowedActions: readonly DesktopAgentAuthorityAction[];
      client: DesktopCloudAgentAuthorityClient;
      activityClient: DesktopActivityAuthorityClient;
      activityScope: null;
    }>
  | Readonly<{
      authority: 'local';
      availability: 'available';
      reasonCode: null;
      allowedActions: readonly DesktopAgentAuthorityAction[];
      client: null;
      activityClient: DesktopActivityAuthorityClient;
      activityScope: LocalActivityAuthorityScope;
    }>;
