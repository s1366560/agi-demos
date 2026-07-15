import type {
  AgentConversation,
  ConversationTimelineState,
  DesktopRun,
  DesktopRunStatus,
  WorkspaceSummary,
} from '../../types';
import type {
  ConversationSessionProjection,
  SessionRunAction,
} from './sessionProjectionTypes';

export type { SessionRunAction } from './sessionProjectionTypes';

export type SessionCapabilityMode = 'work' | 'code' | 'unavailable';
export type SessionStage = 'understand' | 'implement' | 'verify' | 'review' | 'unavailable';
export type SessionExecutionMode = 'plan' | 'build' | 'explore' | 'unavailable';

export type SessionDetailViewModel = {
  id: string;
  title: string;
  workspaceLabel: string | null;
  status: string;
  executionAuthorityKind:
    | 'desktop_run'
    | 'workspace_attempt'
    | 'conversation_record'
    | 'unavailable';
  capabilityMode: SessionCapabilityMode;
  executionMode: SessionExecutionMode;
  stage: SessionStage;
  environmentLabel: string | null;
  branchLabel: string | null;
  modelLabel: string | null;
  permissionLabel: string | null;
  elapsedLabel: string | null;
  usageLabel: string | null;
  taskCount: number;
  eventCount: number;
  hasPlan: boolean;
  runId: string | null;
  runRevision: number | null;
  attemptNumber: number | null;
  workerAgentId: string | null;
  leaderAgentId: string | null;
  error: string | null;
  lastHeartbeatAt: string | null;
  runActions: SessionRunAction[];
};

export type SessionStatusPresentation = {
  tone: 'attention' | 'danger' | 'warning' | 'success';
  titleKey: string;
  descriptionKey: string;
};

type SessionViewModelInput = {
  conversation: AgentConversation;
  workspace: WorkspaceSummary | null;
  timeline: ConversationTimelineState;
  projection: ConversationSessionProjection | null;
  authorityAvailable?: boolean;
};

const capabilityModes: ReadonlySet<string> = new Set(['work', 'code']);
const runStatuses: ReadonlySet<string> = new Set<DesktopRunStatus>([
  'queued',
  'running',
  'needs_input',
  'needs_approval',
  'paused',
  'ready_review',
  'completed',
  'failed',
  'disconnected',
  'interrupted',
  'cancelled',
]);

export type SessionRecoveryPresentation = {
  action: Extract<SessionRunAction, 'reconnect' | 'fork'>;
  labelKey: string;
  titleKey: string;
  descriptionKey: string;
  confirmationRequired: boolean;
  primary: boolean;
  warnings?: string[];
};

export function authoritativeRunFromSocketEvent(event: unknown): DesktopRun | null {
  const envelope = recordValue(event);
  const eventType = stringValue(envelope.type) ?? stringValue(envelope.event_type);
  if (eventType !== 'run_status') return null;
  return parseAuthoritativeRun(envelope.payload);
}

export function authoritativeRunFromConversation(
  conversation: AgentConversation | null,
): DesktopRun | null {
  if (!conversation) return null;
  return parseAuthoritativeRun(recordValue(conversation.metadata).run);
}

function parseAuthoritativeRun(value: unknown): DesktopRun | null {
  const run = recordValue(value);
  const status = stringValue(run.status);
  const revision = numberValue(run.revision);
  if (
    !stringValue(run.id) ||
    !stringValue(run.conversation_id) ||
    !status ||
    !runStatuses.has(status) ||
    revision === null
  ) {
    return null;
  }
  return run as DesktopRun;
}

export function authoritativeRunsFromSocketEvents(events: readonly unknown[]): DesktopRun[] {
  const runs = new Map<string, DesktopRun>();
  for (const event of events) {
    const run = authoritativeRunFromSocketEvent(event);
    if (!run) continue;
    const current = runs.get(run.conversation_id);
    if (!current || isNewerAuthoritativeRun(run, current)) {
      runs.set(run.conversation_id, run);
    }
  }
  return [...runs.values()];
}

export function conversationWithAuthoritativeRun(
  conversation: AgentConversation,
  run: DesktopRun,
): AgentConversation {
  if (conversation.id !== run.conversation_id) return conversation;
  const metadata = recordValue(conversation.metadata);
  const currentRun = recordValue(metadata.run);
  const parsedCurrent = parseAuthoritativeRun(currentRun);
  if (parsedCurrent && !isNewerAuthoritativeRun(run, parsedCurrent)) return conversation;
  return {
    ...conversation,
    updated_at: run.updated_at,
    metadata: { ...metadata, run },
  };
}

export function mergeConversationListWithCurrentRunAuthority(
  incoming: AgentConversation[],
  current: AgentConversation[],
): AgentConversation[] {
  const currentById = new Map(current.map((conversation) => [conversation.id, conversation]));
  return incoming.map((conversation) => {
    const currentRun = authoritativeRunFromConversation(
      currentById.get(conversation.id) ?? null,
    );
    return currentRun ? conversationWithAuthoritativeRun(conversation, currentRun) : conversation;
  });
}

function isNewerAuthoritativeRun(candidate: DesktopRun, current: DesktopRun): boolean {
  if (candidate.id === current.id) return candidate.revision > current.revision;
  const candidateSource = stringValue(
    recordValue(candidate.authorization_snapshot).source_run_id,
  );
  const currentSource = stringValue(recordValue(current.authorization_snapshot).source_run_id);
  if (candidateSource === current.id) return true;
  if (currentSource === candidate.id) return false;
  const candidateCreated = Date.parse(candidate.created_at);
  const currentCreated = Date.parse(current.created_at);
  if (Number.isFinite(candidateCreated) && Number.isFinite(currentCreated)) {
    if (candidateCreated !== currentCreated) return candidateCreated > currentCreated;
  }
  const candidateUpdated = Date.parse(candidate.updated_at);
  const currentUpdated = Date.parse(current.updated_at);
  if (Number.isFinite(candidateUpdated) && Number.isFinite(currentUpdated)) {
    if (candidateUpdated !== currentUpdated) return candidateUpdated > currentUpdated;
  }
  return candidate.id.localeCompare(current.id) > 0;
}

export function buildSessionDetailViewModel({
  conversation,
  workspace,
  timeline,
  projection,
  authorityAvailable = true,
}: SessionViewModelInput): SessionDetailViewModel {
  const authorityConversation = projection?.conversation ?? conversation;
  const run = projection?.currentRun ?? null;
  const executionAuthority = projection?.executionAuthority ?? null;
  const attempt =
    executionAuthority?.kind === 'workspace_attempt'
      ? executionAuthority.currentAttempt
      : null;
  const agentConfig = projection ? recordValue(authorityConversation.agent_config) : {};
  const explicitStatus =
    run?.status ??
    attempt?.status ??
    (executionAuthority?.kind === 'conversation_record' ? authorityConversation.status : null);
  const explicitMode = stringValue(agentConfig.capability_mode);
  const executionMode = projection ? stringValue(authorityConversation.current_mode) : null;
  const elapsedSeconds = run ? elapsedSecondsForRun(run) : null;
  const environment = recordValue(run?.environment);

  return {
    id: authorityConversation.id,
    title: authorityConversation.title || 'Untitled session',
    workspaceLabel: workspace?.name ?? workspace?.title ?? workspace?.id ?? null,
    status: explicitStatus ?? 'unavailable',
    executionAuthorityKind: executionAuthority?.kind ?? 'unavailable',
    capabilityMode: capabilityModes.has(explicitMode ?? '')
      ? (explicitMode as SessionCapabilityMode)
      : 'unavailable',
    executionMode:
      executionMode === 'plan' || executionMode === 'build' || executionMode === 'explore'
        ? executionMode
        : 'unavailable',
    stage: 'unavailable',
    environmentLabel:
      stringValue(environment.label) ??
      stringValue(environment.kind) ??
      null,
    branchLabel: stringValue(environment.branch),
    modelLabel: stringValue(agentConfig.model),
    permissionLabel: run?.permission_profile ?? null,
    elapsedLabel: elapsedSeconds === null ? null : formatDuration(elapsedSeconds),
    usageLabel: null,
    taskCount: projection?.tasks.length ?? 0,
    eventCount: timeline.items.length,
    hasPlan:
      projection?.planAuthority.kind === 'desktop_plan_version'
        ? projection.currentPlan !== null
        : projection?.planAuthority.workspacePlanContext !== null && projection !== null,
    runId: run?.id ?? null,
    runRevision: run?.revision ?? null,
    attemptNumber: attempt?.attemptNumber ?? null,
    workerAgentId: attempt?.workerAgentId ?? null,
    leaderAgentId: attempt?.leaderAgentId ?? null,
    error: run?.error ?? null,
    lastHeartbeatAt: run?.last_heartbeat_at ?? null,
    runActions: authorityAvailable ? (projection?.capabilities.runActions ?? []) : [],
  };
}

export function sessionStatusPresentation(status: string): SessionStatusPresentation | null {
  const presentations: Record<string, SessionStatusPresentation> = {
    needs_input: {
      tone: 'attention',
      titleKey: 'session.needsInput',
      descriptionKey: 'session.needsInputDescription',
    },
    needs_approval: {
      tone: 'attention',
      titleKey: 'session.needsApproval',
      descriptionKey: 'session.needsApprovalDescription',
    },
    failed: {
      tone: 'danger',
      titleKey: 'session.runFailed',
      descriptionKey: 'session.runFailedDescription',
    },
    interrupted: {
      tone: 'warning',
      titleKey: 'session.runInterrupted',
      descriptionKey: 'session.runInterruptedDescription',
    },
    paused: {
      tone: 'warning',
      titleKey: 'session.runPaused',
      descriptionKey: 'session.runPausedDescription',
    },
    disconnected: {
      tone: 'danger',
      titleKey: 'session.runDisconnected',
      descriptionKey: 'session.runDisconnectedDescription',
    },
    ready_review: {
      tone: 'success',
      titleKey: 'session.readyReview',
      descriptionKey: 'session.readyReviewDescription',
    },
  };
  return presentations[status.trim().toLowerCase()] ?? null;
}

export function sessionRecoveryPresentation(
  action: Extract<SessionRunAction, 'reconnect' | 'fork'>,
): SessionRecoveryPresentation {
  if (action === 'reconnect') {
    return {
      action,
      labelKey: 'session.reconnectRun',
      titleKey: 'session.reattachTitle',
      descriptionKey: 'session.reattachDescription',
      confirmationRequired: false,
      primary: true,
    };
  }
  return {
    action,
    labelKey: 'session.forkRecovery',
    titleKey: 'session.forkRecoveryTitle',
    descriptionKey: 'session.forkRecoveryDescription',
    confirmationRequired: true,
    primary: false,
    warnings: [
      'session.forkRecoveryNewRun',
      'session.forkRecoveryVerifiedHead',
      'session.forkRecoveryLocalChanges',
    ],
  };
}

function recordValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

function formatDuration(totalSeconds: number): string {
  const seconds = Math.floor(totalSeconds % 60);
  const minutes = Math.floor((totalSeconds / 60) % 60);
  const hours = Math.floor(totalSeconds / 3600);
  return [hours, minutes, seconds].map((part) => String(part).padStart(2, '0')).join(':');
}

function elapsedSecondsForRun(run: DesktopRun): number | null {
  if (!run.started_at) return null;
  const startedAt = Date.parse(run.started_at);
  const stoppedAt = Date.parse(run.completed_at ?? run.updated_at);
  if (!Number.isFinite(startedAt) || !Number.isFinite(stoppedAt) || stoppedAt < startedAt) {
    return null;
  }
  return Math.floor((stoppedAt - startedAt) / 1000);
}
