import type {
  AgentConversation,
  ConversationTimelineState,
  DesktopRun,
  DesktopRunStatus,
  DesktopRuntimeConfig,
  PlanSnapshot,
  WorkspaceSummary,
  WorkspaceTask,
} from '../../types';

export type SessionCapabilityMode = 'work' | 'code' | 'unavailable';
export type SessionStage = 'understand' | 'implement' | 'verify' | 'review' | 'unavailable';
export type SessionExecutionMode = 'plan' | 'build' | 'unavailable';

export type SessionDetailViewModel = {
  id: string;
  title: string;
  workspaceLabel: string;
  status: string;
  capabilityMode: SessionCapabilityMode;
  executionMode: SessionExecutionMode;
  stage: SessionStage;
  environmentLabel: string;
  branchLabel: string | null;
  modelLabel: string;
  permissionLabel: string;
  elapsedLabel: string;
  usageLabel: string;
  taskCount: number;
  eventCount: number;
  hasPlan: boolean;
  runId: string | null;
  runRevision: number | null;
  error: string | null;
  lastHeartbeatAt: string | null;
};

export type SessionStatusPresentation = {
  tone: 'attention' | 'danger' | 'warning' | 'success';
  titleKey: string;
  descriptionKey: string;
};

type SessionViewModelInput = {
  conversation: AgentConversation;
  config: DesktopRuntimeConfig;
  workspace: WorkspaceSummary | null;
  timeline: ConversationTimelineState;
  tasks: WorkspaceTask[];
  plan: PlanSnapshot | null;
};

const sessionStages: ReadonlySet<string> = new Set([
  'understand',
  'implement',
  'verify',
  'review',
]);

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

export type SessionRunAction =
  | 'pause'
  | 'resume'
  | 'cancel'
  | 'reconnect'
  | 'fork'
  | 'request_changes'
  | 'approve';

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
    status: run.status,
    updated_at: run.updated_at,
    metadata: { ...metadata, run },
  };
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
  config,
  workspace,
  timeline,
  tasks,
  plan,
}: SessionViewModelInput): SessionDetailViewModel {
  const metadata = recordValue(conversation.metadata);
  const runMetadata = recordValue(metadata.run);
  const agentConfig = recordValue(conversation.agent_config);
  const explicitStage = stringValue(runMetadata.stage) ?? stringValue(metadata.stage);
  const explicitMode =
    stringValue(metadata.capability_mode) ?? stringValue(agentConfig.capability_mode);
  const executionMode = stringValue(conversation.current_mode);
  const elapsedSeconds = numberValue(runMetadata.elapsed_seconds);
  const usageUsd = numberValue(runMetadata.usage_usd);
  const runEnvironment = recordValue(runMetadata.environment);
  const metadataEnvironment = recordValue(metadata.environment);
  const environment =
    stringValue(runEnvironment.id) || stringValue(runEnvironment.kind)
      ? runEnvironment
      : metadataEnvironment;

  return {
    id: conversation.id,
    title: conversation.title || 'Untitled session',
    workspaceLabel: workspace?.name ?? workspace?.title ?? workspace?.id ?? 'Workspace unavailable',
    status: conversation.status || 'unavailable',
    capabilityMode: capabilityModes.has(explicitMode ?? '')
      ? (explicitMode as SessionCapabilityMode)
      : 'unavailable',
    executionMode:
      executionMode === 'plan' || executionMode === 'build' ? executionMode : 'unavailable',
    stage: sessionStages.has(explicitStage ?? '') ? (explicitStage as SessionStage) : 'unavailable',
    environmentLabel:
      stringValue(environment.label) ??
      stringValue(environment.kind) ??
      (config.mode === 'local' ? 'Local runtime' : 'Cloud runtime'),
    branchLabel: stringValue(environment.branch) ?? stringValue(metadata.branch),
    modelLabel:
      stringValue(agentConfig.model) ?? (config.llmModel.trim() || 'Model unavailable'),
    permissionLabel:
      stringValue(runMetadata.permission_profile) ??
      stringValue(runMetadata.permission_policy) ??
      stringValue(metadata.permission_policy) ??
      'Permission policy unavailable',
    elapsedLabel: elapsedSeconds === null ? 'Elapsed unavailable' : formatDuration(elapsedSeconds),
    usageLabel: usageUsd === null ? 'Usage unavailable' : `$${usageUsd.toFixed(2)}`,
    taskCount: tasks.length,
    eventCount: timeline.items.length,
    hasPlan: plan !== null,
    runId: stringValue(runMetadata.id),
    runRevision: numberValue(runMetadata.revision),
    error: stringValue(runMetadata.error),
    lastHeartbeatAt: stringValue(runMetadata.last_heartbeat_at),
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

export function sessionRunActions(status: string): SessionRunAction[] {
  switch (status.trim().toLowerCase()) {
    case 'running':
      return ['pause', 'cancel'];
    case 'paused':
      return ['resume', 'cancel'];
    case 'disconnected':
    case 'interrupted':
      return ['reconnect', 'fork', 'cancel'];
    case 'ready_review':
      return ['request_changes', 'approve'];
    default:
      return [];
  }
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
