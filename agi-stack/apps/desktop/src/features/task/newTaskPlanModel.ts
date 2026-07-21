import type { AgentPlanTask, DesktopRuntimeConfig } from '../../types';
import { canonicalJsonSha256 } from '../session/canonicalJsonDigest';

export type NewTaskKind = 'general' | 'programming';
export type NewTaskContextSource = 'project_memory' | 'project_files' | 'web_research';
export type NewTaskAgentTurnOutcome = 'acknowledged' | 'unknown_outcome';

export type PlanningTurnAttempt = {
  fingerprint: string;
  messageId: string;
};

export type LegacyPlanApprovalRecovery = {
  schemaVersion: 2;
  conversationId: string;
  runtimeScope: string;
  planSignature: string;
  messageId: string;
  createdAt: number;
  expiresAt: number;
};

export type LegacyPlanApprovalStorage = {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
  removeItem: (key: string) => void;
};

export const PLAN_EMPTY_POLL_RETRY_THRESHOLD = 8;
export const LEGACY_PLAN_APPROVAL_TTL_MS = 24 * 60 * 60 * 1_000;

const SHA256_SIGNATURE_PATTERN = /^sha256:[a-f0-9]{64}$/;

export type ReviewPlanStep = {
  id: string;
  sourceTaskId: string | null;
  content: string;
  priority: string;
  enabled: boolean;
};

export type NewTaskDefinition = {
  title: string;
  objective: string;
  kind: NewTaskKind;
  workspaceRoot?: string;
  contextSources?: NewTaskContextSource[];
};

export function newTaskDefinitionSignature(
  definition: NewTaskDefinition,
  workspaceSelection: string,
): string {
  return JSON.stringify({
    title: definition.title.trim(),
    objective: definition.objective.trim(),
    kind: definition.kind,
    workspaceSelection: workspaceSelection.trim(),
  });
}

export function planningTurnAttempt(
  current: PlanningTurnAttempt | null,
  fingerprint: string,
  createMessageId: () => string,
): PlanningTurnAttempt {
  if (current?.fingerprint === fingerprint) return current;
  return { fingerprint, messageId: createMessageId() };
}

// Keep the original key namespace so schema-v1 records are rejected and removed in place.
const LEGACY_PLAN_APPROVAL_RECOVERY_KEY_PREFIX =
  'memstack.desktop.legacy-plan-approval.v1:';

function legacyPlanApprovalRecoveryKey(conversationId: string): string {
  return `${LEGACY_PLAN_APPROVAL_RECOVERY_KEY_PREFIX}${conversationId.trim()}`;
}

export function browserLegacyPlanApprovalStorage(): LegacyPlanApprovalStorage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function legacyPlanApprovalRuntimeScope(
  config: Pick<
    DesktopRuntimeConfig,
    'apiBaseUrl' | 'mode' | 'tenantId' | 'projectId'
  >,
): string {
  let normalizedApiBaseUrl: string;
  try {
    const url = new URL(config.apiBaseUrl.trim());
    if (
      (url.protocol !== 'http:' && url.protocol !== 'https:') ||
      url.username ||
      url.password ||
      url.search ||
      url.hash
    ) {
      return '';
    }
    const path = url.pathname.replace(/\/+$/, '') || '/';
    normalizedApiBaseUrl = `${url.origin.toLowerCase()}${path}`;
  } catch {
    return '';
  }
  const digest = canonicalJsonSha256({
    apiBaseUrl: normalizedApiBaseUrl,
    mode: config.mode,
    tenantId: config.tenantId.trim(),
    projectId: config.projectId.trim(),
  });
  return digest ? `sha256:${digest}` : '';
}

export function createLegacyPlanApprovalRecovery(
  conversationId: string,
  planSignature: string,
  messageId: string,
  runtimeScope: string,
  createdAt = Date.now(),
): LegacyPlanApprovalRecovery {
  return {
    schemaVersion: 2,
    conversationId: conversationId.trim(),
    runtimeScope,
    planSignature,
    messageId: messageId.trim(),
    createdAt,
    expiresAt: createdAt + LEGACY_PLAN_APPROVAL_TTL_MS,
  };
}

export function writeLegacyPlanApprovalRecovery(
  storage: LegacyPlanApprovalStorage | null,
  recovery: LegacyPlanApprovalRecovery,
): boolean {
  if (
    !storage ||
    !recovery.conversationId ||
    recovery.conversationId.length > 256 ||
    !SHA256_SIGNATURE_PATTERN.test(recovery.runtimeScope) ||
    !SHA256_SIGNATURE_PATTERN.test(recovery.planSignature) ||
    !recovery.messageId ||
    recovery.messageId.length > 255 ||
    !Number.isSafeInteger(recovery.createdAt) ||
    !Number.isSafeInteger(recovery.expiresAt) ||
    recovery.expiresAt !== recovery.createdAt + LEGACY_PLAN_APPROVAL_TTL_MS
  ) {
    return false;
  }
  try {
    const serialized = JSON.stringify(recovery);
    const key = legacyPlanApprovalRecoveryKey(recovery.conversationId);
    storage.setItem(key, serialized);
    return storage.getItem(key) === serialized;
  } catch {
    return false;
  }
}

export function readLegacyPlanApprovalRecovery(
  storage: LegacyPlanApprovalStorage | null,
  conversationId: string,
  planSignature: string,
  runtimeScope: string,
  now = Date.now(),
): LegacyPlanApprovalRecovery | null {
  const scopedConversationId = conversationId.trim();
  if (
    !storage ||
    !scopedConversationId ||
    !SHA256_SIGNATURE_PATTERN.test(planSignature) ||
    !SHA256_SIGNATURE_PATTERN.test(runtimeScope)
  ) {
    return null;
  }
  const key = legacyPlanApprovalRecoveryKey(scopedConversationId);
  try {
    const serialized = storage.getItem(key);
    if (!serialized) return null;
    const candidate = JSON.parse(serialized) as Partial<LegacyPlanApprovalRecovery>;
    if (
      candidate.schemaVersion !== 2 ||
      candidate.conversationId !== scopedConversationId ||
      candidate.runtimeScope !== runtimeScope ||
      candidate.planSignature !== planSignature ||
      typeof candidate.messageId !== 'string' ||
      !candidate.messageId.trim() ||
      candidate.messageId.length > 255 ||
      !Number.isSafeInteger(candidate.createdAt) ||
      !Number.isSafeInteger(candidate.expiresAt) ||
      candidate.expiresAt !==
        (candidate.createdAt as number) + LEGACY_PLAN_APPROVAL_TTL_MS ||
      (candidate.expiresAt as number) <= now
    ) {
      storage.removeItem(key);
      return null;
    }
    return createLegacyPlanApprovalRecovery(
      scopedConversationId,
      planSignature,
      candidate.messageId,
      runtimeScope,
      candidate.createdAt as number,
    );
  } catch {
    try {
      storage.removeItem(key);
    } catch {
      // Storage remains fail-closed when a corrupt record cannot be removed.
    }
    return null;
  }
}

export function clearLegacyPlanApprovalRecovery(
  storage: LegacyPlanApprovalStorage | null,
  conversationId: string,
): boolean {
  const scopedConversationId = conversationId.trim();
  if (!storage || !scopedConversationId) return false;
  try {
    const key = legacyPlanApprovalRecoveryKey(scopedConversationId);
    storage.removeItem(key);
    return storage.getItem(key) === null;
  } catch {
    return false;
  }
}

export function canResumeLegacyPlanApproval(
  currentMode: string,
  hasAcceptedAttempt: boolean,
  planSignature: string,
  recovery: LegacyPlanApprovalRecovery | null,
): boolean {
  if (currentMode === 'plan') return true;
  return Boolean(
    currentMode === 'build' &&
      !hasAcceptedAttempt &&
      planSignature &&
      recovery?.planSignature === planSignature,
  );
}

export function isFreshPlanningPlan(
  tasks: ReadonlyArray<unknown>,
  signature: string,
  baselineSignature: string,
  versionChanged: boolean,
): boolean {
  return tasks.length > 0 && (versionChanged || signature !== baselineSignature);
}

export function canActivateNewTaskSession(
  workspaceId: string,
  conversationWorkspaceId: string | null | undefined,
  outcome: NewTaskAgentTurnOutcome,
): boolean {
  return (
    Boolean(workspaceId) &&
    conversationWorkspaceId === workspaceId &&
    (outcome === 'acknowledged' || outcome === 'unknown_outcome')
  );
}

export function buildPlanningPrompt(definition: NewTaskDefinition): string {
  const codeContext =
    definition.kind === 'programming'
      ? `\nCode workspace: ${definition.workspaceRoot?.trim() || 'Use the configured workspace root.'}`
      : '';
  const context = definition.contextSources?.length
    ? definition.contextSources.join(', ')
    : 'current project and workspace context';
  return [
    'Work in Plan mode. Analyze the objective without changing files or executing the solution.',
    'Inspect only the context needed to make the plan concrete.',
    'Publish the final plan through the available structured task-list tool.',
    'On MemStack cloud use todowrite with action="replace". In the local desktop runtime call submit_plan with JSON input {"tasks":[{"content":"actionable step","priority":"high|medium|low"}]}.',
    'Every task must be actionable, ordered, and independently reviewable by a human.',
    'Do not start implementation until the human explicitly approves the plan.',
    `Task title: ${definition.title.trim()}`,
    `Objective: ${definition.objective.trim()}${codeContext}`,
    `Requested planning context (guidance, not an access-control boundary): ${context}`,
  ].join('\n\n');
}

export function buildRevisionPrompt(feedback: string): string {
  return [
    'The human reviewed the current plan and requested a revision.',
    `Feedback: ${feedback.trim()}`,
    'Remain in Plan mode. Update the structured task list in full and do not implement anything.',
  ].join('\n\n');
}

export function buildExecutionPrompt(): string {
  return [
    'The human approved the current structured plan.',
    'Build mode is now active. Execute the approved tasks in order.',
    'Keep the task list status current and pause for any permission, credential, or irreversible decision.',
  ].join('\n\n');
}

export function newTaskAgentTurnTransport(
  mode: 'local' | 'cloud',
  socketQueued: boolean,
): 'socket' | 'local_http' | 'cloud_socket_queue' {
  if (socketQueued) return 'socket';
  return mode === 'local' ? 'local_http' : 'cloud_socket_queue';
}

export function newTaskAgentTurnResolution(
  signal: {
    conversationId: string;
    messageId?: string;
    status: string;
  },
  conversationId: string,
  messageId: string,
): 'acknowledged' | 'failed' | null {
  if (signal.conversationId !== conversationId) return null;
  if (!signal.messageId || signal.messageId !== messageId) return null;
  return signal.status === 'acknowledged' || signal.status === 'failed' ? signal.status : null;
}

export function createReviewPlanDraft(tasks: AgentPlanTask[]): ReviewPlanStep[] {
  return orderedPlanTasks(tasks).map((task) => ({
    id: task.id,
    sourceTaskId: task.id,
    content: task.content,
    priority: task.priority || 'medium',
    enabled: true,
  }));
}

export function enabledReviewPlanSteps(steps: ReviewPlanStep[]): ReviewPlanStep[] {
  return steps.filter((step) => step.enabled && step.content.trim().length > 0);
}

export function hasReviewPlanChanges(
  tasks: AgentPlanTask[],
  steps: ReviewPlanStep[],
): boolean {
  const source = createReviewPlanDraft(tasks);
  if (source.length !== steps.length) return true;
  return source.some((step, index) => {
    const candidate = steps[index];
    return (
      !candidate ||
      !candidate.enabled ||
      candidate.sourceTaskId !== step.sourceTaskId ||
      candidate.content.trim() !== step.content.trim() ||
      candidate.priority !== step.priority
    );
  });
}

export function buildPlanReplacementPrompt(steps: ReviewPlanStep[]): string {
  const payloads = buildPlanReplacementPayloads(steps);
  return [
    'The human explicitly edited the current plan in the review interface.',
    'Remain in Plan mode. Replace the structured task list in full and do not implement anything.',
    'Publish the replacement through the available structured task-list tool.',
    `Cloud todowrite input: ${JSON.stringify(payloads.cloud)}`,
    `Local submit_plan input: ${JSON.stringify(payloads.local)}`,
  ].join('\n\n');
}

export function buildPlanReplacementPayloads(steps: ReviewPlanStep[]) {
  const tasks = enabledReviewPlanSteps(steps).map((step) => ({
    content: step.content.trim(),
    priority: step.priority || 'medium',
  }));
  return {
    cloud: { action: 'replace' as const, todos: tasks },
    local: { tasks },
  };
}

export function shouldOfferPlanRetry(emptyPollCount: number): boolean {
  return emptyPollCount >= PLAN_EMPTY_POLL_RETRY_THRESHOLD;
}

export function planPriorityTranslationKey(priority: string): string {
  if (priority === 'high') return 'task.priorityHigh';
  if (priority === 'medium') return 'task.priorityMedium';
  if (priority === 'low') return 'task.priorityLow';
  return 'task.priorityUnknown';
}

export function planTaskSignature(tasks: AgentPlanTask[]): string {
  if (!tasks.length) return '';
  const digest = canonicalJsonSha256(
    [...tasks]
      .sort((left, right) => left.order_index - right.order_index)
      .map((task) => [
        task.id,
        task.conversation_id,
        task.order_index,
        task.status,
        task.priority,
        task.content,
        task.updated_at || '',
      ]),
  );
  return digest ? `sha256:${digest}` : '';
}

export function orderedPlanTasks(tasks: AgentPlanTask[]): AgentPlanTask[] {
  return [...tasks].sort((left, right) => left.order_index - right.order_index);
}
