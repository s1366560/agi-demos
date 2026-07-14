import type {
  DesktopArtifactDelivery,
  DesktopArtifactVersion,
  DesktopRun,
  PlanSnapshot,
  WorkspaceConversationExecution,
  WorkspaceTask,
} from '../../types';

export function socketEventBelongsToConversation(
  event: unknown,
  conversationId: string,
): boolean {
  return eventScopeState(event, ['conversation_id', 'conversationId'], conversationId) === 'match';
}

export function socketEventMatchesSessionScope(
  event: unknown,
  scope: { conversationId: string; workspaceId: string | null },
  allowWorkspaceOnly: boolean,
): boolean {
  const conversation = eventScopeState(
    event,
    ['conversation_id', 'conversationId'],
    scope.conversationId,
  );
  const workspace = eventScopeState(event, ['workspace_id', 'workspaceId'], scope.workspaceId);
  if (conversation === 'conflict' || workspace === 'conflict') return false;
  if (conversation === 'match') return true;
  return allowWorkspaceOnly && workspace === 'match';
}

export function taskBelongsToConversation(
  task: WorkspaceTask,
  conversationId: string,
): boolean {
  const record = task as Record<string, unknown>;
  const metadata = asRecord(task.metadata);
  return [record, metadata]
    .filter((candidate): candidate is Record<string, unknown> => Boolean(candidate))
    .some((candidate) => conversationIdFromRecord(candidate) === conversationId);
}

export function planBelongsToConversation(
  plan: PlanSnapshot | null,
  conversationId: string,
): boolean {
  if (!plan) return false;
  if (rootPlanBelongsToConversation(plan, conversationId)) return true;
  return conversationPlanRecord(plan, conversationId) !== null;
}

export function planForConversation(
  plan: PlanSnapshot | null,
  conversationId: string,
): PlanSnapshot | null {
  if (!plan) return null;
  if (rootPlanBelongsToConversation(plan, conversationId)) return plan;
  const conversationPlan = conversationPlanRecord(plan, conversationId);
  if (!conversationPlan) return null;
  const run = asRecord(conversationPlan.run);
  const planHistory = Array.isArray(plan.plan_history)
    ? plan.plan_history.filter((item) => {
        const record = asRecord(item);
        return record ? conversationIdFromRecord(record) === conversationId : false;
      })
    : [];
  return {
    workspace_id: stringValue(plan.workspace_id),
    project_id: stringValue(plan.project_id),
    conversation_id: conversationId,
    plan: asRecord(conversationPlan.plan),
    conversation_plans: [conversationPlan as WorkspaceConversationExecution],
    plan_history: planHistory,
    run_health: run ? [run as DesktopRun] : [],
    pending_hitl: recordArray(conversationPlan.pending_hitl),
    delivery: recordArray(conversationPlan.delivery) as DesktopArtifactDelivery[],
    artifact_index: recordArray(conversationPlan.artifacts) as DesktopArtifactVersion[],
  };
}

function rootPlanBelongsToConversation(
  plan: PlanSnapshot,
  conversationId: string,
): boolean {
  const metadata = asRecord(plan.metadata);
  return [plan, metadata]
    .filter((candidate): candidate is Record<string, unknown> => Boolean(candidate))
    .some((candidate) => conversationIdFromRecord(candidate) === conversationId);
}

function conversationPlanRecord(
  plan: PlanSnapshot,
  conversationId: string,
): Record<string, unknown> | null {
  if (!Array.isArray(plan.conversation_plans)) return null;
  for (const value of plan.conversation_plans) {
    const record = asRecord(value);
    if (record && conversationIdFromRecord(record) === conversationId) return record;
  }
  return null;
}

function conversationIdFromRecord(record: Record<string, unknown>): string | null {
  const value = record.conversation_id ?? record.conversationId;
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

type EventScopeState = 'absent' | 'match' | 'conflict';

function eventScopeState(
  event: unknown,
  keys: readonly string[],
  expected: string | null,
): EventScopeState {
  const values = new Set<string>();
  for (const record of eventRecords(event)) {
    for (const key of keys) {
      const value = record[key];
      if (typeof value === 'string' && value.trim()) values.add(value.trim());
    }
  }
  if (!values.size) return 'absent';
  return expected !== null && values.size === 1 && values.has(expected) ? 'match' : 'conflict';
}

function eventRecords(event: unknown): Record<string, unknown>[] {
  const root = asRecord(event);
  if (!root) return [];
  const records: Record<string, unknown>[] = [];
  const queue = [root];
  const seen = new Set<Record<string, unknown>>();
  while (queue.length) {
    const record = queue.shift();
    if (!record || seen.has(record)) continue;
    seen.add(record);
    records.push(record);
    for (const key of ['payload', 'data']) {
      const nested = asRecord(record[key]);
      if (nested) queue.push(nested);
    }
  }
  return records;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function recordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => asRecord(item) !== null)
    : [];
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}
