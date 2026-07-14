import type {
  AgentCapabilityMode,
  AgentConversation,
  MyWorkGroup,
  ProjectWorkItem,
} from '../../types';

export const MY_WORK_GROUPS: MyWorkGroup[] = [
  'needs_input',
  'needs_approval',
  'running',
  'ready_review',
];

export type MyWorkModeFilter = 'all' | AgentCapabilityMode;

const myWorkInvalidationEventTypes = new Set([
  'run_status',
  'clarification_asked',
  'decision_asked',
  'env_var_requested',
  'permission_asked',
  'hitl_responded',
  'review_decision',
  'recovery_forked',
]);

export function filterMyWorkItems(
  items: ProjectWorkItem[],
  group: MyWorkGroup | 'all',
  mode: MyWorkModeFilter,
  query = '',
): ProjectWorkItem[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  return items
    .filter((item) => group === 'all' || item.group === group)
    .filter((item) => mode === 'all' || item.capability_mode === mode)
    .filter(
      (item) =>
        !normalizedQuery || item.title.toLocaleLowerCase().includes(normalizedQuery),
    )
    .sort(
      (left, right) =>
        Date.parse(right.updated_at || right.created_at) -
        Date.parse(left.updated_at || left.created_at),
    );
}

export function countMyWorkGroups(items: ProjectWorkItem[]): Record<MyWorkGroup, number> {
  return MY_WORK_GROUPS.reduce<Record<MyWorkGroup, number>>(
    (counts, group) => {
      counts[group] = items.filter((item) => item.group === group).length;
      return counts;
    },
    { needs_input: 0, needs_approval: 0, running: 0, ready_review: 0 },
  );
}

export function socketEventInvalidatesMyWork(event: unknown): boolean {
  if (!event || typeof event !== 'object' || Array.isArray(event)) return false;
  const queue = [event as Record<string, unknown>];
  const seen = new Set<Record<string, unknown>>();
  while (queue.length) {
    const current = queue.shift();
    if (!current || seen.has(current)) continue;
    seen.add(current);
    const eventType =
      typeof current.event_type === 'string'
        ? current.event_type
        : typeof current.type === 'string'
          ? current.type
          : null;
    if (eventType && myWorkInvalidationEventTypes.has(eventType)) return true;
    for (const key of ['payload', 'data']) {
      const nested = current[key];
      if (nested && typeof nested === 'object' && !Array.isArray(nested)) {
        queue.push(nested as Record<string, unknown>);
      }
    }
  }
  return false;
}

export function myWorkConversationMatchesScope(
  item: ProjectWorkItem,
  conversation: AgentConversation,
  context: { tenantId: string; projectId: string },
): boolean {
  return (
    Boolean(item.workspace_id) &&
    item.project_id === context.projectId &&
    conversation.id === item.conversation_id &&
    conversation.tenant_id === context.tenantId &&
    conversation.project_id === context.projectId &&
    conversation.workspace_id === item.workspace_id
  );
}
