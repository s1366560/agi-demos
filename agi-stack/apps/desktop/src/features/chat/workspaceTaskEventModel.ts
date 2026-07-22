import type { WorkspaceTask } from '../../types';

export type WorkspaceTaskStreamResult = {
  handled: boolean;
  tasks: WorkspaceTask[];
};

const workspaceTaskEventTypes = new Set([
  'workspace_task_created',
  'workspace_task_updated',
  'workspace_task_deleted',
  'workspace_task_status_changed',
  'workspace_task_assigned',
]);

export function applyWorkspaceTaskStreamEvent(
  existing: WorkspaceTask[],
  event: unknown,
  workspaceId: string,
): WorkspaceTaskStreamResult {
  const root = recordValue(event);
  const type = stringValue(root?.type ?? root?.event_type);
  if (!root || !type || !workspaceTaskEventTypes.has(type)) {
    return { handled: false, tasks: existing };
  }
  const data = recordValue(root.data) ?? recordValue(root.payload);
  const eventWorkspaceId = stringValue(data?.workspace_id ?? data?.workspaceId);
  const taskId = stringValue(data?.task_id ?? data?.taskId);
  if (!data || !workspaceId || eventWorkspaceId !== workspaceId || !taskId) {
    return { handled: false, tasks: existing };
  }
  const index = existing.findIndex((task) => task.id === taskId);
  if (type === 'workspace_task_deleted') {
    return {
      handled: true,
      tasks: index < 0 ? existing : existing.filter((task) => task.id !== taskId),
    };
  }

  let task: WorkspaceTask | null = null;
  if (type === 'workspace_task_created') {
    task = createdTask(data, workspaceId, taskId);
  } else if (type === 'workspace_task_updated') {
    task = index < 0 ? null : updatedTask(existing[index], data.changes, workspaceId, taskId);
  } else if (type === 'workspace_task_status_changed') {
    const status = stringValue(data.new_status ?? data.newStatus);
    task = index < 0 || !status ? null : { ...existing[index], status };
  } else if (type === 'workspace_task_assigned') {
    task = assignedTask(index < 0 ? null : existing[index], data, workspaceId, taskId);
  }
  if (!task) return { handled: false, tasks: existing };
  return {
    handled: true,
    tasks: index < 0
      ? [...existing, task]
      : existing.map((candidate, candidateIndex) => candidateIndex === index ? task! : candidate),
  };
}

function createdTask(
  data: Record<string, unknown>,
  workspaceId: string,
  taskId: string,
): WorkspaceTask | null {
  const title = optionalString(data.title);
  const metadata = optionalRecord(data.metadata);
  if (title.invalid || metadata.invalid) return null;
  return {
    id: taskId,
    workspace_id: workspaceId,
    ...(title.value !== undefined ? { title: title.value } : {}),
    ...(metadata.value !== undefined ? { metadata: metadata.value } : {}),
  };
}

function updatedTask(
  existing: WorkspaceTask,
  value: unknown,
  workspaceId: string,
  taskId: string,
): WorkspaceTask | null {
  const changes = recordValue(value);
  if (!changes) return null;
  if ('id' in changes && changes.id !== taskId) return null;
  if ('workspace_id' in changes && changes.workspace_id !== workspaceId) return null;
  return { ...existing, ...changes, id: taskId, workspace_id: workspaceId } as WorkspaceTask;
}

function assignedTask(
  existing: WorkspaceTask | null,
  data: Record<string, unknown>,
  workspaceId: string,
  taskId: string,
): WorkspaceTask | null {
  const supplied = recordValue(data.task);
  if (supplied) {
    if (stringValue(supplied.id) !== taskId || stringValue(supplied.workspace_id) !== workspaceId) {
      return null;
    }
    return { ...supplied, id: taskId, workspace_id: workspaceId } as WorkspaceTask;
  }
  if (!existing) return null;
  const workspaceAgentId = optionalString(data.workspace_agent_id);
  const status = optionalString(data.status);
  if (workspaceAgentId.invalid || status.invalid) return null;
  return {
    ...existing,
    ...(workspaceAgentId.value !== undefined
      ? { workspace_agent_id: workspaceAgentId.value }
      : {}),
    ...(status.value !== undefined ? { status: status.value } : {}),
  } as WorkspaceTask;
}

function optionalString(value: unknown): { invalid: boolean; value?: string } {
  if (value === undefined || value === null) return { invalid: false };
  return typeof value === 'string' ? { invalid: false, value } : { invalid: true };
}

function optionalRecord(
  value: unknown,
): { invalid: boolean; value?: Record<string, unknown> } {
  if (value === undefined || value === null) return { invalid: false };
  const record = recordValue(value);
  return record ? { invalid: false, value: record } : { invalid: true };
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}
