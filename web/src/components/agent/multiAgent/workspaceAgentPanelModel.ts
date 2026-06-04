import {
  getTaskAttemptConversationId,
  getTaskAttemptNumber,
  getTaskAttemptWorkerAgentId,
  getTaskAttemptWorkerBindingId,
} from '@/utils/workspaceTaskProjection';

import type { AgentNode } from '@/types/multiAgent';
import type { WorkspaceAgent, WorkspacePlanSnapshot, WorkspaceTask } from '@/types/workspace';


function now(): number {
  return Date.now();
}

function readText(value: unknown): string | null {
  return typeof value === 'string' && value.trim().length > 0 ? value : null;
}

function workspaceAgentName(agent: WorkspaceAgent): string {
  return agent.display_name ?? agent.label ?? agent.agent_id;
}

function workspaceAgentRole(agent: WorkspaceAgent): string | null {
  const configRole = readText(agent.config?.workspace_role);
  return configRole ?? agent.label ?? null;
}

function statusFromWorkspaceAgent(agent: WorkspaceAgent): AgentNode['status'] {
  if (!agent.is_active) {
    return 'stopped';
  }

  const status = agent.status?.toLowerCase();
  if (status === 'running' || status === 'active' || status === 'busy') {
    return 'running';
  }
  if (status === 'failed' || status === 'error') {
    return 'failed';
  }
  if (status === 'stopped' || status === 'disabled') {
    return 'stopped';
  }
  if (status === 'completed' || status === 'done') {
    return 'completed';
  }
  return 'pending';
}

function statusFromAttempt(status: string | undefined): AgentNode['status'] {
  switch (status) {
    case 'accepted':
    case 'completed':
    case 'done':
      return 'completed';
    case 'blocked':
    case 'failed':
    case 'rejected':
      return 'failed';
    case 'cancelled':
    case 'stopped':
      return 'stopped';
    case 'awaiting_leader_adjudication':
    case 'awaiting_pipeline':
    case 'awaiting_plan_verification':
    case 'launched':
    case 'running':
    case 'waiting_response':
      return 'running';
    default:
      return 'pending';
  }
}

function latestSupervisorEvent(snapshot: WorkspacePlanSnapshot | null): string | null {
  const event = snapshot?.events.find((item) => item.event_type.startsWith('supervisor_'));
  return event?.event_type ?? null;
}

function createSupervisorNode(
  workspaceId: string,
  conversationId: string | null | undefined,
  snapshot: WorkspacePlanSnapshot | null
): AgentNode {
  const supervisorConversationId =
    conversationId?.startsWith('workspace-contract:supervisor-decision:') === true
      ? conversationId
      : null;
  const eventType = latestSupervisorEvent(snapshot);
  return {
    agentId: `workspace-supervisor:${workspaceId}`,
    name: 'Workspace Supervisor',
    parentAgentId: null,
    sessionId: supervisorConversationId,
    status: supervisorConversationId ? 'running' : eventType ? 'completed' : 'pending',
    taskSummary: eventType ?? 'Coordinates workspace plan decisions and handoffs',
    result: null,
    success: null,
    artifacts: [],
    children: [],
    createdAt: now(),
    lastUpdateAt: now(),
  };
}

function findAgentForTask(task: WorkspaceTask, agents: WorkspaceAgent[]): WorkspaceAgent | null {
  const workerBindingId = getTaskAttemptWorkerBindingId(task);
  if (workerBindingId) {
    const byBinding = agents.find((agent) => agent.id === workerBindingId);
    if (byBinding) return byBinding;
  }

  const workerAgentId = getTaskAttemptWorkerAgentId(task) ?? task.assignee_agent_id;
  if (workerAgentId) {
    const byAgentId = agents.find((agent) => agent.agent_id === workerAgentId);
    if (byAgentId) return byAgentId;
  }

  return null;
}

function taskAttemptId(task: WorkspaceTask): string | null {
  return readText(task.current_attempt_id) ?? readText(task.metadata.current_attempt_id);
}

function taskAttemptStatus(task: WorkspaceTask): string | undefined {
  return (
    readText(task.last_attempt_status) ??
    readText(task.metadata.last_attempt_status) ??
    readText(task.status) ??
    undefined
  );
}

function addChild(parent: AgentNode, childKey: string): AgentNode {
  return parent.children.includes(childKey)
    ? parent
    : { ...parent, children: [...parent.children, childKey], lastUpdateAt: now() };
}

export function buildWorkspaceAgentNodes(params: {
  workspaceId: string | null | undefined;
  conversationId: string | null | undefined;
  agents: WorkspaceAgent[];
  tasks: WorkspaceTask[];
  snapshot: WorkspacePlanSnapshot | null;
}): Map<string, AgentNode> {
  const { workspaceId, conversationId, agents, tasks, snapshot } = params;
  const nodes = new Map<string, AgentNode>();
  if (!workspaceId) {
    return nodes;
  }

  const supervisorKey = `workspace-supervisor:${workspaceId}`;
  nodes.set(supervisorKey, createSupervisorNode(workspaceId, conversationId, snapshot));

  const agentKeyByBinding = new Map<string, string>();
  const agentKeyByAgentId = new Map<string, string>();
  for (const agent of agents) {
    const key = `workspace-agent:${agent.id}`;
    agentKeyByBinding.set(agent.id, key);
    agentKeyByAgentId.set(agent.agent_id, key);
    nodes.set(key, {
      agentId: agent.agent_id,
      name: workspaceAgentName(agent),
      parentAgentId: supervisorKey,
      sessionId: null,
      status: statusFromWorkspaceAgent(agent),
      taskSummary: workspaceAgentRole(agent),
      result: null,
      success: null,
      artifacts: [],
      children: [],
      createdAt: new Date(agent.created_at).getTime(),
      lastUpdateAt: agent.updated_at ? new Date(agent.updated_at).getTime() : now(),
    });
    const supervisor = nodes.get(supervisorKey);
    if (supervisor) {
      nodes.set(supervisorKey, addChild(supervisor, key));
    }
  }

  for (const task of tasks) {
    const attemptId = taskAttemptId(task);
    const conversation = getTaskAttemptConversationId(task);
    if (!attemptId && !conversation) {
      continue;
    }

    const agent = findAgentForTask(task, agents);
    const parentKey = agent
      ? (agentKeyByBinding.get(agent.id) ?? agentKeyByAgentId.get(agent.agent_id))
      : supervisorKey;
    if (!parentKey) {
      continue;
    }

    const attemptNumber = getTaskAttemptNumber(task);
    const key = `workspace-attempt:${attemptId ?? conversation ?? task.id}`;
    nodes.set(key, {
      agentId: task.current_attempt_worker_agent_id ?? task.assignee_agent_id ?? task.id,
      name: attemptNumber ? `Attempt #${String(attemptNumber)}` : 'Workspace attempt',
      parentAgentId: parentKey,
      sessionId: conversation ?? null,
      status: statusFromAttempt(taskAttemptStatus(task)),
      taskSummary: task.title,
      result: task.last_worker_report_summary ?? readText(task.metadata.last_worker_report_summary),
      success: task.status === 'done' ? true : task.status === 'blocked' ? false : null,
      artifacts: task.last_worker_report_artifacts ?? [],
      children: [],
      createdAt: new Date(task.created_at).getTime(),
      lastUpdateAt: task.updated_at ? new Date(task.updated_at).getTime() : now(),
    });

    const parent = nodes.get(parentKey);
    if (parent) {
      nodes.set(parentKey, addChild(parent, key));
    }
  }

  return nodes;
}
