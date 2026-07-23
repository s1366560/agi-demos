import type { AgentTimelineItem, DesktopRunStatus, ToolDisplayData } from '../../types';
import { pairToolCallItems } from '../chat/chatTimelineModel';

export type SessionToolGroupStatus = 'running' | 'complete' | 'failed';

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

export function buildSessionNarrative(items: AgentTimelineItem[]): SessionNarrativeNode[] {
  const narrative: SessionNarrativeNode[] = [];
  let structuredItems: AgentTimelineItem[] = [];

  const flushStructuredItems = () => {
    appendStructuredNarrative(narrative, structuredItems);
    structuredItems = [];
  };

  items.forEach((item) => {
    if (item.type === 'thought' || item.type === 'act' || item.type === 'observe') {
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
  const calls = items.filter((item) => item.type === 'act').length;
  if (calls) return calls;
  const namedTools = new Set(items.map((item) => item.toolName).filter(Boolean));
  return Math.max(namedTools.size, items.length ? 1 : 0);
}

function appendStructuredNarrative(
  narrative: SessionNarrativeNode[],
  items: AgentTimelineItem[],
): void {
  if (!items.length) return;
  const pairs = pairToolCallItems(
    items.filter((item) => item.type === 'act' || item.type === 'observe'),
  );
  const pairsByCallId = new Map(pairs.map((pair) => [pair.call.id, pair]));
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
      status: toolGroupStatus(toolItems),
      items: toolItems,
    });
    toolItems = [];
  };

  items.forEach((item) => {
    if (item.type === 'thought') {
      flushToolItems();
      narrative.push({ kind: 'item', id: item.id, item });
      return;
    }
    if (claimedResultIds.has(item.id)) return;
    const pair = pairsByCallId.get(item.id);
    if (!pair) return;
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

function toolGroupStatus(items: AgentTimelineItem[]): SessionToolGroupStatus {
  if (items.some((item) => item.isError || Boolean(item.error))) return 'failed';
  const acts = items.filter((item) => item.type === 'act').length;
  const observations = items.filter((item) => item.type === 'observe').length;
  if (items[items.length - 1]?.type === 'act' || acts > observations) return 'running';
  return 'complete';
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
