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

  for (let i = 0; i < timeline.length; i++) {
    const event = timeline[i];
    if (!event) continue;

    // SubAgent event grouping
    if (SUBAGENT_EVENT_TYPES.has(event.type)) {
      flushGroup();
      const subGroup = buildSubAgentGroup(timeline, i);
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
 * Build a SubAgentGroup from consecutive SubAgent events starting at index.
 * Returns the group and the last consumed event index.
 */
function buildSubAgentGroup(
  timeline: TimelineEvent[],
  startIdx: number
): { group: SubAgentGroup; endIndex: number } {
  const events: TimelineEvent[] = [];
  let endIndex = startIdx;

  // Collect consecutive SubAgent events
  for (let i = startIdx; i < timeline.length; i++) {
    const item = timeline[i];
    if (!item) break;
    if (SUBAGENT_EVENT_TYPES.has(item.type)) {
      events.push(item);
      endIndex = i;
      // Stop after terminal events
      const t = item.type;
      if (
        t === 'subagent_completed' ||
        t === 'subagent_failed' ||
        t === 'subagent_killed' ||
        t === 'subagent_depth_limited' ||
        t === 'parallel_completed' ||
        t === 'chain_completed' ||
        t === 'background_launched'
      ) {
        break;
      }
    } else {
      break;
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

  return { group, endIndex };
}
