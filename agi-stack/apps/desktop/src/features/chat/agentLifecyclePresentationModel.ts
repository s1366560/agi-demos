import type { AgentTimelineItem } from '../../types';

export type AgentLifecycleFamily =
  | 'subagent'
  | 'agent'
  | 'agentMessage'
  | 'parallel'
  | 'chain'
  | 'chainStep'
  | 'background'
  | 'routing'
  | 'selection'
  | 'policy'
  | 'toolset'
  | 'doomLoop'
  | 'skill'
  | 'model'
  | 'context'
  | 'mcpApp'
  | 'memory'
  | 'task'
  | 'artifact'
  | 'sandbox'
  | 'desktop'
  | 'terminal'
  | 'httpService'
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
  | 'blocked'
  | 'scheduled'
  | 'ready'
  | 'stopped';

export type AgentLifecyclePresentation = {
  family: AgentLifecycleFamily;
  state: AgentLifecycleState;
  subject: string;
  detail: string;
  isError: boolean;
  progress?: {
    unit:
      | 'tasks'
      | 'steps'
      | 'tools'
      | 'filteredTools'
      | 'calls'
      | 'tokens'
      | 'messages'
      | 'memories'
      | 'artifacts';
    current?: number;
    total: number;
  };
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
  parallel_started: { family: 'parallel', state: 'running' },
  parallel_completed: { family: 'parallel', state: 'complete' },
  chain_started: { family: 'chain', state: 'running' },
  chain_step_started: {
    family: 'chainStep',
    state: 'running',
    detailFields: ['task_preview', 'taskPreview', 'subagent_name', 'subagentName'],
  },
  chain_step_completed: {
    family: 'chainStep',
    state: 'complete',
    detailFields: ['summary'],
  },
  chain_completed: {
    family: 'chain',
    state: 'complete',
    detailFields: ['final_summary', 'finalSummary'],
  },
  background_launched: {
    family: 'background',
    state: 'running',
    detailFields: ['task', 'task_description', 'taskDescription'],
  },
  execution_path_decided: {
    family: 'routing',
    state: 'complete',
    detailFields: ['reason'],
  },
  selection_trace: { family: 'selection', state: 'complete' },
  policy_filtered: { family: 'policy', state: 'complete' },
  tool_policy_denied: {
    family: 'policy',
    state: 'blocked',
    detailFields: ['denial_reason', 'denialReason', 'policy_layer', 'policyLayer'],
  },
  toolset_changed: { family: 'toolset', state: 'complete' },
  doom_loop_detected: { family: 'doomLoop', state: 'failed' },
  doom_loop_intervened: { family: 'doomLoop', state: 'complete' },
  skill_matched: {
    family: 'skill',
    state: 'complete',
    detailFields: ['execution_mode', 'executionMode'],
  },
  skill_execution_start: {
    family: 'skill',
    state: 'running',
    detailFields: ['query'],
  },
  skill_tool_start: { family: 'skill', state: 'running' },
  skill_tool_result: {
    family: 'skill',
    state: 'complete',
    detailFields: ['error'],
  },
  skill_execution_complete: {
    family: 'skill',
    state: 'complete',
    detailFields: ['summary', 'error'],
  },
  skill_fallback: {
    family: 'skill',
    state: 'attention',
    detailFields: ['error', 'reason'],
  },
  model_switch_requested: {
    family: 'model',
    state: 'scheduled',
    detailFields: ['reason', 'provider_name', 'providerName', 'provider_type', 'providerType'],
  },
  model_override_rejected: {
    family: 'model',
    state: 'blocked',
    detailFields: ['reason'],
  },
  context_status: { family: 'context', state: 'complete' },
  context_compressed: {
    family: 'context',
    state: 'complete',
    detailFields: ['compression_level', 'compressionLevel'],
  },
  mcp_app_registered: { family: 'mcpApp', state: 'ready' },
  mcp_app_result: { family: 'mcpApp', state: 'complete' },
  memory_recalled: { family: 'memory', state: 'complete' },
  memory_captured: { family: 'memory', state: 'complete' },
  task_start: { family: 'task', state: 'running' },
  task_complete: { family: 'task', state: 'complete' },
  artifact_created: {
    family: 'artifact',
    state: 'running',
    detailFields: ['source_tool', 'sourceTool'],
  },
  artifact_ready: {
    family: 'artifact',
    state: 'ready',
    detailFields: ['source_tool', 'sourceTool'],
  },
  artifact_error: {
    family: 'artifact',
    state: 'failed',
    detailFields: ['error'],
  },
  artifacts_batch: { family: 'artifact', state: 'complete' },
  sandbox_created: { family: 'sandbox', state: 'ready' },
  sandbox_status: { family: 'sandbox', state: 'running' },
  sandbox_terminated: { family: 'sandbox', state: 'stopped' },
  desktop_started: { family: 'desktop', state: 'ready' },
  desktop_status: { family: 'desktop', state: 'running' },
  desktop_stopped: { family: 'desktop', state: 'stopped' },
  terminal_started: { family: 'terminal', state: 'ready' },
  terminal_status: { family: 'terminal', state: 'running' },
  terminal_stopped: { family: 'terminal', state: 'stopped' },
  http_service_started: { family: 'httpService', state: 'ready' },
  http_service_updated: { family: 'httpService', state: 'running' },
  http_service_stopped: { family: 'httpService', state: 'stopped' },
  http_service_error: { family: 'httpService', state: 'failed' },
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
 * Convert authoritative SubAgent, multi-Agent, skill, MCP App, orchestration,
 * and graph protocol fields into compact UI semantics. Event type membership
 * and structured status fields are protocol facts; no free-text classification
 * is used here.
 */
export function agentLifecyclePresentation(
  item: AgentTimelineItem,
): AgentLifecyclePresentation | null {
  const definition = lifecycleEventDefinitions[item.type];
  if (!definition) return null;

  let state = definition.state;
  const explicitStatus = timelineEventString(item, ['status']);
  if (
    lifecycleFailed(item) ||
    (definition.family === 'artifact' && Boolean(timelineEventString(item, ['error']))) ||
    explicitStatus === 'failed' ||
    explicitStatus === 'error'
  ) {
    state = 'failed';
  } else if (isRuntimeInfrastructureFamily(definition.family)) {
    const running = timelineEventBoolean(item, 'running');
    if (
      running === false ||
      explicitStatus === 'stopped' ||
      explicitStatus === 'terminated' ||
      explicitStatus === 'disconnected'
    ) {
      state = 'stopped';
    } else if (
      running === true ||
      explicitStatus === 'running' ||
      explicitStatus === 'ready' ||
      explicitStatus === 'connected'
    ) {
      state = 'ready';
    }
  } else if (explicitStatus === 'cancelled' || explicitStatus === 'skipped') {
    state = 'attention';
  } else if (
    item.type === 'policy_filtered' &&
    (timelineEventNumber(item, ['removed_total', 'removedTotal']) ?? 0) > 0
  ) {
    state = 'attention';
  } else if (
    item.type === 'artifact_created' &&
    Boolean(timelineEventString(item, ['url']))
  ) {
    state = 'ready';
  }

  const subject = lifecycleSubject(item, definition.family);
  const detail = lifecycleDetail(item, definition.detailFields ?? []);
  const progress = lifecycleProgress(item, definition.family);
  return {
    family: definition.family,
    state,
    subject,
    detail,
    isError:
      state === 'failed' ||
      (item.type !== 'skill_fallback' && Boolean(item.isError || item.error)),
    ...(progress ? { progress } : {}),
  };
}

function lifecycleSubject(item: AgentTimelineItem, family: AgentLifecycleFamily): string {
  if (isRuntimeInfrastructureFamily(family)) {
    if (family === 'httpService') {
      return (
        timelineEventString(item, ['service_name', 'serviceName']) ??
        timelineEventString(item, ['service_id', 'serviceId']) ??
        ''
      );
    }
    if (family === 'terminal') {
      return (
        timelineEventString(item, ['session_id', 'sessionId']) ??
        timelineEventString(item, ['sandbox_id', 'sandboxId']) ??
        ''
      );
    }
    return timelineEventString(item, ['sandbox_id', 'sandboxId']) ?? '';
  }
  if (family === 'model') {
    return timelineEventString(item, ['model']) ?? '';
  }
  if (family === 'doomLoop') {
    return item.type === 'doom_loop_detected'
      ? timelineEventString(item, ['tool_name', 'toolName', 'tool']) ?? ''
      : timelineEventString(item, ['action']) ?? '';
  }
  if (family === 'context') {
    return item.type === 'context_compressed'
      ? timelineEventString(item, ['compression_strategy', 'compressionStrategy']) ?? ''
      : timelineEventString(item, ['compression_level', 'compressionLevel']) ?? '';
  }
  if (family === 'mcpApp') {
    return (
      timelineEventString(item, ['title']) ??
      timelineEventRecordString(item, ['ui_metadata', 'uiMetadata'], ['title']) ??
      timelineEventString(item, ['tool_name', 'toolName', 'app_id', 'appId']) ??
      ''
    );
  }
  if (family === 'memory') {
    return item.type === 'memory_captured'
      ? timelineEventStringArray(item, ['categories']).join(', ')
      : '';
  }
  if (family === 'task') {
    return item.type === 'task_start'
      ? timelineEventString(item, ['content']) ?? ''
      : '';
  }
  if (family === 'artifact') {
    if (item.type === 'artifacts_batch') {
      return timelineEventString(item, ['source_tool', 'sourceTool']) ?? '';
    }
    return (
      timelineEventString(item, ['filename', 'artifact_id', 'artifactId']) ?? ''
    );
  }
  if (family === 'skill') {
    const skill = timelineEventString(item, ['skill_name', 'skillName']);
    if (item.type === 'skill_tool_start' || item.type === 'skill_tool_result') {
      const tool = timelineEventString(item, ['tool_name', 'toolName']);
      if (skill && tool) return `${skill} → ${tool}`;
      return skill ?? tool ?? '';
    }
    return skill ?? '';
  }
  if (family === 'routing') {
    const path = timelineEventString(item, ['path']);
    const target = timelineEventString(item, ['target']);
    if (path && target) return `${path} → ${target}`;
    return path ?? target ?? '';
  }
  if (family === 'selection') {
    return timelineEventString(item, ['domain_lane', 'domainLane']) ?? '';
  }
  if (family === 'policy') {
    if (item.type === 'tool_policy_denied') {
      return timelineEventString(item, ['tool_name', 'toolName', 'agent_id', 'agentId']) ?? '';
    }
    return timelineEventString(item, ['domain_lane', 'domainLane']) ?? '';
  }
  if (family === 'toolset') {
    const namedSubject = timelineEventString(item, [
      'plugin_name',
      'pluginName',
      'server_name',
      'serverName',
      'skill_name',
      'skillName',
    ]);
    return namedSubject ?? timelineEventString(item, ['source']) ?? '';
  }
  if (family === 'parallel') {
    const sourceKey = item.type === 'parallel_started' ? 'subtasks' : 'results';
    const names = timelineEventRecordArray(item, [sourceKey]).flatMap((entry) => {
      const name = firstRecordString(entry, [
        'subagent_name',
        'subagentName',
        'agent_name',
        'agentName',
      ]);
      return name ? [name] : [];
    });
    return uniqueStrings(names).join(', ');
  }
  if (family === 'chain') {
    const name = timelineEventString(item, ['chain_name', 'chainName']);
    if (name) return name;
    return timelineEventStringArray(item, ['step_names', 'stepNames']).join(' → ');
  }
  if (family === 'chainStep') {
    return timelineEventString(item, ['step_name', 'stepName']) ?? '';
  }
  if (family === 'background') {
    return timelineEventString(item, ['subagent_name', 'subagentName']) ?? '';
  }
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

function lifecycleDetail(item: AgentTimelineItem, detailFields: string[]): string {
  const lifecycle = lifecycleEventDefinitions[item.type];
  if (lifecycle && isRuntimeInfrastructureFamily(lifecycle.family)) {
    const error = timelineEventString(item, ['error_message', 'errorMessage', 'error']);
    if (error) return error;
    if (lifecycle.family === 'sandbox') {
      return (
        timelineEventString(item, ['endpoint', 'websocket_url', 'websocketUrl']) ?? ''
      );
    }
    if (lifecycle.family === 'desktop') {
      return uniqueStrings(
        [
          timelineEventString(item, ['resolution']),
          timelineEventString(item, ['display']),
          timelineEventString(item, ['url', 'desktop_url', 'desktopUrl']),
        ].flatMap((value) => (value ? [value] : [])),
      ).join(' · ');
    }
    if (lifecycle.family === 'httpService') {
      const subject = lifecycleSubject(item, 'httpService');
      const serviceId = timelineEventString(item, ['service_id', 'serviceId']);
      const previewUrl = timelineEventString(item, [
        'proxy_url',
        'proxyUrl',
        'preview_url',
        'previewUrl',
        'service_url',
        'serviceUrl',
      ]);
      return uniqueStrings(
        [serviceId === subject ? null : serviceId, previewUrl].flatMap((value) =>
          value ? [value] : [],
        ),
      ).join(' · ');
    }
    const subject = lifecycleSubject(item, 'terminal');
    const sandbox = timelineEventString(item, ['sandbox_id', 'sandboxId']);
    return uniqueStrings(
      [
        sandbox === subject ? null : sandbox,
        timelineEventString(item, ['url', 'terminal_url', 'terminalUrl']),
      ].flatMap((value) => (value ? [value] : [])),
    ).join(' · ');
  }
  if (item.type === 'mcp_app_registered' || item.type === 'mcp_app_result') {
    const subject = lifecycleSubject(item, 'mcpApp');
    const server = timelineEventString(item, ['server_name', 'serverName']);
    const tool = timelineEventString(item, ['tool_name', 'toolName']);
    const source =
      item.type === 'mcp_app_registered' ? timelineEventString(item, ['source']) : null;
    return uniqueStrings(
      [server, tool === subject ? null : tool, source].flatMap((value) =>
        value ? [value] : [],
      ),
    ).join(' · ');
  }
  if (item.type === 'selection_trace' || item.type === 'policy_filtered') {
    return timelineEventStringArray(item, [
      'budget_exceeded_stages',
      'budgetExceededStages',
    ]).join(', ');
  }
  if (item.type === 'toolset_changed') {
    const subject = lifecycleSubject(item, 'toolset');
    return (
      timelineEventString(item, ['action']) ??
      (subject ? timelineEventString(item, ['source']) : null) ??
      ''
    );
  }
  if (item.type === 'parallel_completed') {
    const failedAgents = timelineEventStringArray(item, ['failed_agents', 'failedAgents']);
    if (failedAgents.length) return failedAgents.join(', ');
    const results = timelineEventRecordArray(item, ['results']);
    const failedResultNames = results.flatMap((result) => {
      if (result.success !== false) return [];
      const name = firstRecordString(result, [
        'subagent_name',
        'subagentName',
        'agent_name',
        'agentName',
      ]);
      return name ? [name] : [];
    });
    if (failedResultNames.length) return uniqueStrings(failedResultNames).join(', ');
    for (const result of results) {
      const summary = firstRecordString(result, ['summary', 'result', 'final_content']);
      if (summary) return summary;
    }
  }
  return timelineEventString(item, detailFields) ?? item.error ?? '';
}

function isRuntimeInfrastructureFamily(family: AgentLifecycleFamily): boolean {
  return (
    family === 'sandbox' ||
    family === 'desktop' ||
    family === 'terminal' ||
    family === 'httpService'
  );
}

function lifecycleProgress(
  item: AgentTimelineItem,
  family: AgentLifecycleFamily,
): AgentLifecyclePresentation['progress'] {
  if (family === 'doomLoop' && item.type === 'doom_loop_detected') {
    const total = timelineEventNumber(item, ['call_count', 'callCount']);
    return total === null ? undefined : { unit: 'calls', total };
  }
  if (family === 'context') {
    if (item.type === 'context_status') {
      const total = timelineEventNumber(item, ['token_budget', 'tokenBudget']);
      const current = timelineEventNumber(item, ['current_tokens', 'currentTokens']);
      if (total === null) return undefined;
      return current === null
        ? { unit: 'tokens', total }
        : { unit: 'tokens', current, total };
    }
    if (item.type === 'context_compressed') {
      const total = timelineEventNumber(item, [
        'original_message_count',
        'originalMessageCount',
      ]);
      const current = timelineEventNumber(item, [
        'final_message_count',
        'finalMessageCount',
      ]);
      if (total === null) return undefined;
      return current === null
        ? { unit: 'messages', total }
        : { unit: 'messages', current, total };
    }
  }
  if (family === 'memory') {
    const explicitCount = timelineEventNumber(item, [
      item.type === 'memory_recalled' ? 'count' : 'captured_count',
      'capturedCount',
    ]);
    const recalledCount = timelineEventRecordArray(item, ['memories']).length;
    const total =
      explicitCount ??
      (item.type === 'memory_recalled' && recalledCount > 0 ? recalledCount : null);
    return total === null ? undefined : { unit: 'memories', total };
  }
  if (family === 'task') {
    const total = timelineEventNumber(item, ['total_tasks', 'totalTasks']);
    const orderIndex = timelineEventNumber(item, ['order_index', 'orderIndex']);
    if (total === null) return undefined;
    return orderIndex === null
      ? { unit: 'tasks', total }
      : { unit: 'tasks', current: orderIndex + 1, total };
  }
  if (family === 'artifact' && item.type === 'artifacts_batch') {
    const total = timelineEventRecordArray(item, ['artifacts']).length;
    return total > 0 ? { unit: 'artifacts', total } : undefined;
  }
  if (family === 'skill') {
    if (item.type === 'skill_matched') {
      const total = timelineEventStringArray(item, ['tools']).length;
      return total > 0 ? { unit: 'tools', total } : undefined;
    }
    if (item.type === 'skill_execution_start') {
      const total = timelineEventNumber(item, ['total_steps', 'totalSteps']);
      return total === null ? undefined : { unit: 'steps', total };
    }
    if (item.type === 'skill_tool_start' || item.type === 'skill_tool_result') {
      const total = timelineEventNumber(item, ['total_steps', 'totalSteps']);
      const current = timelineEventNumber(item, ['step_index', 'stepIndex']);
      if (total === null) return undefined;
      return current === null
        ? { unit: 'steps', total }
        : { unit: 'steps', current, total };
    }
    if (item.type === 'skill_execution_complete') {
      const total = timelineEventRecordArray(item, ['tool_results', 'toolResults']).length;
      return total > 0 ? { unit: 'tools', total } : undefined;
    }
  }
  if (family === 'selection') {
    const total = timelineEventNumber(item, ['initial_count', 'initialCount']);
    const current = timelineEventNumber(item, ['final_count', 'finalCount']);
    if (total === null) return undefined;
    return current === null
      ? { unit: 'tools', total }
      : { unit: 'tools', current, total };
  }
  if (family === 'policy' && item.type === 'policy_filtered') {
    const total = timelineEventNumber(item, ['removed_total', 'removedTotal']);
    return total === null ? undefined : { unit: 'filteredTools', total };
  }
  if (family === 'toolset') {
    const total = timelineEventNumber(item, [
      'refreshed_tool_count',
      'refreshedToolCount',
    ]);
    return total === null ? undefined : { unit: 'tools', total };
  }
  if (family === 'parallel') {
    const recordCount = timelineEventRecordArray(item, [
      item.type === 'parallel_started' ? 'subtasks' : 'results',
    ]).length;
    const total =
      timelineEventNumber(item, [
        'total_tasks',
        'totalTasks',
        'task_count',
        'taskCount',
      ]) ?? (recordCount > 0 ? recordCount : null);
    if (total === null) return undefined;
    if (item.type === 'parallel_started') return { unit: 'tasks', total };

    const explicitCompleted = timelineEventNumber(item, ['completed']);
    const succeeded = timelineEventNumber(item, ['succeeded']);
    const failed = timelineEventNumber(item, ['failed']);
    const current =
      explicitCompleted ??
      (succeeded !== null && failed !== null
        ? succeeded + failed
        : recordCount > 0
          ? recordCount
          : undefined);
    return current === undefined
      ? { unit: 'tasks', total }
      : { unit: 'tasks', current, total };
  }
  if (family === 'chain') {
    const total = timelineEventNumber(item, [
      'total_steps',
      'totalSteps',
      'step_count',
      'stepCount',
    ]);
    if (total === null) return undefined;
    if (item.type === 'chain_started') return { unit: 'steps', total };
    const current = timelineEventNumber(item, ['steps_completed', 'stepsCompleted']);
    return current === null
      ? { unit: 'steps', total }
      : { unit: 'steps', current, total };
  }
  return undefined;
}

function lifecycleFailed(item: AgentTimelineItem): boolean {
  if (timelineEventBoolean(item, 'success') === false) return true;
  if (item.type === 'toolset_changed') {
    return timelineEventString(item, ['refresh_status', 'refreshStatus']) === 'failed';
  }
  if (item.type !== 'parallel_completed') return false;

  const resultStates = timelineEventRecordArray(item, ['results']).flatMap((result) =>
    typeof result.success === 'boolean' ? [result.success] : [],
  );
  if (resultStates.length) return resultStates.some((success) => !success);

  const failed = timelineEventNumber(item, ['failed']);
  if (failed !== null) return failed > 0;
  if (timelineEventStringArray(item, ['failed_agents', 'failedAgents']).length) return true;

  const succeeded = timelineEventNumber(item, ['succeeded']);
  const total = timelineEventNumber(item, ['total_tasks', 'totalTasks']);
  if (succeeded !== null && total !== null) return succeeded < total;
  return (
    timelineEventBoolean(item, 'all_succeeded') === false ||
    timelineEventBoolean(item, 'allSucceeded') === false
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

function timelineEventNumber(item: AgentTimelineItem, keys: string[]): number | null {
  const payload = isRecord(item.payload) ? item.payload : null;
  for (const source of [payload, item]) {
    if (!source) continue;
    for (const key of keys) {
      const value = source[key];
      if (typeof value === 'number' && Number.isFinite(value) && value >= 0) return value;
    }
  }
  return null;
}

function timelineEventStringArray(item: AgentTimelineItem, keys: string[]): string[] {
  const payload = isRecord(item.payload) ? item.payload : null;
  for (const source of [payload, item]) {
    if (!source) continue;
    for (const key of keys) {
      const value = source[key];
      if (!Array.isArray(value)) continue;
      return value.flatMap((entry) =>
        typeof entry === 'string' && entry.trim() ? [entry.trim()] : [],
      );
    }
  }
  return [];
}

function timelineEventRecordArray(
  item: AgentTimelineItem,
  keys: string[],
): Array<Record<string, unknown>> {
  const payload = isRecord(item.payload) ? item.payload : null;
  for (const source of [payload, item]) {
    if (!source) continue;
    for (const key of keys) {
      const value = source[key];
      if (Array.isArray(value)) return value.filter(isRecord);
    }
  }
  return [];
}

function timelineEventRecordString(
  item: AgentTimelineItem,
  recordKeys: string[],
  valueKeys: string[],
): string | null {
  const payload = isRecord(item.payload) ? item.payload : null;
  for (const source of [payload, item]) {
    if (!source) continue;
    for (const recordKey of recordKeys) {
      const record = source[recordKey];
      if (!isRecord(record)) continue;
      const value = firstRecordString(record, valueKeys);
      if (value) return value;
    }
  }
  return null;
}

function firstRecordString(record: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return null;
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values)];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}
