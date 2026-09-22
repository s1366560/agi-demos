import { timelineToolResultFailed } from '../chat/toolResultStatus';
import type { AgentTimelineItem, DesktopRunStatus, ToolDisplayData } from '../../types';
import { exactToolResults, timelineExecutionScope } from '../chat/timelineExecutionIdentity';
import { pairToolCallItems, toolCallPairStatus } from '../chat/chatTimelineModel';

export type SessionToolGroupStatus = 'running' | 'complete' | 'failed' | 'stopped';

export type SessionNarrativeNode =
  | {
      kind: 'item';
      id: string;
      item: AgentTimelineItem;
    }
  | {
      kind: 'tool_group';
      id: string;
      items: AgentTimelineItem[];
      toolCount: number;
      status: SessionToolGroupStatus;
    };

export type SessionActivitySummary = {
  title: string;
  titleKey: string | null;
  detail: string;
  checkpoint: string;
  checkpointKey: string | null;
  evidence: SessionActivityEvidence;
};

export type SessionActivityPresence = 'live' | 'recorded';

export type SessionActivityStructuredEvidence = {
  artifactCount: number;
  checkCount: number | null;
  toolActivityCount: number;
};

export type SessionActivityEvidence =
  | ({ kind: 'structured' } & SessionActivityStructuredEvidence)
  | { kind: 'agent_reported'; text: string }
  | { kind: 'unavailable' };

export function sessionActivityPresence(
  runStatus: DesktopRunStatus | null,
  updatesConnected: boolean,
): SessionActivityPresence {
  return runStatus === 'running' && updatesConnected ? 'live' : 'recorded';
}

export function buildSessionNarrative(
  items: AgentTimelineItem[],
  conversationId?: string,
): SessionNarrativeNode[] {
  const uniqueItems = [...new Map(items.map((item) => [item.id, item])).values()];
  const linkedResults = exactExecutionResults(uniqueItems, conversationId);
  const linkedResultIds = new Set([...linkedResults.values()].map((item) => item.id));
  const narrative: SessionNarrativeNode[] = [];
  let structuredItems: AgentTimelineItem[] = [];

  const flushStructuredItems = () => {
    appendStructuredNarrative(narrative, structuredItems, linkedResults, linkedResultIds);
    structuredItems = [];
  };

  uniqueItems.forEach((item) => {
    if (
      item.role !== 'user' &&
      item.role !== 'assistant' &&
      !['user_message', 'assistant_message', 'complete', 'run_status', 'environment_selected'].includes(item.type)
    ) {
      structuredItems.push(item);
      return;
    }
    flushStructuredItems();
    narrative.push({ kind: 'item', id: item.id, item });
  });
  flushStructuredItems();

  return narrative;
}

export function timelineGroupOpen(
  items: readonly Pick<AgentTimelineItem, 'id'>[],
  expandedItems: Readonly<Record<string, boolean>>,
  defaultOpen = false,
): boolean {
  let hasExplicitState = false;
  let open = false;
  for (const item of items) {
    if (!Object.prototype.hasOwnProperty.call(expandedItems, item.id)) continue;
    hasExplicitState = true;
    open ||= expandedItems[item.id] === true;
  }
  return hasExplicitState ? open : defaultOpen;
}

export function sessionActivitySummary(input: {
  items: AgentTimelineItem[];
  structuredEvidence?: SessionActivityStructuredEvidence | null;
}): SessionActivitySummary {
  const latest = [...input.items]
    .reverse()
    .find((item) => item.role !== 'user' && item.type !== 'user_message');
  const display = latest ? timelineDisplay(latest) : null;
  const titleKey = display?.title ? null : activityTitleKey(latest) ?? 'session.activityUpdated';
  const title = display?.title || '';
  const detail =
    display?.summary ||
    compactText(latest?.content) ||
    compactText(latest?.description) ||
    compactText(latest?.error) ||
    '';
  const checkpointItem = [...input.items]
    .reverse()
    .find(
      (item) =>
        Boolean(item.toolName) ||
        Boolean(item.filename) ||
        Boolean(item.artifactId) ||
        item.type === 'work_plan',
    );
  const checkpoint = compactText(display?.checkpoint);
  const checkpointKey = checkpoint
    ? null
    : checkpointTitleKey(checkpointItem) ?? 'session.activityCheckpoint';
  const reportedEvidence = compactText(display?.evidence);
  const evidence: SessionActivityEvidence = input.structuredEvidence
    ? { kind: 'structured', ...input.structuredEvidence }
    : reportedEvidence
      ? { kind: 'agent_reported', text: reportedEvidence }
      : { kind: 'unavailable' };

  return {
    title,
    titleKey,
    detail,
    checkpoint,
    checkpointKey,
    evidence,
  };
}

function toolGroupCount(items: AgentTimelineItem[]): number {
  return pairToolCallItems(items.filter((item) => item.type === 'act' || item.type === 'observe')).length;
}

function appendStructuredNarrative(
  narrative: SessionNarrativeNode[],
  items: AgentTimelineItem[],
  linkedResults: ReadonlyMap<string, AgentTimelineItem>,
  linkedResultIds: ReadonlySet<string>,
): void {
  if (!items.length) return;
  const pairs = pairToolCallItems(
    items.filter((item) =>
      (item.type === 'act' || item.type === 'observe') && !linkedResultIds.has(item.id)),
  );
  const pairsByCallId = new Map(pairs.map((pair) => [pair.call.id, {
    ...pair, result: linkedResults.get(pair.call.id) ?? pair.result,
  }]));
  const claimedResultIds = new Set(
    pairs.flatMap((pair) => (pair.result ? [pair.result.id] : [])),
  );
  let toolItems: AgentTimelineItem[] = [];

  const flushToolItems = () => {
    if (!toolItems.length) return;
    narrative.push({
      kind: 'tool_group',
      id: `tool-group:${toolItems[0].id}`,
      toolCount: toolGroupCount(toolItems),
      status: sessionToolGroupStatus(toolItems),
      items: toolItems,
    });
    toolItems = [];
  };

  items.forEach((item) => {
    if (item.type !== 'act' && item.type !== 'observe') {
      const scope = timelineExecutionScope(item);
      const owner = toolItems.find((candidate) => candidate.type === 'act' || candidate.type === 'observe');
      if (owner && scope && scope === timelineExecutionScope(owner) && isSessionDiagnostic(item)) {
        toolItems.push(item);
        return;
      }
      flushToolItems();
      narrative.push({ kind: 'item', id: item.id, item });
      return;
    }
    if (claimedResultIds.has(item.id) || linkedResultIds.has(item.id)) return;
    const pair = pairsByCallId.get(item.id);
    if (!pair) return;
    const owner = toolItems.find((candidate) => candidate.type === 'act' || candidate.type === 'observe');
    if (owner && timelineExecutionScope(owner) !== timelineExecutionScope(pair.call)) flushToolItems();
    toolItems.push(pair.call);
    if (pair.result) toolItems.push(pair.result);
  });
  flushToolItems();
}

function activityTitleKey(item: AgentTimelineItem | undefined): string | null {
  if (!item) return null;
  if (item.role === 'assistant' || item.type === 'assistant_message') {
    return 'session.activityAgentResponse';
  }
  if (item.type === 'thought') return 'session.activityReasoning';
  if (item.type === 'work_plan') return 'session.activityPlan';
  if (item.type === 'memory_captured') return 'session.activityMemoryCaptured';
  if (item.type === 'task_list_updated' || item.type === 'task_updated') {
    return 'session.activityPlan';
  }
  if (item.type.startsWith('artifact_')) return 'session.activityArtifact';
  return null;
}

function checkpointTitleKey(item: AgentTimelineItem | undefined): string | null {
  if (item?.toolName === 'todowrite') return 'session.activityPlan';
  return null;
}

export function sessionToolGroupStatus(items: AgentTimelineItem[]): SessionToolGroupStatus {
  if (items.some((item) => item.isError || Boolean(item.error) ||
    (item.type === 'observe' && timelineToolResultFailed(item)))) return 'failed';
  const statuses = items.filter((item) => item.type === 'run_status').map((item) => {
    const payload = isRecord(item.payload) ? item.payload : {};
    return payload.status ?? item.status;
  });
  const status = statuses.at(-1);
  if (status === 'failed') return 'failed';
  if (status === 'stopped' || status === 'cancelled' || status === 'canceled') return 'stopped';
  if (status === 'running' || status === 'pending' || status === 'queued') return 'running';
  const pairs = pairToolCallItems(items.filter((item) => item.type === 'act' || item.type === 'observe'));
  if (!pairs.length) return status === 'completed' ? 'complete' : 'running';
  if (pairs.some((pair) => toolCallPairStatus(pair) === 'failed')) return 'failed';
  return pairs.some((pair) => ['running', 'preparing'].includes(toolCallPairStatus(pair)))
    ? 'running' : 'complete';
}

function timelineDisplay(item: AgentTimelineItem): ToolDisplayData | null {
  if (isRecord(item.display)) return item.display as ToolDisplayData;
  if (!isRecord(item.toolOutput)) return null;
  return isRecord(item.toolOutput.display) ? (item.toolOutput.display as ToolDisplayData) : null;
}

function compactText(value: unknown): string {
  if (typeof value !== 'string') return '';
  return value.trim().replace(/\s+/g, ' ').slice(0, 180);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

// Only explicit execution identities may cross assistant narrative boundaries.
function exactExecutionResults(
  items: readonly AgentTimelineItem[],
  conversationId: string | undefined,
): Map<string, AgentTimelineItem> {
  const results = new Map<string, AgentTimelineItem>();
  let segment: AgentTimelineItem[] = [];
  const flush = () => {
    for (const [id, result] of exactToolResults(segment)) results.set(id, result);
    segment = [];
  };
  for (const item of items) {
    if (item.role === 'user' || ['user_message', 'complete', 'run_status', 'environment_selected'].includes(item.type)) {
      flush();
      continue;
    }
    const records = [item, item.payload, item.metadata].filter(isRecord);
    if (conversationId && records.some((record) =>
      ['conversation_id', 'conversationId'].some((key) => record[key] != null && record[key] !== conversationId))) continue;
    segment.push(item);
  }
  flush();
  return results;
}

// These protocol events are internal observations, never user requests or agent prose.
const diagnosticTypes = new Set([
  'ack', 'knowledge_tool_audit', 'tool_progress', 'tool_execution_progress',
  'tool_selection', 'tool_policy', 'toolset_changed', 'tool_selected',
  'context_usage', 'context_compressed', 'context_compacted',
  'agent_decision_logged', 'agent_supervisor_verdict',
]);

function isSessionDiagnostic(item: AgentTimelineItem): boolean {
  return diagnosticTypes.has(item.type) && !item.isError && !item.error;
}
