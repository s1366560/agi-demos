import type { AgentTimelineItem } from '../../types';

export type SessionExecutionGraphRunStatus =
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type SessionExecutionGraphNodeStatus =
  | 'running'
  | 'completed'
  | 'failed'
  | 'skipped';

export type SessionExecutionGraphNode = {
  nodeId: string;
  label: string;
  agentDefinitionId: string;
  agentSessionId: string | null;
  status: SessionExecutionGraphNodeStatus;
  outputKeys: string[];
  errorMessage: string | null;
  skipReason: string | null;
  durationSeconds: number | null;
  startedAtUs: number;
  completedAtUs: number | null;
};

export type SessionExecutionGraphHandoff = {
  id: string;
  fromNodeId: string;
  toNodeId: string;
  fromLabel: string;
  toLabel: string;
  contextSummary: string;
  eventTimeUs: number;
};

export type SessionExecutionGraphRun = {
  graphRunId: string;
  graphId: string;
  graphName: string;
  pattern: string;
  entryNodeIds: string[];
  status: SessionExecutionGraphRunStatus;
  nodes: SessionExecutionGraphNode[];
  layers: SessionExecutionGraphNode[][];
  handoffs: SessionExecutionGraphHandoff[];
  totalSteps: number | null;
  durationSeconds: number | null;
  errorMessage: string | null;
  failedNodeId: string | null;
  cancelReason: string | null;
  startedAtUs: number;
  completedAtUs: number | null;
};

export type SessionExecutionGraphModel = {
  runs: SessionExecutionGraphRun[];
  activeRun: SessionExecutionGraphRun | null;
  summary: {
    runs: number;
    nodes: number;
    running: number;
    completed: number;
    failed: number;
    skipped: number;
    handoffs: number;
  };
};

type MutableGraphRun = Omit<SessionExecutionGraphRun, 'nodes' | 'layers'> & {
  nodes: Map<string, SessionExecutionGraphNode>;
};

const sessionExecutionGraphEventTypes = new Set([
  'graph_run_started',
  'graph_run_completed',
  'graph_run_failed',
  'graph_run_cancelled',
  'graph_node_started',
  'graph_node_completed',
  'graph_node_failed',
  'graph_node_skipped',
  'graph_handoff',
]);

export function isSessionExecutionGraphEvent(value: unknown): boolean {
  const root = recordValue(value);
  const type = stringValue(root?.type ?? root?.event_type);
  return Boolean(type && sessionExecutionGraphEventTypes.has(type));
}

export function buildSessionExecutionGraph(
  items: readonly AgentTimelineItem[],
): SessionExecutionGraphModel {
  const runs = new Map<string, MutableGraphRun>();
  const seenEventIds = new Set<string>();
  const orderedItems = [...items].sort(compareTimelineItems);

  for (const item of orderedItems) {
    if (!isSessionExecutionGraphEvent(item) || seenEventIds.has(item.id)) continue;
    seenEventIds.add(item.id);
    const type = eventType(item);
    const eventTimeUs = timelineTimeUs(item);
    const graphRunId = fieldString(item, 'graph_run_id', 'graphRunId');
    if (!graphRunId) continue;

    if (type === 'graph_run_started') {
      const graphId = fieldString(item, 'graph_id', 'graphId');
      const graphName = fieldString(item, 'graph_name', 'graphName');
      if (!graphId || !graphName) continue;
      runs.set(graphRunId, {
        graphRunId,
        graphId,
        graphName,
        pattern: fieldString(item, 'pattern') ?? '',
        entryNodeIds: fieldStringList(item, 'entry_node_ids', 'entryNodeIds') ?? [],
        status: 'running',
        nodes: new Map(),
        handoffs: [],
        totalSteps: null,
        durationSeconds: null,
        errorMessage: null,
        failedNodeId: null,
        cancelReason: null,
        startedAtUs: eventTimeUs,
        completedAtUs: null,
      });
      continue;
    }

    const run = runs.get(graphRunId);
    if (!run) continue;

    if (type === 'graph_run_completed') {
      run.status = 'completed';
      run.totalSteps = fieldNumber(item, 'total_steps', 'totalSteps');
      run.durationSeconds = fieldNumber(item, 'duration_seconds', 'durationSeconds');
      run.completedAtUs = eventTimeUs;
      continue;
    }
    if (type === 'graph_run_failed') {
      run.status = 'failed';
      run.errorMessage = fieldString(item, 'error_message', 'errorMessage');
      run.failedNodeId = fieldString(item, 'failed_node_id', 'failedNodeId');
      run.completedAtUs = eventTimeUs;
      continue;
    }
    if (type === 'graph_run_cancelled') {
      run.status = 'cancelled';
      run.cancelReason = fieldString(item, 'reason');
      run.completedAtUs = eventTimeUs;
      continue;
    }
    if (type === 'graph_handoff') {
      const fromNodeId = fieldString(item, 'from_node_id', 'fromNodeId');
      const toNodeId = fieldString(item, 'to_node_id', 'toNodeId');
      if (!fromNodeId || !toNodeId) continue;
      run.handoffs.push({
        id: item.id,
        fromNodeId,
        toNodeId,
        fromLabel:
          fieldString(item, 'from_label', 'fromLabel') ??
          run.nodes.get(fromNodeId)?.label ??
          fromNodeId,
        toLabel:
          fieldString(item, 'to_label', 'toLabel') ?? run.nodes.get(toNodeId)?.label ?? toNodeId,
        contextSummary: fieldString(item, 'context_summary', 'contextSummary') ?? '',
        eventTimeUs,
      });
      continue;
    }

    const nodeId = fieldString(item, 'node_id', 'nodeId');
    if (!nodeId) continue;
    if (type === 'graph_node_started') {
      const label = fieldString(item, 'node_label', 'nodeLabel');
      const agentDefinitionId = fieldString(
        item,
        'agent_definition_id',
        'agentDefinitionId',
      );
      if (!label || !agentDefinitionId) continue;
      run.nodes.set(nodeId, {
        nodeId,
        label,
        agentDefinitionId,
        agentSessionId: fieldString(item, 'agent_session_id', 'agentSessionId'),
        status: 'running',
        outputKeys: [],
        errorMessage: null,
        skipReason: null,
        durationSeconds: null,
        startedAtUs: eventTimeUs,
        completedAtUs: null,
      });
      continue;
    }

    const node = run.nodes.get(nodeId);
    if (!node) continue;
    if (type === 'graph_node_completed') {
      run.nodes.set(nodeId, {
        ...node,
        status: 'completed',
        outputKeys: fieldStringList(item, 'output_keys', 'outputKeys') ?? [],
        durationSeconds: fieldNumber(item, 'duration_seconds', 'durationSeconds'),
        completedAtUs: eventTimeUs,
      });
      continue;
    }
    if (type === 'graph_node_failed') {
      run.nodes.set(nodeId, {
        ...node,
        status: 'failed',
        errorMessage: fieldString(item, 'error_message', 'errorMessage'),
        completedAtUs: eventTimeUs,
      });
      continue;
    }
    run.nodes.set(nodeId, {
      ...node,
      status: 'skipped',
      skipReason: fieldString(item, 'reason'),
      completedAtUs: eventTimeUs,
    });
  }

  const frozenRuns = [...runs.values()]
    .sort((left, right) => right.startedAtUs - left.startedAtUs || left.graphRunId.localeCompare(right.graphRunId))
    .map(freezeRun);
  const activeRun = frozenRuns[0] ?? null;
  const statuses = activeRun?.nodes.map((node) => node.status) ?? [];
  const countStatus = (status: SessionExecutionGraphNodeStatus) =>
    statuses.reduce((count, candidate) => count + Number(candidate === status), 0);

  return {
    runs: frozenRuns,
    activeRun,
    summary: {
      runs: frozenRuns.length,
      nodes: activeRun?.nodes.length ?? 0,
      running: countStatus('running'),
      completed: countStatus('completed'),
      failed: countStatus('failed'),
      skipped: countStatus('skipped'),
      handoffs: activeRun?.handoffs.length ?? 0,
    },
  };
}

function freezeRun(run: MutableGraphRun): SessionExecutionGraphRun {
  const nodes = [...run.nodes.values()].sort(
    (left, right) => left.startedAtUs - right.startedAtUs || left.nodeId.localeCompare(right.nodeId),
  );
  const handoffs = [...run.handoffs].sort(
    (left, right) => left.eventTimeUs - right.eventTimeUs || left.id.localeCompare(right.id),
  );
  return {
    ...run,
    entryNodeIds: [...run.entryNodeIds],
    nodes,
    layers: buildGraphLayers(nodes, handoffs, run.entryNodeIds),
    handoffs,
  };
}

function buildGraphLayers(
  nodes: readonly SessionExecutionGraphNode[],
  handoffs: readonly SessionExecutionGraphHandoff[],
  entryNodeIds: readonly string[],
): SessionExecutionGraphNode[][] {
  if (!nodes.length) return [];
  const nodeById = new Map(nodes.map((node) => [node.nodeId, node]));
  const incomingCount = new Map(nodes.map((node) => [node.nodeId, 0]));
  const outgoing = new Map<string, string[]>();
  for (const handoff of handoffs) {
    if (!nodeById.has(handoff.fromNodeId) || !nodeById.has(handoff.toNodeId)) continue;
    incomingCount.set(handoff.toNodeId, (incomingCount.get(handoff.toNodeId) ?? 0) + 1);
    outgoing.set(handoff.fromNodeId, [
      ...(outgoing.get(handoff.fromNodeId) ?? []),
      handoff.toNodeId,
    ]);
  }

  const entryOrder = new Map(entryNodeIds.map((nodeId, index) => [nodeId, index]));
  const queue = nodes
    .filter((node) => (incomingCount.get(node.nodeId) ?? 0) === 0)
    .sort((left, right) => {
      const leftEntry = entryOrder.get(left.nodeId) ?? Number.MAX_SAFE_INTEGER;
      const rightEntry = entryOrder.get(right.nodeId) ?? Number.MAX_SAFE_INTEGER;
      return leftEntry - rightEntry || left.startedAtUs - right.startedAtUs;
    })
    .map((node) => node.nodeId);
  const levelByNodeId = new Map(queue.map((nodeId) => [nodeId, 0]));
  const visited = new Set<string>();

  while (queue.length) {
    const nodeId = queue.shift();
    if (!nodeId || visited.has(nodeId)) continue;
    visited.add(nodeId);
    const level = levelByNodeId.get(nodeId) ?? 0;
    for (const targetId of outgoing.get(nodeId) ?? []) {
      levelByNodeId.set(targetId, Math.max(levelByNodeId.get(targetId) ?? 0, level + 1));
      const remaining = (incomingCount.get(targetId) ?? 0) - 1;
      incomingCount.set(targetId, remaining);
      if (remaining === 0) queue.push(targetId);
    }
  }

  let fallbackLevel = Math.max(0, ...levelByNodeId.values());
  for (const node of nodes) {
    if (levelByNodeId.has(node.nodeId)) continue;
    fallbackLevel += 1;
    levelByNodeId.set(node.nodeId, fallbackLevel);
  }
  const layers: SessionExecutionGraphNode[][] = [];
  for (const node of nodes) {
    const level = levelByNodeId.get(node.nodeId) ?? 0;
    (layers[level] ??= []).push(node);
  }
  return layers.filter((layer): layer is SessionExecutionGraphNode[] => Boolean(layer?.length));
}

function compareTimelineItems(left: AgentTimelineItem, right: AgentTimelineItem): number {
  return (
    timelineTimeUs(left) - timelineTimeUs(right) ||
    left.eventCounter - right.eventCounter ||
    left.id.localeCompare(right.id)
  );
}

function eventType(item: AgentTimelineItem): string {
  const root = item as unknown as Record<string, unknown>;
  return stringValue(root.type ?? root.event_type) ?? '';
}

function timelineTimeUs(item: AgentTimelineItem): number {
  if (Number.isFinite(item.eventTimeUs)) return item.eventTimeUs;
  return Number.isFinite(item.timestamp) ? Number(item.timestamp) * 1_000 : 0;
}

function fieldString(item: AgentTimelineItem, ...keys: string[]): string | null {
  const root = item as unknown as Record<string, unknown>;
  const payload = recordValue(root.payload);
  for (const key of keys) {
    const value = stringValue(root[key]) ?? stringValue(payload?.[key]);
    if (value) return value;
  }
  return null;
}

function fieldStringList(item: AgentTimelineItem, ...keys: string[]): string[] | null {
  const root = item as unknown as Record<string, unknown>;
  const payload = recordValue(root.payload);
  for (const key of keys) {
    const value = root[key] ?? payload?.[key];
    if (!Array.isArray(value)) continue;
    return value.filter((candidate): candidate is string => typeof candidate === 'string');
  }
  return null;
}

function fieldNumber(item: AgentTimelineItem, ...keys: string[]): number | null {
  const root = item as unknown as Record<string, unknown>;
  const payload = recordValue(root.payload);
  for (const key of keys) {
    const value = root[key] ?? payload?.[key];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return null;
}

function recordValue(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}
