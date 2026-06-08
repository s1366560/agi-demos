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

function parseRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }

  if (typeof value === 'string') {
    const text = value.trim();
    if (!text.startsWith('{')) return null;
    try {
      const parsed: unknown = JSON.parse(text);
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
        ? (parsed as Record<string, unknown>)
        : null;
    } catch {
      return null;
    }
  }

  return null;
}

function getTodoId(input: unknown): string | undefined {
  const record = parseRecord(input);
  return typeof record?.todo_id === 'string' ? record.todo_id : undefined;
}

function cacheTodoTitlesFromOutput(output: unknown, cache: Map<string, string>): void {
  const record = parseRecord(output);
  const todos = record?.todos;
  if (!Array.isArray(todos)) return;

  for (const todo of todos) {
    if (!todo || typeof todo !== 'object') continue;
    const item = todo as Record<string, unknown>;
    const id = item.id;
    const title = item.content ?? item.title ?? item.task ?? item.description ?? item.name;
    if (typeof id === 'string' && typeof title === 'string' && title.trim()) {
      cache.set(id, title.trim());
    }
  }
}

const SUBAGENT_EVENT_TYPES = new Set([
  'subagent_routed',
  'subagent_started',
  'subagent_completed',
  'subagent_failed',
  'subagent_run_started',
  'subagent_run_completed',
  'subagent_run_failed',
  'subagent_session_spawned',
  'subagent_session_message_sent',
  'subagent_announce_retry',
  'subagent_announce_giveup',
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

const HITL_REQUEST_EVENT_TYPES = new Set([
  'clarification_asked',
  'decision_asked',
  'env_var_requested',
  'permission_asked',
  'permission_requested',
]);

const HITL_RESPONSE_TO_REQUEST_EVENT_TYPE: Record<string, string> = {
  clarification_answered: 'clarification_asked',
  decision_answered: 'decision_asked',
  env_var_provided: 'env_var_requested',
  permission_replied: 'permission_asked',
  permission_granted: 'permission_asked',
};

function getRequestId(event: TimelineEvent): string | undefined {
  const value = (event as unknown as Record<string, unknown>).requestId;
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}

function isAnsweredHITLEvent(event: TimelineEvent, timeline: TimelineEvent[]): boolean {
  const record = event as unknown as Record<string, unknown>;
  if (record.answered === true) return true;

  const requestId = getRequestId(event);
  if (!requestId) return false;

  return timeline.some((candidate) => {
    const requestType = HITL_RESPONSE_TO_REQUEST_EVENT_TYPE[candidate.type];
    return requestType === event.type && getRequestId(candidate) === requestId;
  });
}

function getHITLStepOutput(event: TimelineEvent): Record<string, unknown> {
  const record = event as unknown as Record<string, unknown>;
  if (event.type === 'env_var_requested') {
    const values = record.values;
    const providedVariables = record.providedVariables;
    return {
      status: 'submitted',
      variables: Array.isArray(providedVariables)
        ? providedVariables
        : values && typeof values === 'object' && !Array.isArray(values)
          ? Object.keys(values)
          : undefined,
    };
  }
  if (event.type === 'permission_asked' || event.type === 'permission_requested') {
    return { status: record.granted === false ? 'denied' : 'submitted' };
  }
  if (event.type === 'decision_asked') {
    return { status: 'submitted', decision: record.decision };
  }
  return { status: 'submitted', answer: record.answer };
}

function findHITLRequestForAct(
  timeline: TimelineEvent[],
  actIndex: number
): TimelineEvent | undefined {
  for (let i = actIndex + 1; i < timeline.length; i++) {
    const candidate = timeline[i];
    if (!candidate) continue;

    if (candidate.type === 'observe') continue;
    if (candidate.type === 'act') return undefined;
    if (HITL_REQUEST_EVENT_TYPES.has(candidate.type)) return candidate;
    if (SUBAGENT_EVENT_TYPES.has(candidate.type)) return undefined;
    if (
      candidate.type === 'assistant_message' ||
      candidate.type === 'user_message' ||
      candidate.type === 'text_end'
    ) {
      return undefined;
    }
  }

  return undefined;
}

export function groupTimelineEvents(timeline: TimelineEvent[]): GroupedItem[] {
  const result: GroupedItem[] = [];
  let currentSteps: TimelineStep[] = [];
  let groupStartIndex = 0;
  const todoTitleById = new Map<string, string>();

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

  // Track act executions already rendered as a step. The same tool execution can
  // appear more than once in the timeline when persisted history is merged with
  // live-streamed events: each occurrence carries a different event id but the
  // same execution_id. Without this guard the duplicate renders a second step
  // that is stuck "running" (no matching observe), producing the doubled tool
  // execution UI.
  const seenActExecIds = new Set<string>();

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
      const act = event;

      // Skip duplicate occurrences of the same execution. observeByExecId is
      // built from the whole timeline, so the retained occurrence still resolves
      // its observe (completed/error) regardless of which copy is kept.
      const execId = act.execution_id;
      if (execId) {
        if (seenActExecIds.has(execId)) {
          continue;
        }
        seenActExecIds.add(execId);
      }

      if (currentSteps.length === 0) groupStartIndex = i;

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

      const hitlRequest = obs ? undefined : findHITLRequestForAct(timeline, i);
      const hitlAnswered = hitlRequest ? isAnsweredHITLEvent(hitlRequest, timeline) : false;

      const step: TimelineStep = {
        id: act.execution_id || act.id || `step-${String(i)}`,
        toolName: act.toolName || 'unknown',
        status: obs ? (obs.isError ? 'error' : 'success') : hitlAnswered ? 'success' : 'running',
        input: act.toolInput,
        output:
          obs?.toolOutput ??
          (hitlAnswered && hitlRequest ? getHITLStepOutput(hitlRequest) : undefined),
        isError: obs?.isError,
        duration: obs && act.timestamp && obs.timestamp ? obs.timestamp - act.timestamp : undefined,
        todoTitle: todoTitleById.get(getTodoId(act.toolInput) ?? ''),
        mcpUiMetadata: obs?.mcpUiMetadata,
      };
      currentSteps.push(step);
    } else if (event.type === 'observe') {
      cacheTodoTitlesFromOutput(event.toolOutput, todoTitleById);
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
  'subagent_run_completed',
  'subagent_run_failed',
  'subagent_announce_giveup',
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

function getSubAgentName(ev: TimelineEvent): string | undefined {
  const d = ev as unknown as Record<string, unknown>;
  const name = d.subagentName;
  return typeof name === 'string' && name.length > 0 ? name : undefined;
}

function normalizeSubAgentName(name: string | undefined): string {
  return (name ?? '').toLowerCase().replace(/[^a-z0-9]+/g, '');
}

function getSubAgentGroupMode(ev: TimelineEvent): 'parallel' | 'chain' | 'single' {
  if (ev.type.startsWith('parallel_')) return 'parallel';
  if (ev.type.startsWith('chain_')) return 'chain';
  return 'single';
}

function getTextMarkers(ev: TimelineEvent): string[] {
  const d = ev as unknown as Record<string, unknown>;
  return [d.task, d.summary, d.error]
    .filter((value): value is string => typeof value === 'string' && value.trim().length > 0)
    .map((value) => value.trim());
}

function hasSharedTextMarker(events: TimelineEvent[], candidate: TimelineEvent): boolean {
  const candidateMarkers = getTextMarkers(candidate);
  if (candidateMarkers.length === 0) return false;
  const existingMarkers = new Set(events.flatMap((event) => getTextMarkers(event)));
  return candidateMarkers.some((marker) => existingMarkers.has(marker));
}

function hasTerminalEvent(events: TimelineEvent[]): boolean {
  return events.some((event) => TERMINAL_SUBAGENT_TYPES.has(event.type));
}

function isCompatibleSubAgentEvent(events: TimelineEvent[], candidate: TimelineEvent): boolean {
  if (events.length === 0) return true;

  const first = events[0];
  if (!first) return true;

  const mode = getSubAgentGroupMode(first);
  const candidateMode = getSubAgentGroupMode(candidate);
  if (mode !== candidateMode) return false;
  if (mode !== 'single') return true;

  const candidateId = getSubAgentId(candidate);
  const knownIds = new Set(events.map((event) => getSubAgentId(event)).filter(Boolean));
  if (candidateId && knownIds.size > 0) return knownIds.has(candidateId);

  const candidateName = getSubAgentName(candidate);
  const normalizedCandidateName = normalizeSubAgentName(candidateName);
  const knownNames = new Set(
    events
      .map((event) => normalizeSubAgentName(getSubAgentName(event)))
      .filter((name) => name.length > 0)
  );
  if (normalizedCandidateName && knownNames.size > 0) {
    return knownNames.has(normalizedCandidateName);
  }

  if (!candidateId && !candidateName && TERMINAL_SUBAGENT_TYPES.has(candidate.type)) {
    return !hasTerminalEvent(events) || hasSharedTextMarker(events, candidate);
  }

  return knownIds.size === 0 && knownNames.size === 0;
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
    if (!SUBAGENT_EVENT_TYPES.has(item.type)) {
      break;
    }
    if (!isCompatibleSubAgentEvent(events, item)) {
      break;
    }
    events.push(item);
    endIndex = i;
    if (TERMINAL_SUBAGENT_TYPES.has(item.type)) {
      foundTerminal = true;
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
        if (
          TERMINAL_SUBAGENT_TYPES.has(item.type) &&
          getSubAgentId(item) === targetId &&
          isCompatibleSubAgentEvent(events, item)
        ) {
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
        group.subagentId = group.subagentId || d.subagentId || '';
        group.subagentName = group.subagentName || d.subagentName || '';
        group.status = 'success';
        group.summary = d.summary;
        group.tokensUsed = d.tokensUsed;
        group.executionTimeMs = d.executionTimeMs;
        break;
      }
      case 'subagent_failed': {
        const d = ev;
        group.subagentId = group.subagentId || d.subagentId || '';
        group.subagentName = group.subagentName || d.subagentName || '';
        group.status = 'error';
        group.error = d.error;
        break;
      }
      case 'subagent_run_started': {
        const d = ev;
        group.subagentId = group.subagentId || d.subagentId || '';
        group.subagentName = group.subagentName || d.subagentName || '';
        group.task = d.task;
        break;
      }
      case 'subagent_run_completed': {
        const d = ev;
        group.subagentId = group.subagentId || d.subagentId || '';
        group.subagentName = group.subagentName || d.subagentName || '';
        group.status = 'success';
        group.summary = d.summary || '';
        group.tokensUsed = d.tokensUsed;
        group.executionTimeMs = d.executionTimeMs;
        break;
      }
      case 'subagent_run_failed': {
        const d = ev;
        group.subagentId = group.subagentId || d.subagentId || '';
        group.subagentName = group.subagentName || d.subagentName || '';
        group.status = 'error';
        group.error = d.error || 'Unknown error';
        break;
      }
      case 'subagent_session_spawned': {
        const d = ev;
        group.subagentId = group.subagentId || d.subagentId || '';
        group.subagentName = group.subagentName || d.subagentName || '';
        group.task = group.task || 'Session spawned';
        break;
      }
      case 'subagent_session_message_sent': {
        const d = ev;
        group.subagentId = group.subagentId || d.subagentId || '';
        group.subagentName = group.subagentName || d.subagentName || '';
        group.task = group.task || `Follow-up sent from ${d.parentSubagentId}`;
        break;
      }
      case 'subagent_announce_retry': {
        const d = ev;
        group.subagentId = group.subagentId || d.subagentId || '';
        group.subagentName = group.subagentName || d.subagentName || '';
        group.task = `Retry ${String(d.attempt)}: ${d.error}`;
        break;
      }
      case 'subagent_announce_giveup': {
        const d = ev;
        group.subagentId = group.subagentId || d.subagentId || '';
        group.subagentName = group.subagentName || d.subagentName || '';
        group.status = 'error';
        group.error = `Give up after ${String(d.attempts)} attempts: ${d.error}`;
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
