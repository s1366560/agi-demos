import type { AgentTimelineItem } from '../../types';

export type SessionAgentStatus = 'running' | 'completed' | 'failed' | 'stopped';

export type SessionAgentNode = {
  key: string;
  agentId: string;
  name: string | null;
  parentAgentId: string | null;
  sessionId: string | null;
  status: SessionAgentStatus;
  taskSummary: string | null;
  result: string | null;
  stopReason: string | null;
  success: boolean | null;
  artifacts: string[];
  createdAtUs: number;
  lastUpdateAtUs: number;
  children: SessionAgentNode[];
};

export type SessionAgentCommunication = {
  id: string;
  type: 'sent' | 'received';
  fromAgentId: string | null;
  fromLabel: string;
  toAgentId: string | null;
  toLabel: string;
  preview: string;
  eventTimeUs: number;
};

export type SessionAgentTreeModel = {
  roots: SessionAgentNode[];
  communications: SessionAgentCommunication[];
  summary: {
    total: number;
    running: number;
    completed: number;
    failed: number;
    stopped: number;
    communications: number;
  };
};

type MutableSessionAgentNode = Omit<SessionAgentNode, 'children'> & {
  childKeys: string[];
};

const sessionAgentTreeEventTypes = new Set([
  'agent_spawned',
  'agent_completed',
  'agent_stopped',
  'agent_message_sent',
  'agent_message_received',
]);

export function isSessionAgentTreeEvent(value: unknown): boolean {
  const root = recordValue(value);
  const type = stringValue(root?.type ?? root?.event_type);
  return Boolean(type && sessionAgentTreeEventTypes.has(type));
}

export function buildSessionAgentTree(items: readonly AgentTimelineItem[]): SessionAgentTreeModel {
  const nodes = new Map<string, MutableSessionAgentNode>();
  const keyByAgentId = new Map<string, string>();
  const communications: SessionAgentCommunication[] = [];

  for (const item of items) {
    if (!isSessionAgentTreeEvent(item)) continue;
    const type = eventType(item);
    const eventTimeUs = timelineTimeUs(item);

    if (type === 'agent_spawned') {
      const agentId = fieldString(item, 'agent_id', 'agentId');
      if (!agentId) continue;
      const sessionId = fieldString(item, 'child_session_id', 'childSessionId');
      const key = sessionId ?? agentId;
      const existing = nodes.get(key);
      const next: MutableSessionAgentNode = {
        key,
        agentId,
        name: fieldString(item, 'agent_name', 'agentName') ?? existing?.name ?? null,
        parentAgentId:
          fieldString(item, 'parent_agent_id', 'parentAgentId') ??
          existing?.parentAgentId ??
          null,
        sessionId: sessionId ?? existing?.sessionId ?? null,
        status: existing && existing.status !== 'running' ? existing.status : 'running',
        taskSummary:
          fieldString(item, 'task_summary', 'taskSummary') ?? existing?.taskSummary ?? null,
        result: existing?.result ?? null,
        stopReason: existing?.stopReason ?? null,
        success: existing?.success ?? null,
        artifacts: existing?.artifacts ?? [],
        createdAtUs: existing ? Math.min(existing.createdAtUs, eventTimeUs) : eventTimeUs,
        lastUpdateAtUs: existing ? Math.max(existing.lastUpdateAtUs, eventTimeUs) : eventTimeUs,
        childKeys: existing?.childKeys ?? [],
      };
      nodes.set(key, next);
      keyByAgentId.set(agentId, key);
      continue;
    }

    if (type === 'agent_message_sent' || type === 'agent_message_received') {
      const communication = readCommunication(item, type, eventTimeUs);
      if (communication) communications.push(communication);
      continue;
    }

    const agentId = fieldString(item, 'agent_id', 'agentId');
    if (!agentId) continue;
    const sessionId = fieldString(item, 'session_id', 'sessionId');
    const key = (sessionId && nodes.has(sessionId) ? sessionId : null) ?? keyByAgentId.get(agentId);
    if (!key) continue;
    const existing = nodes.get(key);
    if (!existing) continue;

    if (type === 'agent_completed') {
      const success = fieldBoolean(item, 'success');
      nodes.set(key, {
        ...existing,
        status: success === false ? 'failed' : 'completed',
        result: fieldString(item, 'result') ?? existing.result,
        success,
        artifacts: fieldStringList(item, 'artifacts') ?? existing.artifacts,
        lastUpdateAtUs: Math.max(existing.lastUpdateAtUs, eventTimeUs),
      });
      continue;
    }

    nodes.set(key, {
      ...existing,
      status: 'stopped',
      stopReason: fieldString(item, 'reason') ?? existing.stopReason,
      lastUpdateAtUs: Math.max(existing.lastUpdateAtUs, eventTimeUs),
    });
  }

  const candidateParents = new Map<string, string>();
  for (const node of nodes.values()) {
    if (!node.parentAgentId) continue;
    const parentKey = keyByAgentId.get(node.parentAgentId) ??
      (nodes.has(node.parentAgentId) ? node.parentAgentId : null);
    if (parentKey && parentKey !== node.key) candidateParents.set(node.key, parentKey);
  }

  const parentKeys = new Map<string, string>();
  for (const [childKey, parentKey] of candidateParents) {
    if (!parentChainContains(candidateParents, parentKey, childKey)) {
      parentKeys.set(childKey, parentKey);
    }
  }
  for (const [childKey, parentKey] of parentKeys) {
    const parent = nodes.get(parentKey);
    if (!parent || parent.childKeys.includes(childKey)) continue;
    parent.childKeys = [...parent.childKeys, childKey];
  }

  const roots = [...nodes.values()]
    .filter((node) => !parentKeys.has(node.key))
    .sort(compareMutableNodes)
    .map((node) => freezeNode(node, nodes));
  const statuses = [...nodes.values()].map((node) => node.status);
  const countStatus = (status: SessionAgentStatus) =>
    statuses.reduce((count, candidate) => count + Number(candidate === status), 0);

  return {
    roots,
    communications: communications.sort(
      (left, right) => left.eventTimeUs - right.eventTimeUs || left.id.localeCompare(right.id),
    ),
    summary: {
      total: nodes.size,
      running: countStatus('running'),
      completed: countStatus('completed'),
      failed: countStatus('failed'),
      stopped: countStatus('stopped'),
      communications: communications.length,
    },
  };
}

function readCommunication(
  item: AgentTimelineItem,
  event: 'agent_message_sent' | 'agent_message_received',
  eventTimeUs: number,
): SessionAgentCommunication | null {
  const fromAgentId = fieldString(item, 'from_agent_id', 'fromAgentId');
  const toAgentId = fieldString(item, 'to_agent_id', 'toAgentId');
  const fromName = fieldString(item, 'from_agent_name', 'fromAgentName');
  const toName = fieldString(item, 'to_agent_name', 'toAgentName', 'agent_name', 'agentName');
  const preview = fieldString(item, 'message_preview', 'messagePreview');
  if ((!fromAgentId && !fromName) || (!toAgentId && !toName) || !preview) return null;
  return {
    id: item.id,
    type: event === 'agent_message_sent' ? 'sent' : 'received',
    fromAgentId,
    fromLabel: fromName ?? fromAgentId ?? '',
    toAgentId,
    toLabel: toName ?? toAgentId ?? '',
    preview,
    eventTimeUs,
  };
}

function freezeNode(
  node: MutableSessionAgentNode,
  nodes: ReadonlyMap<string, MutableSessionAgentNode>,
): SessionAgentNode {
  return {
    key: node.key,
    agentId: node.agentId,
    name: node.name,
    parentAgentId: node.parentAgentId,
    sessionId: node.sessionId,
    status: node.status,
    taskSummary: node.taskSummary,
    result: node.result,
    stopReason: node.stopReason,
    success: node.success,
    artifacts: [...node.artifacts],
    createdAtUs: node.createdAtUs,
    lastUpdateAtUs: node.lastUpdateAtUs,
    children: node.childKeys
      .flatMap((key) => {
        const child = nodes.get(key);
        return child ? [child] : [];
      })
      .sort(compareMutableNodes)
      .map((child) => freezeNode(child, nodes)),
  };
}

function parentChainContains(
  candidateParents: ReadonlyMap<string, string>,
  startKey: string,
  targetKey: string,
): boolean {
  const visited = new Set<string>();
  let current: string | undefined = startKey;
  while (current) {
    if (current === targetKey) return true;
    if (visited.has(current)) return true;
    visited.add(current);
    current = candidateParents.get(current);
  }
  return false;
}

function compareMutableNodes(
  left: MutableSessionAgentNode,
  right: MutableSessionAgentNode,
): number {
  return left.createdAtUs - right.createdAtUs || left.key.localeCompare(right.key);
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

function fieldBoolean(item: AgentTimelineItem, ...keys: string[]): boolean | null {
  const root = item as unknown as Record<string, unknown>;
  const payload = recordValue(root.payload);
  for (const key of keys) {
    const value = root[key] ?? payload?.[key];
    if (typeof value === 'boolean') return value;
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

function recordValue(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}
