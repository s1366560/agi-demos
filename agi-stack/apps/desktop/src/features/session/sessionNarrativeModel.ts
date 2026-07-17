import type { AgentTimelineItem, ToolDisplayData } from '../../types';

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
  evidence: string;
};

export function buildSessionNarrative(items: AgentTimelineItem[]): SessionNarrativeNode[] {
  const narrative: SessionNarrativeNode[] = [];
  let toolItems: AgentTimelineItem[] = [];

  const flushToolItems = () => {
    if (!toolItems.length) return;
    narrative.push({
      kind: 'tool_group',
      id: `tool-group:${toolItems[0].id}:${toolItems[toolItems.length - 1].id}`,
      toolCount: toolGroupCount(toolItems),
      status: toolGroupStatus(toolItems),
      items: toolItems,
    });
    toolItems = [];
  };

  items.forEach((item) => {
    if (item.type === 'act' || item.type === 'observe') {
      toolItems.push(item);
      return;
    }
    flushToolItems();
    narrative.push({ kind: 'item', id: item.id, item });
  });
  flushToolItems();

  return narrative;
}

export function sessionActivitySummary(input: {
  items: AgentTimelineItem[];
  artifactCount: number;
  taskCount: number;
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
  const checkpointKey = checkpointTitleKey(checkpointItem) ?? 'session.activityCheckpoint';
  const checkpoint = '';

  return {
    title,
    titleKey,
    detail,
    checkpoint,
    checkpointKey,
    evidence: `${input.artifactCount} artifacts · ${input.taskCount} tasks`,
  };
}

function toolGroupCount(items: AgentTimelineItem[]): number {
  const calls = items.filter((item) => item.type === 'act').length;
  if (calls) return calls;
  const namedTools = new Set(items.map((item) => item.toolName).filter(Boolean));
  return Math.max(namedTools.size, items.length ? 1 : 0);
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
