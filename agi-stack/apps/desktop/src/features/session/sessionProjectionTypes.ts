import type {
  AgentConversation,
  DesktopApprovalRequest,
  DesktopArtifactDelivery,
  DesktopArtifactVersion,
  DesktopRun,
  DesktopToolInvocation,
} from '../../types';

export type SessionProjectionTask = Record<string, unknown> & {
  id: string;
  conversation_id?: string;
};

export type SessionProjectionPlan = {
  id: string;
  conversation_id: string;
  version: number;
  status: 'draft' | 'approved';
  tasks: SessionProjectionTask[];
  created_at: string;
  approved_at: string | null;
};

export type SessionRunAction =
  | 'pause'
  | 'resume'
  | 'cancel'
  | 'reconnect'
  | 'fork'
  | 'request_changes'
  | 'approve';

export type SessionAllowedAction =
  | 'send_message'
  | 'approve_plan_and_start'
  | 'respond_to_hitl'
  | 'steer_now'
  | 'queue_next'
  | 'review_artifact'
  | 'deliver_artifact'
  | SessionRunAction;

export type SessionProjectionCapabilities = {
  canSendMessage: boolean;
  canApprovePlan: boolean;
  canRespondToHitl: boolean;
  canSteerNow: boolean;
  canQueueNext: boolean;
  canReviewArtifacts: boolean;
  canDeliverArtifacts: boolean;
  runActions: SessionRunAction[];
  allowedActions: SessionAllowedAction[];
};

export type SessionProjectionEvidenceSummary = {
  artifactVersionCount: number | null;
  artifactDeliveryCount: number | null;
  artifactSourceCount: number | null;
  toolInvocationCount: number | null;
  unknownOutcomeCount: number | null;
  checks: {
    total: number;
    artifactVersionsWithoutChecks: number;
  } | null;
  changes: null;
};

export type CloudWorkspaceAttempt = {
  id: string;
  workspaceTaskId: string;
  rootGoalTaskId: string;
  workspaceId: string;
  conversationId: string;
  attemptNumber: number;
  status: string;
  workerAgentId: string | null;
  leaderAgentId: string | null;
  candidateSummary: string | null;
  candidateArtifactRefs: string[];
  candidateVerificationRefs: string[];
  leaderFeedback: string | null;
  adjudicationReason: string | null;
  createdAt: string;
  updatedAt: string | null;
  completedAt: string | null;
};

export type CloudWorkspacePlanNode = {
  id: string;
  planId: string;
  workspaceTaskId: string;
  kind: string;
  title: string;
  description: string;
  intent: string;
  execution: string;
  progress: Record<string, unknown>;
  assigneeAgentId: string | null;
  currentAttemptId: string | null;
  createdAt: string;
  updatedAt: string | null;
  completedAt: string | null;
};

export type CloudWorkspacePlanContext = {
  id: string;
  workspaceId: string;
  goalId: string;
  status: string;
  createdAt: string;
  updatedAt: string | null;
  linkedNodes: CloudWorkspacePlanNode[];
};

export type CloudToolExecutionRecord = {
  id: string;
  messageId: string;
  callId: string;
  toolName: string;
  status: string;
  error: string | null;
  stepNumber: number | null;
  sequenceNumber: number;
  startedAt: string;
  completedAt: string | null;
  durationMs: number | null;
};

export type CloudToolExecutionRecords = {
  items: CloudToolExecutionRecord[];
  total: number;
  truncated: boolean;
};

export type CloudEvidenceSummary = {
  candidateArtifactRefCount: number;
  candidateVerificationRefCount: number;
  artifactRecordCount: number;
  toolExecutionRecordCount: number;
  failedToolExecutionCount: number;
};

export type SessionExecutionAuthority =
  | {
      kind: 'desktop_run';
      currentRun: DesktopRun | null;
      runHistory: DesktopRun[];
      currentAttempt: null;
      attemptHistory: [];
    }
  | {
      kind: 'workspace_attempt';
      currentRun: null;
      runHistory: [];
      currentAttempt: CloudWorkspaceAttempt;
      attemptHistory: CloudWorkspaceAttempt[];
    }
  | {
      kind: 'conversation_record';
      currentRun: null;
      runHistory: [];
      currentAttempt: null;
      attemptHistory: [];
    };

export type SessionPlanAuthority =
  | {
      kind: 'desktop_plan_version';
      currentPlan: SessionProjectionPlan | null;
      planHistory: SessionProjectionPlan[];
      tasks: SessionProjectionTask[];
      workspacePlanContext: null;
    }
  | {
      kind: 'agent_task_list';
      currentPlan: null;
      planHistory: [];
      tasks: SessionProjectionTask[];
      workspacePlanContext: CloudWorkspacePlanContext | null;
    };

export type SessionHitlAuthority =
  | { kind: 'desktop_hitl'; pending: DesktopApprovalRequest[] }
  | { kind: 'cloud_hitl'; pending: DesktopApprovalRequest[] };

export type SessionArtifactAuthority =
  | {
      kind: 'desktop_artifact_versions';
      versions: DesktopArtifactVersion[];
      deliveries: DesktopArtifactDelivery[];
    }
  | { kind: 'unavailable'; versions: []; deliveries: [] };

export type SessionActivityAuthority =
  | { kind: 'desktop_tool_invocations'; invocations: DesktopToolInvocation[] }
  | ({ kind: 'cloud_tool_records'; invocations: [] } & CloudToolExecutionRecords);

export type ConversationSessionProjection = {
  schemaVersion: 1 | 2;
  conversation: AgentConversation;
  executionAuthority: SessionExecutionAuthority;
  planAuthority: SessionPlanAuthority;
  hitlAuthority: SessionHitlAuthority;
  artifactAuthority: SessionArtifactAuthority;
  activityAuthority: SessionActivityAuthority;
  cloudEvidenceSummary: CloudEvidenceSummary | null;
  currentRun: DesktopRun | null;
  runHistory: DesktopRun[];
  currentPlan: SessionProjectionPlan | null;
  planHistory: SessionProjectionPlan[];
  tasks: SessionProjectionTask[];
  pendingHitl: DesktopApprovalRequest[];
  artifactVersions: DesktopArtifactVersion[];
  artifactDeliveries: DesktopArtifactDelivery[];
  toolInvocations: DesktopToolInvocation[];
  evidenceSummary: SessionProjectionEvidenceSummary;
  capabilities: SessionProjectionCapabilities;
  snapshotRevision: string;
  updatedAt: string;
};

export type SessionProjectionScope = {
  conversationId: string;
  projectId?: string;
  tenantId?: string;
  workspaceId?: string | null;
};

export type SessionProjectionLoadState =
  | { status: 'idle'; conversationId: null; projection: null; error: null }
  | { status: 'loading'; conversationId: string; projection: null; error: null }
  | {
      status: 'ready';
      conversationId: string;
      projection: ConversationSessionProjection;
      error: null;
    }
  | { status: 'error'; conversationId: string; projection: null; error: string };

export const emptySessionProjectionState: SessionProjectionLoadState = {
  status: 'idle',
  conversationId: null,
  projection: null,
  error: null,
};
