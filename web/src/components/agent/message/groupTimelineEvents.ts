/**
 * Groups consecutive act/observe timeline events into ExecutionTimeline groups.
 * Non-tool events pass through as individual items.
 * SubAgent events are grouped into SubAgentGroup blocks.
 */

import type { TimelineEvent, ObserveEvent } from '../../../types/agent';
import type { TimelineStep } from '../timeline/ExecutionTimeline';
import type { SubAgentGroup } from '../timeline/SubAgentTimeline';

export type GroupedItem =
  | { kind: 'event'; event: TimelineEvent; index: number }
  | { kind: 'timeline'; steps: TimelineStep[]; startIndex: number }
  | { kind: 'subagent'; group: SubAgentGroup; startIndex: number };

const SUBAGENT_EVENT_TYPES = new Set([
  'subagent_routed',
  'subagent_started',
  'subagent_completed',
  'subagent_failed',
  'subagent_queued',
  'subagent_killed',
  'subagent_steered',
  'subagent_depth_limited',
  'subagent_session_update',
  'parallel_started',
  'parallel_completed',
  'chain_started',
  'chain_step_started',
  'chain_step_completed',
  'chain_completed',
  'background_launched',
]);

export function groupTimelineEvents(timeline: TimelineEvent[]): GroupedItem[] {
  const result: GroupedItem[] = [];
  let currentSteps: TimelineStep[] = [];
  let groupStartIndex = 0;

  // Build observe lookup by execution_id
  const observeByExecId = new Map<string, ObserveEvent>();
  // Fallback: build observe lookup by toolName for events without execution_id
  const observeByToolName = new Map<string, ObserveEvent[]>();
  for (const ev of timeline) {
    if (ev.type === 'observe') {
      const obsEv = ev;
      if (obsEv.execution_id) {
        observeByExecId.set(obsEv.execution_id, obsEv);
      }
      const name = obsEv.toolName || 'unknown';
      const list = observeByToolName.get(name) || [];
      list.push(obsEv);
      observeByToolName.set(name, list);
    }
  }

  // Track which observe events have been consumed by fallback matching
  const consumedObserves = new Set<string>();

  const flushGroup = () => {
    if (currentSteps.length >= 1) {
      result.push({ kind: 'timeline', steps: currentSteps, startIndex: groupStartIndex });
    }
    currentSteps = [];
  };

  // Track terminal SubAgent events claimed by forward scans (avoid duplicate groups)
  const claimedIndices = new Set<number>();

  for (let i = 0; i < timeline.length; i++) {
    const event = timeline[i];
    if (!event) continue;
    // Skip events already claimed by a forward scan
    if (claimedIndices.has(i)) continue;

    // SubAgent event grouping
    if (SUBAGENT_EVENT_TYPES.has(event.type)) {
      flushGroup();
      const subGroup = buildSubAgentGroup(timeline, i);
      // Merge forward-scanned terminal indices
      for (const idx of subGroup.claimedIndices) claimedIndices.add(idx);
      result.push({ kind: 'subagent', group: subGroup.group, startIndex: i });
      i = subGroup.endIndex;
      continue;
    }

    if (event.type === 'act') {
      if (currentSteps.length === 0) groupStartIndex = i;

      const act = event;
      // Priority 1: match by execution_id
      let obs: ObserveEvent | undefined = act.execution_id
        ? observeByExecId.get(act.execution_id)
        : undefined;
      // Priority 2: fallback to toolName matching
      if (!obs) {
        const candidates = observeByToolName.get(act.toolName) || [];
        for (const cand of candidates) {
          if (!consumedObserves.has(cand.id) && cand.timestamp >= act.timestamp) {
            obs = cand;
            consumedObserves.add(cand.id);
            break;
          }
        }
      }

      const step: TimelineStep = {
        id: act.execution_id || act.id || `step-${String(i)}`,
        toolName: act.toolName || 'unknown',
        status: obs ? (obs.isError ? 'error' : 'success') : 'running',
        input: act.toolInput,
        output: obs?.toolOutput,
        isError: obs?.isError,
        duration: obs && act.timestamp && obs.timestamp ? obs.timestamp - act.timestamp : undefined,
        mcpUiMetadata: obs?.mcpUiMetadata,
      };
      currentSteps.push(step);
    } else if (event.type === 'observe') {
      // Skip - handled as part of act
      continue;
    } else {
      flushGroup();
      result.push({ kind: 'event', event, index: i });
    }
  }
  flushGroup();

  return result;
}

/**
 * Terminal SubAgent event types that signal the end of a SubAgent lifecycle.
 */
const TERMINAL_SUBAGENT_TYPES = new Set([
  'subagent_completed',
  'subagent_failed',
  'subagent_killed',
  'subagent_depth_limited',
  'parallel_completed',
  'chain_completed',
  'background_launched',
]);

/**
 * Extract subagentId from a timeline event if present.
 */
function getSubAgentId(ev: TimelineEvent): string | undefined {
  // All SubAgent events have subagentId mapped by sseEventAdapter
  const d = ev as unknown as Record<string, unknown>;
  const id = d.subagentId;
  return typeof id === 'string' && id.length > 0 ? id : undefined;
}

/**
 * Build a SubAgentGroup from consecutive SubAgent events starting at index.
 * Returns the group and the last consumed event index.
 *
 * If a non-SubAgent event interrupts the consecutive sequence (e.g. main agent
 * emitting thought/act/observe between SubAgent lifecycle events), we do a forward
 * scan to find the matching terminal event so the group gets the correct final status.
 */
function buildSubAgentGroup(
  timeline: TimelineEvent[],
  startIdx: number
): { group: SubAgentGroup; endIndex: number; claimedIndices: Set<number> } {
  const events: TimelineEvent[] = [];
  let endIndex = startIdx;
  let foundTerminal = false;
  const claimedIndices = new Set<number>();

  // Phase 1: Collect consecutive SubAgent events (original behavior)
  for (let i = startIdx; i < timeline.length; i++) {
    const item = timeline[i];
    if (!item) break;
    if (SUBAGENT_EVENT_TYPES.has(item.type)) {
      events.push(item);
      endIndex = i;
      if (TERMINAL_SUBAGENT_TYPES.has(item.type)) {
        foundTerminal = true;
        break;
      }
    } else {
      break;
    }
  }

  // Phase 2: If no terminal event found, scan ahead for a matching terminal event.
  // This handles interleaved main-agent events (thought/act/observe/complete)
  // that appear between a SubAgent's start and its terminal event.
  if (!foundTerminal && events.length > 0) {
    // Determine the subagentId from collected events
    let targetId: string | undefined;
    for (const ev of events) {
      targetId = getSubAgentId(ev);
      if (targetId) break;
    }

    if (targetId) {
      for (let i = endIndex + 1; i < timeline.length; i++) {
        const item = timeline[i];
        if (!item) break;
        if (TERMINAL_SUBAGENT_TYPES.has(item.type) && getSubAgentId(item) === targetId) {
          events.push(item);
          // Record this index so the main loop skips it (avoid duplicate group)
          claimedIndices.add(i);
          break;
        }
      }
    }
  }

  // Build group from events
  const group: SubAgentGroup = {
    kind: 'subagent',
    subagentId: '',
    subagentName: '',
    status: 'running',
    events,
    startIndex: startIdx,
    mode: 'single',
  };

  for (const ev of events) {
    switch (ev.type) {
      case 'subagent_routed': {
        const d = ev;
        group.subagentId = d.subagentId || '';
        group.subagentName = d.subagentName || '';
        group.confidence = d.confidence;
        group.reason = d.reason;
        break;
      }
      case 'subagent_started': {
        const d = ev;
        group.subagentId = group.subagentId || d.subagentId || '';
        group.subagentName = group.subagentName || d.subagentName || '';
        group.task = d.task;
        break;
      }
      case 'subagent_completed': {
        const d = ev;
        group.status = 'success';
        group.summary = d.summary;
        group.tokensUsed = d.tokensUsed;
        group.executionTimeMs = d.executionTimeMs;
        break;
      }
      case 'subagent_failed': {
        const d = ev;
        group.status = 'error';
        group.error = d.error;
        break;
      }
      case 'parallel_started': {
        const d = ev;
        group.mode = 'parallel';
        group.parallelInfo = {
          taskCount: d.taskCount,
          subtasks: d.subtasks,
        };
        break;
      }
      case 'parallel_completed': {
        const d = ev;
        group.status = 'success';
        if (group.parallelInfo) {
          group.parallelInfo.results = d.results;
          group.parallelInfo.totalTimeMs = d.totalTimeMs;
        }
        group.executionTimeMs = d.totalTimeMs;
        break;
      }
      case 'chain_started': {
        const d = ev;
        group.mode = 'chain';
        group.chainInfo = {
          stepCount: d.stepCount || 0,
          chainName: d.chainName || '',
          steps: [],
        };
        break;
      }
      case 'chain_step_started': {
        const d = ev;
        if (group.chainInfo) {
          group.chainInfo.steps.push({
            index: d.stepIndex,
            name: d.stepName || '',
            subagentName: d.subagentName || '',
            status: 'running',
          });
        }
        break;
      }
      case 'chain_step_completed': {
        const d = ev;
        if (group.chainInfo) {
          const idx = d.stepIndex;
          const step = group.chainInfo.steps.find((s) => s.index === idx);
          if (step) {
            step.summary = d.summary;
            step.success = d.success;
            step.status = d.success !== false ? 'success' : 'error';
          }
        }
        break;
      }
      case 'chain_completed': {
        const d = ev;
        group.status = d.success !== false ? 'success' : 'error';
        if (group.chainInfo) {
          group.chainInfo.totalTimeMs = d.totalTimeMs;
        }
        group.executionTimeMs = d.totalTimeMs;
        break;
      }
      case 'background_launched': {
        const d = ev;
        group.status = 'background';
        group.subagentName = group.subagentName || d.subagentName || '';
        group.task = d.task;
        break;
      }
      case 'subagent_queued': {
        const d = ev;
        group.subagentId = group.subagentId || d.subagentId || '';
        group.subagentName = group.subagentName || d.subagentName || '';
        group.status = 'queued';
        break;
      }
      case 'subagent_killed': {
        const d = ev;
        group.subagentId = group.subagentId || d.subagentId || '';
        group.subagentName = group.subagentName || d.subagentName || '';
        group.status = 'killed';
        group.error = d.kill_reason || d.error || 'Killed';
        break;
      }
      case 'subagent_steered': {
        const d = ev;
        group.subagentId = group.subagentId || d.subagentId || '';
        group.subagentName = group.subagentName || d.subagentName || '';
        group.task = d.instruction || group.task;
        break;
      }
      case 'subagent_depth_limited': {
        const d = ev;
        group.subagentName = group.subagentName || d.subagentName || '';
        group.status = 'depth_limited';
        group.error = `Depth limit reached: ${String(d.current_depth ?? '?')}/${String(d.max_depth ?? '?')}`;
        break;
      }
      case 'subagent_session_update': {
        const d = ev;
        group.subagentId = group.subagentId || d.subagentId || '';
        group.subagentName = group.subagentName || d.subagentName || '';
        // Progress updates don't change status — the agent is still running
        break;
      }
    }
  }

  return { group, endIndex, claimedIndices };
}

export interface SubAgentSummary {
  subagentId: string;
  name: string;
  status: SubAgentGroup['status'];
  executionTimeMs?: number;
  tokensUsed?: number;
  startIndex: number;
}

export function getSubAgentSummaries(items: GroupedItem[]): SubAgentSummary[] {
  return items
    .filter(
      (item): item is { kind: 'subagent'; group: SubAgentGroup; startIndex: number } =>
        item.kind === 'subagent'
    )
    .map((item) => {
      const summary: SubAgentSummary = {
        subagentId: item.group.subagentId,
        name: item.group.subagentName || item.group.subagentId?.slice(0, 8) || 'Unnamed',
        status: item.group.status,
        startIndex: item.startIndex,
      };
      if (item.group.executionTimeMs !== undefined) {
        summary.executionTimeMs = item.group.executionTimeMs;
      }
      if (item.group.tokensUsed !== undefined) {
        summary.tokensUsed = item.group.tokensUsed;
      }
      return summary;
    });
}
