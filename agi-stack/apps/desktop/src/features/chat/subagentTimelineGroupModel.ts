import type { AgentTimelineItem } from '../../types';
import { agentLifecyclePresentation } from './agentLifecyclePresentationModel';

export type SubAgentTimelineGroupMode = 'single' | 'parallel' | 'chain';

export type SubAgentTimelineGroupStatus =
  | 'running'
  | 'success'
  | 'error'
  | 'background'
  | 'queued'
  | 'killed'
  | 'steered'
  | 'depth_limited';

export type SubAgentTimelineGroup = {
  id: string;
  startItemId: string;
  itemIds: string[];
  items: AgentTimelineItem[];
  mode: SubAgentTimelineGroupMode;
  subagentId: string;
  subagentName: string;
  status: SubAgentTimelineGroupStatus;
  task: string;
  reason: string;
  summary: string;
  error: string;
  confidence: number | null;
  tokensUsed: number | null;
  executionTimeMs: number | null;
  progress: number | null;
  statusMessage: string;
  toolCallsCount: number | null;
  phases: {
    routed: boolean;
    started: boolean;
    executing: boolean;
    ended: boolean;
  };
};

export type SubAgentTimelineGrouping = {
  groups: SubAgentTimelineGroup[];
  claimedItemIds: string[];
};

const orchestrationEventTypes = new Set([
  'parallel_started',
  'parallel_completed',
  'chain_started',
  'chain_step_started',
  'chain_step_completed',
  'chain_completed',
  'background_launched',
]);

const terminalEventTypes = new Set([
  'subagent_completed',
  'subagent_failed',
  'subagent_run_completed',
  'subagent_run_failed',
  'subagent_announce_giveup',
  'subagent_announce_expired',
  'subagent_killed',
  'subagent_doom_loop',
  'subagent_depth_limited',
  'subagent_spawn_rejected',
  'subagent_orphan_detected',
  'parallel_completed',
  'chain_completed',
  'background_launched',
]);

const startedEventTypes = new Set([
  'subagent_spawning',
  'subagent_started',
  'subagent_run_started',
  'subagent_session_spawned',
  'parallel_started',
  'chain_started',
]);

const executingEventTypes = new Set([
  'subagent_session_update',
  'subagent_session_message_sent',
  'subagent_steered',
  'subagent_retry',
  'subagent_announce_retry',
  'chain_step_started',
  'chain_step_completed',
]);

/**
 * Build Web-compatible SubAgent lifecycle groups without parsing narrative text.
 * Identity matching uses only structured protocol ids/names and fails closed when
 * two executions cannot be proven to be the same lifecycle.
 */
export function groupSubAgentTimelineItems(
  items: readonly AgentTimelineItem[],
): SubAgentTimelineGrouping {
  const groups: SubAgentTimelineGroup[] = [];
  const claimedIndexes = new Set<number>();

  for (let index = 0; index < items.length; index += 1) {
    const first = items[index];
    if (!first || claimedIndexes.has(index) || !isSubAgentGroupingEvent(first)) continue;

    const groupedIndexes = [index];
    const groupedItems = [first];
    let cursor = index + 1;
    while (cursor < items.length) {
      const candidate = items[cursor];
      if (
        !candidate ||
        claimedIndexes.has(cursor) ||
        !isSubAgentGroupingEvent(candidate) ||
        !compatibleSubAgentEvent(groupedItems, candidate)
      ) {
        break;
      }
      groupedIndexes.push(cursor);
      groupedItems.push(candidate);
      cursor += 1;
      if (terminalEventTypes.has(candidate.type)) break;
    }

    if (!groupedItems.some((item) => terminalEventTypes.has(item.type))) {
      const terminalIndex = findMatchingTerminalIndex(items, cursor, groupedItems, claimedIndexes);
      if (terminalIndex !== null) {
        groupedIndexes.push(terminalIndex);
        groupedItems.push(items[terminalIndex] as AgentTimelineItem);
      }
    }

    groupedIndexes.forEach((claimedIndex) => claimedIndexes.add(claimedIndex));
    groups.push(buildSubAgentTimelineGroup(groupedItems));
  }

  return {
    groups,
    claimedItemIds: items.flatMap((item, index) => (claimedIndexes.has(index) ? [item.id] : [])),
  };
}

function findMatchingTerminalIndex(
  items: readonly AgentTimelineItem[],
  startIndex: number,
  groupedItems: readonly AgentTimelineItem[],
  claimedIndexes: ReadonlySet<number>,
): number | null {
  const identity = groupIdentity(groupedItems);
  if (!identity.id && !identity.name && !identity.route) return null;
  for (let index = startIndex; index < items.length; index += 1) {
    const candidate = items[index];
    if (
      candidate &&
      !claimedIndexes.has(index) &&
      terminalEventTypes.has(candidate.type) &&
      compatibleSubAgentEvent(groupedItems, candidate)
    ) {
      return index;
    }
  }
  return null;
}

function compatibleSubAgentEvent(
  items: readonly AgentTimelineItem[],
  candidate: AgentTimelineItem,
): boolean {
  const first = items[0];
  if (!first || groupMode(first) !== groupMode(candidate)) return false;
  const known = groupIdentity(items);
  const incoming = eventIdentity(candidate);
  if (known.id && incoming.id) return known.id === incoming.id;
  if (known.name && incoming.name) return known.name === incoming.name;
  if (known.route && incoming.route) return known.route === incoming.route;
  return !known.id && !known.name && !known.route && !incoming.id && !incoming.name && !incoming.route;
}

function groupIdentity(items: readonly AgentTimelineItem[]): SubAgentIdentity {
  const identity: SubAgentIdentity = { id: '', name: '', route: '' };
  for (const item of items) {
    const candidate = eventIdentity(item);
    identity.id ||= candidate.id;
    identity.name ||= candidate.name;
    identity.route ||= candidate.route;
  }
  return identity;
}

type SubAgentIdentity = { id: string; name: string; route: string };

function eventIdentity(item: AgentTimelineItem): SubAgentIdentity {
  if (item.type === 'subagent_delegation') {
    return {
      id: eventString(item, ['to_subagent_id', 'toSubagentId']),
      name: eventString(item, ['to_subagent_name', 'toSubagentName']),
      route: eventString(item, ['conversation_id', 'conversationId']),
    };
  }
  if (item.type === 'subagent_announce_sent') {
    return {
      id: eventString(item, ['agent_id', 'agentId']),
      name: eventString(item, ['agent_name', 'agentName']),
      route: eventString(item, ['session_id', 'sessionId']),
    };
  }
  if (item.type === 'subagent_announce_received') {
    return {
      id: eventString(item, ['from_agent_id', 'fromAgentId']),
      name: eventString(item, ['from_agent_name', 'fromAgentName']),
      route: eventString(item, ['session_id', 'sessionId']),
    };
  }
  return {
    id: eventString(item, ['subagent_id', 'subagentId', 'run_id', 'runId']),
    name: eventString(item, ['subagent_name', 'subagentName']),
    route: eventString(item, [
      'route_id',
      'routeId',
      'trace_id',
      'traceId',
      'session_id',
      'sessionId',
    ]),
  };
}

function buildSubAgentTimelineGroup(items: AgentTimelineItem[]): SubAgentTimelineGroup {
  const first = items[0] as AgentTimelineItem;
  const last = items[items.length - 1] as AgentTimelineItem;
  const identity = groupIdentity(items);
  let status: SubAgentTimelineGroupStatus = 'running';
  let task = '';
  let reason = '';
  let summary = '';
  let error = '';
  let confidence: number | null = null;
  let tokensUsed: number | null = null;
  let executionTimeMs: number | null = null;
  let progress: number | null = null;
  let statusMessage = '';
  let toolCallsCount: number | null = null;

  for (const item of items) {
    task = latestString(task, eventString(item, ['task', 'task_description', 'taskDescription']));
    if (item.type === 'subagent_steered') {
      task = latestString(task, eventString(item, ['instruction']));
    }
    reason = latestString(reason, eventString(item, ['reason', 'match_reason', 'matchReason']));
    summary = latestString(
      summary,
      eventString(item, ['summary', 'final_content', 'finalContent', 'result_preview', 'resultPreview']),
    );
    error = latestString(
      error,
      eventString(item, [
        'error',
        'kill_reason',
        'killReason',
        'rejection_reason',
        'rejectionReason',
        'last_error',
        'lastError',
      ]),
    );
    confidence = latestNumber(confidence, eventNumber(item, ['confidence']));
    tokensUsed = latestNumber(tokensUsed, eventNumber(item, ['tokens_used', 'tokensUsed']));
    executionTimeMs = latestNumber(
      executionTimeMs,
      eventNumber(item, ['execution_time_ms', 'executionTimeMs', 'total_time_ms', 'totalTimeMs']),
    );
    progress = latestNumber(progress, eventNumber(item, ['progress']));
    statusMessage = latestString(
      statusMessage,
      eventString(item, ['status_message', 'statusMessage']),
    );
    toolCallsCount = latestNumber(
      toolCallsCount,
      eventNumber(item, ['tool_calls_count', 'toolCallsCount']),
    );
    status = subAgentStatus(item, status);
  }

  if (status === 'success') progress = 100;
  return {
    id: `subagent-group:${first.id}:${last.id}`,
    startItemId: first.id,
    itemIds: items.map((item) => item.id),
    items,
    mode: groupMode(first),
    subagentId: identity.id,
    subagentName:
      identity.name || eventString(first, ['chain_name', 'chainName']) || identity.id,
    status,
    task,
    reason,
    summary,
    error,
    confidence,
    tokensUsed,
    executionTimeMs,
    progress,
    statusMessage,
    toolCallsCount,
    phases: {
      routed: items.some(
        (item) => item.type === 'subagent_routed' || item.type === 'subagent_delegation',
      ),
      started: items.some((item) => startedEventTypes.has(item.type)),
      executing: items.some((item) => executingEventTypes.has(item.type)),
      ended: items.some(
        (item) =>
          terminalEventTypes.has(item.type) || item.type === 'subagent_announce_received',
      ),
    },
  };
}

function subAgentStatus(
  item: AgentTimelineItem,
  current: SubAgentTimelineGroupStatus,
): SubAgentTimelineGroupStatus {
  if (
    item.type === 'subagent_failed' ||
    item.type === 'subagent_run_failed' ||
    item.type === 'subagent_announce_giveup' ||
    item.type === 'subagent_announce_expired' ||
    item.type === 'subagent_spawn_rejected' ||
    item.type === 'subagent_orphan_detected' ||
    item.type === 'subagent_doom_loop'
  ) {
    return 'error';
  }
  if (item.type === 'subagent_killed') return 'killed';
  if (item.type === 'subagent_depth_limited') return 'depth_limited';
  if (item.type === 'subagent_queued') return 'queued';
  if (item.type === 'background_launched') return 'background';
  if (item.type === 'subagent_steered') return 'steered';
  if (
    item.type === 'subagent_announce_sent' ||
    item.type === 'subagent_announce_received'
  ) {
    return 'success';
  }
  if (
    item.type === 'subagent_completed' ||
    item.type === 'subagent_run_completed' ||
    item.type === 'parallel_completed' ||
    item.type === 'chain_completed'
  ) {
    return eventBoolean(item, ['success']) === false ? 'error' : 'success';
  }
  const explicitStatus = eventString(item, ['status']).toLowerCase();
  if (explicitStatus === 'completed' || explicitStatus === 'success') return 'success';
  if (explicitStatus === 'failed' || explicitStatus === 'error') return 'error';
  return current;
}

function groupMode(item: AgentTimelineItem): SubAgentTimelineGroupMode {
  if (item.type.startsWith('parallel_')) return 'parallel';
  if (item.type.startsWith('chain_')) return 'chain';
  return 'single';
}

function isSubAgentGroupingEvent(item: AgentTimelineItem): boolean {
  return (
    agentLifecyclePresentation(item)?.family === 'subagent' ||
    orchestrationEventTypes.has(item.type)
  );
}

function eventRecords(item: AgentTimelineItem): Record<string, unknown>[] {
  const records: Record<string, unknown>[] = [item];
  for (const value of [item.payload, item.data, item.metadata]) {
    if (isRecord(value)) records.push(value);
  }
  return records;
}

function eventString(item: AgentTimelineItem, keys: readonly string[]): string {
  for (const record of eventRecords(item)) {
    for (const key of keys) {
      const value = record[key];
      if (typeof value === 'string' && value.trim()) return value.trim();
    }
  }
  return '';
}

function eventNumber(item: AgentTimelineItem, keys: readonly string[]): number | null {
  for (const record of eventRecords(item)) {
    for (const key of keys) {
      const value = record[key];
      if (typeof value === 'number' && Number.isFinite(value)) return value;
    }
  }
  return null;
}

function eventBoolean(item: AgentTimelineItem, keys: readonly string[]): boolean | null {
  for (const record of eventRecords(item)) {
    for (const key of keys) {
      const value = record[key];
      if (typeof value === 'boolean') return value;
    }
  }
  return null;
}

function latestString(current: string, next: string): string {
  return next || current;
}

function latestNumber(current: number | null, next: number | null): number | null {
  return next ?? current;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
