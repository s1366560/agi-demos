import type { AgentPlanTask } from '../../types';

export type NewTaskKind = 'general' | 'programming';
export type NewTaskContextSource = 'project_memory' | 'project_files' | 'web_research';

export const PLAN_EMPTY_POLL_RETRY_THRESHOLD = 8;

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
): 'socket' | 'local_http' | 'live_socket_required' {
  if (socketQueued) return 'socket';
  return mode === 'local' ? 'local_http' : 'live_socket_required';
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
  return [...tasks]
    .sort((left, right) => left.order_index - right.order_index)
    .map((task) => `${task.order_index}:${task.priority}:${task.content}:${task.updated_at}`)
    .join('|');
}

export function orderedPlanTasks(tasks: AgentPlanTask[]): AgentPlanTask[] {
  return [...tasks].sort((left, right) => left.order_index - right.order_index);
}
