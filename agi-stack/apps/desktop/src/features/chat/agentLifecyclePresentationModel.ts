import type { AgentTimelineItem } from '../../types';

export type AgentLifecycleFamily =
  | 'subagent'
  | 'agent'
  | 'agentMessage'
  | 'graphRun'
  | 'graphNode'
  | 'graphHandoff';

export type AgentLifecycleState =
  | 'running'
  | 'waiting'
  | 'complete'
  | 'failed'
  | 'attention'
  | 'sent'
  | 'received'
  | 'stopped';

export type AgentLifecyclePresentation = {
  family: AgentLifecycleFamily;
  state: AgentLifecycleState;
  subject: string;
  detail: string;
  isError: boolean;
};

const lifecycleEventDefinitions: Record<
  string,
  { family: AgentLifecycleFamily; state: AgentLifecycleState; detailFields?: string[] }
> = {
  subagent_spawning: { family: 'subagent', state: 'running' },
  subagent_routed: {
    family: 'subagent',
    state: 'running',
    detailFields: ['task', 'match_reason', 'reason'],
  },
  subagent_started: { family: 'subagent', state: 'running', detailFields: ['task'] },
  subagent_run_started: { family: 'subagent', state: 'running', detailFields: ['task'] },
  subagent_session_spawned: { family: 'subagent', state: 'running' },
  subagent_session_message_sent: { family: 'subagent', state: 'running' },
  subagent_session_update: {
    family: 'subagent',
    state: 'running',
    detailFields: ['status_message'],
  },
  subagent_steered: {
    family: 'subagent',
    state: 'running',
    detailFields: ['instruction'],
  },
  subagent_delegation: {
    family: 'subagent',
    state: 'running',
    detailFields: ['task_description'],
  },
  subagent_queued: {
    family: 'subagent',
    state: 'waiting',
    detailFields: ['reason'],
  },
  subagent_retry: {
    family: 'subagent',
    state: 'waiting',
    detailFields: ['reason'],
  },
  subagent_announce_retry: {
    family: 'subagent',
    state: 'waiting',
    detailFields: ['error'],
  },
  subagent_completed: {
    family: 'subagent',
    state: 'complete',
    detailFields: ['summary', 'final_content'],
  },
  subagent_run_completed: {
    family: 'subagent',
    state: 'complete',
    detailFields: ['summary'],
  },
  subagent_announce_sent: {
    family: 'subagent',
    state: 'complete',
    detailFields: ['result_preview'],
  },
  subagent_announce_received: {
    family: 'subagent',
    state: 'complete',
    detailFields: ['result_preview'],
  },
  subagent_failed: {
    family: 'subagent',
    state: 'failed',
    detailFields: ['error'],
  },
  subagent_run_failed: {
    family: 'subagent',
    state: 'failed',
    detailFields: ['error'],
  },
  subagent_killed: {
    family: 'subagent',
    state: 'failed',
    detailFields: ['kill_reason', 'error'],
  },
  subagent_doom_loop: {
    family: 'subagent',
    state: 'failed',
    detailFields: ['reason'],
  },
  subagent_depth_limited: {
    family: 'subagent',
    state: 'failed',
    detailFields: ['parent_subagent_name'],
  },
  subagent_spawn_rejected: {
    family: 'subagent',
    state: 'failed',
    detailFields: ['rejection_reason', 'rejection_code'],
  },
  subagent_announce_giveup: {
    family: 'subagent',
    state: 'failed',
    detailFields: ['error'],
  },
  subagent_announce_expired: {
    family: 'subagent',
    state: 'failed',
    detailFields: ['last_error'],
  },
  subagent_orphan_detected: {
    family: 'subagent',
    state: 'failed',
    detailFields: ['reason', 'action_taken'],
  },
  agent_spawned: {
    family: 'agent',
    state: 'running',
    detailFields: ['task_summary', 'taskSummary'],
  },
  agent_completed: {
    family: 'agent',
    state: 'complete',
    detailFields: ['result'],
  },
  agent_stopped: {
    family: 'agent',
    state: 'stopped',
    detailFields: ['reason'],
  },
  agent_message_sent: {
    family: 'agentMessage',
    state: 'sent',
    detailFields: ['message_preview', 'messagePreview'],
  },
  agent_message_received: {
    family: 'agentMessage',
    state: 'received',
    detailFields: ['message_preview', 'messagePreview'],
  },
  graph_run_started: {
    family: 'graphRun',
    state: 'running',
    detailFields: ['pattern'],
  },
  graph_run_completed: { family: 'graphRun', state: 'complete' },
  graph_run_failed: {
    family: 'graphRun',
    state: 'failed',
    detailFields: ['error_message'],
  },
  graph_run_cancelled: {
    family: 'graphRun',
    state: 'attention',
    detailFields: ['reason'],
  },
  graph_node_started: { family: 'graphNode', state: 'running' },
  graph_node_completed: { family: 'graphNode', state: 'complete' },
  graph_node_failed: {
    family: 'graphNode',
    state: 'failed',
    detailFields: ['error_message'],
  },
  graph_node_skipped: {
    family: 'graphNode',
    state: 'attention',
    detailFields: ['reason'],
  },
  graph_handoff: {
    family: 'graphHandoff',
    state: 'running',
    detailFields: ['context_summary'],
  },
};

/**
 * Convert authoritative SubAgent, multi-Agent, and graph protocol fields into
 * compact UI semantics. Event type membership and structured status fields are
 * protocol facts; no free-text classification is used here.
 */
export function agentLifecyclePresentation(
  item: AgentTimelineItem,
): AgentLifecyclePresentation | null {
  const definition = lifecycleEventDefinitions[item.type];
  if (!definition) return null;

  let state = definition.state;
  const explicitStatus = timelineEventString(item, ['status']);
  const success = timelineEventBoolean(item, 'success');
  if (success === false || explicitStatus === 'failed' || explicitStatus === 'error') {
    state = 'failed';
  } else if (explicitStatus === 'cancelled' || explicitStatus === 'skipped') {
    state = 'attention';
  }

  const subject = lifecycleSubject(item, definition.family);
  const detail = timelineEventString(item, definition.detailFields ?? []) ?? item.error ?? '';
  return {
    family: definition.family,
    state,
    subject,
    detail,
    isError: state === 'failed' || Boolean(item.isError || item.error),
  };
}

function lifecycleSubject(item: AgentTimelineItem, family: AgentLifecycleFamily): string {
  if (family === 'agentMessage') {
    const from = timelineEventString(item, [
      'from_agent_name',
      'fromAgentName',
      'from_agent_id',
      'fromAgentId',
    ]);
    const to =
      item.type === 'agent_message_sent'
        ? timelineEventString(item, [
            'to_agent_name',
            'toAgentName',
            'to_agent_id',
            'toAgentId',
          ])
        : timelineEventString(item, ['agent_name', 'agentName', 'agent_id', 'agentId']);
    if (from && to) return `${from} → ${to}`;
    return from ?? to ?? '';
  }
  if (family === 'agent') {
    return timelineEventString(item, ['agent_name', 'agentName', 'agent_id', 'agentId']) ?? '';
  }
  if (family === 'graphHandoff') {
    const from = timelineEventString(item, ['from_label', 'fromLabel']);
    const to = timelineEventString(item, ['to_label', 'toLabel']);
    if (from && to) return `${from} → ${to}`;
    return from ?? to ?? '';
  }
  if (family === 'graphRun') {
    return timelineEventString(item, ['graph_name', 'graphName']) ?? '';
  }
  if (family === 'graphNode') {
    return timelineEventString(item, ['node_label', 'nodeLabel']) ?? '';
  }
  return (
    timelineEventString(item, [
      'subagent_name',
      'subagentName',
      'to_subagent_name',
      'toSubagentName',
    ]) ?? ''
  );
}

function timelineEventString(item: AgentTimelineItem, keys: string[]): string | null {
  const payload = isRecord(item.payload) ? item.payload : null;
  for (const source of [payload, item]) {
    if (!source) continue;
    for (const key of keys) {
      const value = source[key];
      if (typeof value === 'string' && value.trim()) return value.trim();
    }
  }
  return null;
}

function timelineEventBoolean(item: AgentTimelineItem, key: string): boolean | null {
  const payload = isRecord(item.payload) ? item.payload : null;
  const value = payload?.[key] ?? item[key];
  return typeof value === 'boolean' ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}
