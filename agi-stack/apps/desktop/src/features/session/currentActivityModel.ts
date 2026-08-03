import type { AgentTimelineItem, ToolDisplayData } from '../../types';
import {
  pairToolCallItems,
  timelineWorkingStartedAtUs,
  toolCallPairStatus,
  toolCallPresentationKind,
  type ToolCallPair,
  type ToolCallPairStatus,
  type ToolCallPresentationKind,
} from '../chat/chatTimelineModel';
import { groupSubAgentTimelineItems } from '../chat/subagentTimelineGroupModel';
import type { SubAgentTimelineGroup } from '../chat/subagentTimelineGroupModel';
import type { SessionActivityPresence } from './sessionNarrativeModel';

// Pure derivation of the "currently doing X" headline shown above the composer
// while a session run is live. Kept free of React/JSX so the node:test harness
// can compile and exercise it directly (see tests/current-activity-model.test.mjs).

export type CurrentActivityKind =
  | ToolCallPresentationKind
  | 'subagent'
  | 'thinking'
  | 'responding'
  | 'working';

export type CurrentActivityEntryStatus = ToolCallPairStatus;

export type CurrentActivityEntry = {
  id: string;
  kind: CurrentActivityKind;
  label: string;
  /** i18n fallback key when label is empty. */
  titleKey: string | null;
  detail: string;
  status: CurrentActivityEntryStatus;
  startedAtMs: number | null;
};

export type CurrentActivityHeadline = {
  kind: CurrentActivityKind;
  /** Primary one-line label (tool title, subagent name, ...). '' → use titleKey. */
  label: string;
  /** i18n fallback key when label is empty (generic states). */
  titleKey: string | null;
  /** Primary argument/target (file path, command, task), already truncated. */
  detail: string;
  startedAtMs: number | null;
  /** Number of concurrently active subagent groups (0 when none). */
  activeSubagentCount: number;
  /** Recent activity group shown when the headline is expanded, chronological. */
  entries: CurrentActivityEntry[];
};

const HEADLINE_LABEL_MAX = 80;
const HEADLINE_DETAIL_MAX = 96;
const DEFAULT_MAX_ENTRIES = 8;

const ACTIVE_SUBAGENT_STATUSES = new Set(['running', 'queued', 'steered']);

/** Ordered probe keys for the primary target of a tool call. */
const TOOL_TARGET_KEYS = [
  'command',
  'cmd',
  'path',
  'file_path',
  'filePath',
  'relativePath',
  'pattern',
  'query',
  'url',
] as const;

export function deriveCurrentActivity(args: {
  items: AgentTimelineItem[];
  presence: SessionActivityPresence;
  maxEntries?: number;
}): CurrentActivityHeadline | null {
  const { items, presence } = args;
  if (presence !== 'live') return null;
  const maxEntries = args.maxEntries ?? DEFAULT_MAX_ENTRIES;

  const indexById = new Map(items.map((item, index) => [item.id, index]));
  // pairToolCallItems also groups non-tool items (thoughts, subagent events)
  // into single-item pairs; only act/observe pairs are real tool calls.
  const pairs = pairToolCallItems(items.filter((item) => !isUserItem(item))).filter(
    (pair) => pair.call.type === 'act' || pair.call.type === 'observe',
  );
  const lastRunningPair = [...pairs]
    .reverse()
    .find((pair) => toolCallPairStatus(pair) === 'running');

  const subagentGroups = groupSubAgentTimelineItems(items).groups;
  const activeSubagents = subagentGroups.filter((group) =>
    ACTIVE_SUBAGENT_STATUSES.has(group.status),
  );
  const primarySubagent = activeSubagents[activeSubagents.length - 1] ?? null;

  const lastItem = [...items].reverse().find((item) => !isUserItem(item));
  const streamingThought =
    lastItem && lastItem.type === 'thought' && lastItem.metadata?.streaming ? lastItem : null;
  const streamingAssistant =
    lastItem && isAssistantItem(lastItem) && lastItem.metadata?.streaming ? lastItem : null;

  const headline = pickHeadline({
    items,
    indexById,
    lastRunningPair: lastRunningPair ?? null,
    primarySubagent,
    streamingThought: streamingThought ?? null,
    streamingAssistant: streamingAssistant ?? null,
    lastItem: lastItem ?? null,
  });

  return {
    ...headline,
    activeSubagentCount: activeSubagents.length,
    entries: buildEntries({
      activeSubagents,
      pairs,
      maxEntries,
    }),
  };
}

/** Format an elapsed duration as a ticking clock: mm:ss, or h:mm:ss past 1h. */
export function formatElapsedClock(elapsedMs: number): string {
  if (!Number.isFinite(elapsedMs) || elapsedMs < 0) return '';
  const totalSeconds = Math.floor(elapsedMs / 1000);
  const seconds = totalSeconds % 60;
  const minutes = Math.floor(totalSeconds / 60) % 60;
  const hours = Math.floor(totalSeconds / 3600);
  const ss = String(seconds).padStart(2, '0');
  const mm = String(minutes).padStart(2, '0');
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`;
}

function pickHeadline(args: {
  items: AgentTimelineItem[];
  indexById: ReadonlyMap<string, number>;
  lastRunningPair: ToolCallPair | null;
  primarySubagent: SubAgentTimelineGroup | null;
  streamingThought: AgentTimelineItem | null;
  streamingAssistant: AgentTimelineItem | null;
  lastItem: AgentTimelineItem | null;
}): Omit<CurrentActivityHeadline, 'activeSubagentCount' | 'entries'> {
  const { indexById } = args;

  const pairIndex = args.lastRunningPair
    ? (indexById.get(args.lastRunningPair.call.id) ?? -1)
    : -1;
  const subagentLastItem = args.primarySubagent?.items[
    args.primarySubagent.items.length - 1
  ];
  const subagentIndex = subagentLastItem ? (indexById.get(subagentLastItem.id) ?? -1) : -1;

  // Concurrent subagents win only when their latest event is the freshest
  // activity; otherwise an in-flight top-level tool call is more current.
  if (args.primarySubagent && subagentIndex >= 0 && subagentIndex >= pairIndex) {
    return {
      kind: 'subagent',
      label: truncate(args.primarySubagent.subagentName, HEADLINE_LABEL_MAX),
      titleKey: args.primarySubagent.subagentName ? null : 'session.currentActivity.subagent',
      detail: truncate(
        args.primarySubagent.statusMessage || args.primarySubagent.task,
        HEADLINE_DETAIL_MAX,
      ),
      startedAtMs: eventTimeMs(args.primarySubagent.items[0]),
    };
  }

  if (args.lastRunningPair) {
    const call = args.lastRunningPair.call;
    const display = activityDisplay(call);
    const kind = toolCallPresentationKind(args.lastRunningPair);
    return {
      kind,
      label: truncate(display?.title || call.toolName || '', HEADLINE_LABEL_MAX),
      titleKey: display?.title || call.toolName ? null : toolKindTitleKey(kind),
      detail: truncate(toolCallTarget(call, display), HEADLINE_DETAIL_MAX),
      startedAtMs: eventTimeMs(call),
    };
  }

  if (args.streamingThought) {
    return {
      kind: 'thinking',
      label: '',
      titleKey: 'session.currentActivity.thinking',
      detail: truncate(compactText(args.streamingThought.content), HEADLINE_DETAIL_MAX),
      startedAtMs: eventTimeMs(args.streamingThought),
    };
  }

  if (args.streamingAssistant) {
    return {
      kind: 'responding',
      label: '',
      titleKey: 'session.currentActivity.responding',
      detail: '',
      startedAtMs: eventTimeMs(args.streamingAssistant),
    };
  }

  // Idle gap or generic activity: the run is live but nothing is in flight.
  // Keep the headline visible with the run start so the clock reflects the
  // whole run rather than the last completed step.
  return {
    kind: 'working',
    label: '',
    titleKey: 'session.currentActivity.working',
    detail: '',
    startedAtMs: toMs(timelineWorkingStartedAtUs(args.items)) ?? eventTimeMs(args.lastItem),
  };
}

function buildEntries(args: {
  activeSubagents: SubAgentTimelineGroup[];
  pairs: ToolCallPair[];
  maxEntries: number;
}): CurrentActivityEntry[] {
  const subagentEntries: CurrentActivityEntry[] = args.activeSubagents.map((group) => ({
    id: group.id,
    kind: 'subagent',
    label: truncate(group.subagentName, HEADLINE_LABEL_MAX),
    titleKey: group.subagentName ? null : 'session.currentActivity.subagent',
    detail: truncate(group.statusMessage || group.task, HEADLINE_DETAIL_MAX),
    status: 'running',
    startedAtMs: eventTimeMs(group.items[0]),
  }));
  const toolEntries: CurrentActivityEntry[] = args.pairs.map((pair) => {
    const display = activityDisplay(pair.call);
    const kind = toolCallPresentationKind(pair);
    return {
      id: pair.call.id,
      kind,
      label: truncate(display?.title || pair.call.toolName || '', HEADLINE_LABEL_MAX),
      titleKey: display?.title || pair.call.toolName ? null : toolKindTitleKey(kind),
      detail: truncate(toolCallTarget(pair.result ?? pair.call, display), HEADLINE_DETAIL_MAX),
      status: toolCallPairStatus(pair),
      startedAtMs: eventTimeMs(pair.call),
    };
  });
  return [...subagentEntries, ...toolEntries].slice(-args.maxEntries);
}

function toolKindTitleKey(kind: ToolCallPresentationKind): string {
  return kind === 'tool' ? 'chat.toolCall' : `session.toolKind.${kind}`;
}

function toolCallTarget(item: AgentTimelineItem, display: ToolDisplayData | null): string {
  if (display?.summary) return compactText(display.summary);
  const input = isRecord(item.toolInput) ? item.toolInput : null;
  if (input) {
    for (const key of TOOL_TARGET_KEYS) {
      const value = input[key];
      if (typeof value === 'string' && value.trim()) return compactText(value);
    }
  }
  return compactText(item.content);
}

function activityDisplay(item: AgentTimelineItem): ToolDisplayData | null {
  if (isRecord(item.display)) return item.display as ToolDisplayData;
  if (isRecord(item.toolOutput) && isRecord(item.toolOutput.display)) {
    return item.toolOutput.display as ToolDisplayData;
  }
  return null;
}

function isUserItem(item: AgentTimelineItem): boolean {
  return item.role === 'user' || item.type === 'user_message';
}

function isAssistantItem(item: AgentTimelineItem): boolean {
  return item.role === 'assistant' || item.type === 'assistant_message';
}

function eventTimeMs(item: AgentTimelineItem | null | undefined): number | null {
  return item ? toMs(item.eventTimeUs) : null;
}

function toMs(eventTimeUs: number | null): number | null {
  return typeof eventTimeUs === 'number' && Number.isFinite(eventTimeUs) && eventTimeUs > 0
    ? Math.floor(eventTimeUs / 1000)
    : null;
}

function compactText(value: unknown): string {
  if (typeof value !== 'string') return '';
  return value.trim().replace(/\s+/g, ' ');
}

function truncate(value: string, max: number): string {
  const compacted = compactText(value);
  if (compacted.length <= max) return compacted;
  return `${compacted.slice(0, Math.max(0, max - 1)).trimEnd()}…`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}
