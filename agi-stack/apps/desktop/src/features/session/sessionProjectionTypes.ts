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
  artifactVersionCount: number;
  artifactDeliveryCount: number;
  artifactSourceCount: number;
  toolInvocationCount: number;
  unknownOutcomeCount: number;
  checks: {
    total: number;
    artifactVersionsWithoutChecks: number;
  } | null;
  changes: null;
};

export type ConversationSessionProjection = {
  schemaVersion: 1;
  conversation: AgentConversation;
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
  | { status: 'unsupported'; conversationId: string; projection: null; error: null }
  | { status: 'error'; conversationId: string; projection: null; error: string };

export const emptySessionProjectionState: SessionProjectionLoadState = {
  status: 'idle',
  conversationId: null,
  projection: null,
  error: null,
};
