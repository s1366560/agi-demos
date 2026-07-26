import type { AgentTimelineItem } from '../../types';

type AssistantDisplaySourceIdentity = {
  authors: Set<string>;
  sources: Set<string>;
};

type AssistantDisplayDuplicateGroup = {
  content: string;
  identity: AssistantDisplaySourceIdentity;
  originals: AgentTimelineItem[];
  resultIndex: number;
};

/**
 * Fold repeated persisted projections from one Agent execution into a single
 * display row. The input timeline remains authoritative and untouched.
 */
export function foldAssistantExecutionDuplicatesForDisplay(
  items: AgentTimelineItem[],
): AgentTimelineItem[] {
  const result: AgentTimelineItem[] = [];
  let hasUserTurn = false;
  let groupsByExecution = new Map<string, AssistantDisplayDuplicateGroup[]>();

  for (const item of items) {
    if (isUserTimelineItem(item)) {
      hasUserTurn = true;
      groupsByExecution = new Map();
      result.push(item);
      continue;
    }

    const executionMessageId = assistantDisplayExecutionIdentity(item);
    if (!hasUserTurn || executionMessageId === null) {
      result.push(item);
      continue;
    }

    const content = item.content as string;
    const identity = assistantDisplaySourceIdentity(item);
    const executionGroups = groupsByExecution.get(executionMessageId) ?? [];
    const group = executionGroups.find(
      (candidate) =>
        candidate.content === content &&
        !assistantDisplaySourceIdentitiesConflict(candidate.identity, identity),
    );
    if (!group) {
      executionGroups.push({
        content,
        identity,
        originals: [item],
        resultIndex: result.length,
      });
      groupsByExecution.set(executionMessageId, executionGroups);
      result.push(item);
      continue;
    }

    group.identity = mergeAssistantDisplaySourceIdentities(group.identity, identity);
    group.originals = [...group.originals, item];
    result[group.resultIndex] = {
      ...group.originals[0],
      presentationDuplicateAssistantMessages: group.originals,
    };
  }

  return result;
}

/**
 * Return the raw assistant rows represented by one display-only duplicate group.
 * Search, export, comparison, message actions, and diagnostics keep using the
 * authoritative timeline instead of this derived display projection.
 */
export function assistantDisplayDuplicateItems(
  item: AgentTimelineItem,
): AgentTimelineItem[] {
  return Array.isArray(item.presentationDuplicateAssistantMessages)
    ? item.presentationDuplicateAssistantMessages.filter(isAgentTimelineItem)
    : [];
}

function assistantDisplayExecutionIdentity(item: AgentTimelineItem): string | null {
  if (
    item.type !== 'assistant_message' ||
    item.metadata?.streaming === true ||
    isTransientAssistantTimelineItem(item) ||
    typeof item.content !== 'string' ||
    item.content.length === 0 ||
    typeof item.executionMessageId !== 'string' ||
    item.executionMessageId.trim().length === 0
  ) {
    return null;
  }
  return item.executionMessageId;
}

function assistantDisplaySourceIdentity(
  item: AgentTimelineItem,
): AssistantDisplaySourceIdentity {
  const records = [
    item,
    item.metadata,
    isRecord(item.payload) ? item.payload : null,
    isRecord(item.payload) && isRecord(item.payload.metadata)
      ? item.payload.metadata
      : null,
  ].filter(isRecord);
  return {
    authors: recordIdentityValues(records, [
      'agent_id',
      'agentId',
      'source_agent_id',
      'sourceAgentId',
      'sender_id',
      'senderId',
      'from_agent_id',
      'fromAgentId',
    ]),
    sources: recordIdentityValues(records, ['source']),
  };
}

function recordIdentityValues(
  records: Record<string, unknown>[],
  keys: readonly string[],
): Set<string> {
  const values = new Set<string>();
  for (const record of records) {
    for (const key of keys) {
      const value = record[key];
      if (typeof value === 'string' && value.trim()) values.add(value.trim());
    }
  }
  return values;
}

function assistantDisplaySourceIdentitiesConflict(
  left: AssistantDisplaySourceIdentity,
  right: AssistantDisplaySourceIdentity,
): boolean {
  return (
    identityDimensionConflicts(left.authors, right.authors) ||
    identityDimensionConflicts(left.sources, right.sources)
  );
}

function identityDimensionConflicts(left: Set<string>, right: Set<string>): boolean {
  if (left.size > 1 || right.size > 1) return true;
  if (left.size === 0 || right.size === 0) return false;
  return !left.has([...right][0]);
}

function mergeAssistantDisplaySourceIdentities(
  left: AssistantDisplaySourceIdentity,
  right: AssistantDisplaySourceIdentity,
): AssistantDisplaySourceIdentity {
  return {
    authors: new Set([...left.authors, ...right.authors]),
    sources: new Set([...left.sources, ...right.sources]),
  };
}

function isUserTimelineItem(item: AgentTimelineItem): boolean {
  return item.role === 'user' || item.type === 'user_message';
}

function isTransientAssistantTimelineItem(item: AgentTimelineItem): boolean {
  return (
    item.id.startsWith('streaming-assistant-') ||
    item.id.startsWith('completed-assistant-')
  );
}

function isAgentTimelineItem(value: unknown): value is AgentTimelineItem {
  return isRecord(value) && typeof value.id === 'string' && typeof value.type === 'string';
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
