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
export type MyWorkDisplayGroup = 'needs_input' | 'running' | 'ready_review';

export const MY_WORK_DISPLAY_GROUPS: readonly MyWorkDisplayGroup[] = Object.freeze([
  'needs_input',
  'running',
  'ready_review',
]);

export const MY_WORK_DISPLAY_GROUP_BY_AUTHORITY_GROUP: Readonly<
  Record<MyWorkGroup, MyWorkDisplayGroup>
> = Object.freeze({
  needs_input: 'needs_input',
  needs_approval: 'needs_input',
  running: 'running',
  ready_review: 'ready_review',
});

export type MyWorkDisplayGroupItems = Readonly<{
  group: MyWorkDisplayGroup;
  items: ProjectWorkItem[];
}>;

export type MyWorkRefreshScope = Readonly<{
  contextRevision: number;
  scopeEpoch: number;
}>;

export type MyWorkAuthorityPresentation = {
  sourceKey: string;
  descriptionKey: string;
  identifier: string;
  sequence: { labelKey: string; value: string } | null;
  runtime: {
    runId: string | null;
    revision: number | null;
    permissionProfile: ProjectWorkItem['permission_profile'];
    environment: ProjectWorkItem['environment'];
    lastHeartbeatAt: string | null;
  } | null;
};

const myWorkInvalidationEventTypes = new Set([
  'run_status',
  'clarification_asked',
  'clarification_answered',
  'decision_asked',
  'decision_answered',
  'env_var_requested',
  'env_var_provided',
  'permission_asked',
  'permission_replied',
  'a2ui_action_asked',
  'a2ui_action_answered',
  'hitl_responded',
  'review_decision',
  'recovery_forked',
]);

export function myWorkItemKey(
  item: Pick<ProjectWorkItem, 'authority_kind' | 'authority_id'>,
): string {
  return `${item.authority_kind}:${item.authority_id}`;
}

export function myWorkDisplayGroupForAuthorityGroup(
  group: MyWorkGroup,
): MyWorkDisplayGroup {
  return MY_WORK_DISPLAY_GROUP_BY_AUTHORITY_GROUP[group];
}

export function myWorkItemMatchesMode(
  item: Pick<ProjectWorkItem, 'capability_mode'>,
  mode: MyWorkModeFilter,
): boolean {
  return mode === 'all' || item.capability_mode === null || item.capability_mode === mode;
}

export function filterMyWorkItems(
  items: ProjectWorkItem[],
  group: MyWorkGroup | 'all',
  mode: MyWorkModeFilter,
  query = '',
): ProjectWorkItem[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  return items
    .filter((item) => group === 'all' || item.group === group)
    .filter((item) => myWorkItemMatchesMode(item, mode))
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

export function filterMyWorkDisplayItems(
  items: ProjectWorkItem[],
  group: MyWorkDisplayGroup | 'all' = 'all',
  mode: MyWorkModeFilter = 'all',
): ProjectWorkItem[] {
  return filterMyWorkItems(items, 'all', mode).filter(
    (item) =>
      group === 'all' || myWorkDisplayGroupForAuthorityGroup(item.group) === group,
  );
}

export function groupMyWorkDisplayItems(
  items: ProjectWorkItem[],
  mode: MyWorkModeFilter = 'all',
): MyWorkDisplayGroupItems[] {
  const visibleItems = filterMyWorkDisplayItems(items, 'all', mode);
  return MY_WORK_DISPLAY_GROUPS.map((group) => ({
    group,
    items: visibleItems.filter(
      (item) => myWorkDisplayGroupForAuthorityGroup(item.group) === group,
    ),
  }));
}

export function countMyWorkDisplayGroups(
  items: ProjectWorkItem[],
  mode: MyWorkModeFilter = 'all',
): Record<MyWorkDisplayGroup, number> {
  return filterMyWorkDisplayItems(items, 'all', mode).reduce<
    Record<MyWorkDisplayGroup, number>
  >(
    (counts, item) => {
      counts[myWorkDisplayGroupForAuthorityGroup(item.group)] += 1;
      return counts;
    },
    { needs_input: 0, running: 0, ready_review: 0 },
  );
}

export function describeMyWorkAuthority(
  item: Pick<
    ProjectWorkItem,
    | 'authority_kind'
    | 'authority_id'
    | 'run_id'
    | 'revision'
    | 'attempt_number'
    | 'permission_profile'
    | 'environment'
    | 'last_heartbeat_at'
  >,
): MyWorkAuthorityPresentation {
  const authorityKind: string = item.authority_kind;
  const identifier = item.authority_id;

  if (authorityKind === 'desktop_run') {
    return {
      sourceKey: 'myWork.authorityKind.desktop_run',
      descriptionKey: 'myWork.authorityDescription.desktop_run',
      identifier,
      sequence:
        item.revision === null
          ? null
          : { labelKey: 'myWork.runRevisionLabel', value: String(item.revision) },
      runtime: {
        runId: item.run_id,
        revision: item.revision,
        permissionProfile: item.permission_profile,
        environment: item.environment,
        lastHeartbeatAt: item.last_heartbeat_at ?? null,
      },
    };
  }

  if (authorityKind === 'workspace_attempt') {
    return {
      sourceKey: 'myWork.authorityKind.workspace_attempt',
      descriptionKey: 'myWork.authorityDescription.workspace_attempt',
      identifier,
      sequence:
        item.attempt_number === null
          ? null
          : { labelKey: 'myWork.attemptNumber', value: String(item.attempt_number) },
      runtime: null,
    };
  }

  if (authorityKind === 'hitl_request') {
    return {
      sourceKey: 'myWork.authorityKind.hitl_request',
      descriptionKey: 'myWork.authorityDescription.hitl_request',
      identifier,
      sequence: null,
      runtime: null,
    };
  }

  return {
    sourceKey: 'myWork.authorityKind.unknown',
    descriptionKey: 'myWork.authorityDescription.unknown',
    identifier,
    sequence: null,
    runtime: null,
  };
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

export function myWorkRefreshScopeIsCurrent(
  expected: MyWorkRefreshScope,
  current: MyWorkRefreshScope,
): boolean {
  return (
    expected.contextRevision === current.contextRevision &&
    expected.scopeEpoch === current.scopeEpoch
  );
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
