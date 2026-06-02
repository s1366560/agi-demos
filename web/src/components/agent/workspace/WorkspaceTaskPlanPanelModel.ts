import type {
  WorkspacePlanNode,
  WorkspacePlanSnapshot,
  WorkspaceTask,
  WorkspaceTaskStatus,
} from '@/types/workspace';

export type WorkspaceTaskPanelView = 'flat' | 'lanes';
type WorkspacePanelRowSource = 'task' | 'plan';

export interface WorkspaceTaskPlanRow {
  id: string;
  entityId: string;
  title: string;
  description?: string | undefined;
  status: WorkspaceTaskStatus;
  source: WorkspacePanelRowSource;
  kind?: WorkspacePlanNode['kind'] | undefined;
  updatedAt?: string | null | undefined;
  progressPercent?: number | undefined;
  attemptId?: string | null | undefined;
  isCurrent: boolean;
  iterationIndex: number | null;
  order: number;
}

export interface WorkspaceTaskPlanIterationGroup {
  id: string;
  iterationIndex: number | null;
  rows: WorkspaceTaskPlanRow[];
}

const WORKSPACE_STATUS_ORDER: Record<WorkspaceTaskStatus, number> = {
  in_progress: 0,
  todo: 1,
  blocked: 2,
  done: 3,
};

export function statusFromPlanNode(node: WorkspacePlanNode): WorkspaceTaskStatus {
  if (node.intent === 'done') return 'done';
  if (node.intent === 'blocked') return 'blocked';
  if (
    node.intent === 'in_progress' ||
    node.execution === 'dispatched' ||
    node.execution === 'running' ||
    node.execution === 'reported' ||
    node.execution === 'verifying'
  ) {
    return 'in_progress';
  }
  return 'todo';
}

function taskTitle(task: WorkspaceTask, fallbackNode?: WorkspacePlanNode): string {
  return task.title.trim() || fallbackNode?.title || task.id;
}

function taskPriorityOrder(task: WorkspaceTask, fallback: number): number {
  switch (task.priority) {
    case 'P1':
      return 1;
    case 'P2':
      return 2;
    case 'P3':
      return 3;
    case 'P4':
      return 4;
    default:
      return fallback;
  }
}

function rowIsCurrent(
  currentWorkspaceTaskId: string | null | undefined,
  taskId: string | null | undefined,
  nodeId?: string | null
): boolean {
  return Boolean(
    currentWorkspaceTaskId &&
    (currentWorkspaceTaskId === taskId || (nodeId && currentWorkspaceTaskId === nodeId))
  );
}

function planNodeProgressPercent(node: WorkspacePlanNode): number | undefined {
  return (node as { progress?: { percent?: number } }).progress?.percent;
}

function planNodeOrder(node: WorkspacePlanNode, fallback: number): number {
  return (node as { priority?: number }).priority ?? fallback;
}

function planNodeIterationIndex(node: WorkspacePlanNode): number | null {
  const value = node.metadata.iteration_index;
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    return Math.floor(value);
  }
  if (typeof value === 'string' && /^\d+$/.test(value)) {
    return Math.max(1, Number(value));
  }
  return null;
}

function taskIterationIndex(task: WorkspaceTask): number | null {
  const value = task.metadata.iteration_index;
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    return Math.floor(value);
  }
  if (typeof value === 'string' && /^\d+$/.test(value)) {
    return Math.max(1, Number(value));
  }
  return null;
}

export function buildWorkspaceTaskPlanRows(
  tasks: WorkspaceTask[],
  snapshot: WorkspacePlanSnapshot | null,
  currentWorkspaceTaskId: string | null | undefined
): WorkspaceTaskPlanRow[] {
  const planNodes = (snapshot?.plan?.nodes ?? []).filter(
    (node) => node.kind === 'task' || node.kind === 'verify'
  );

  if (snapshot?.plan) {
    const taskById = new Map(tasks.map((task) => [task.id, task]));
    return planNodes
      .map((node, index) => {
        const task = node.workspace_task_id ? taskById.get(node.workspace_task_id) : undefined;
        return {
          id: `plan:${node.id}`,
          entityId: node.id,
          title: node.title || task?.title || node.id,
          description: node.description || task?.description || task?.blocker_reason,
          status: statusFromPlanNode(node),
          source: 'plan' as const,
          kind: node.kind,
          updatedAt: node.updated_at ?? node.completed_at ?? task?.updated_at ?? task?.created_at,
          progressPercent: planNodeProgressPercent(node),
          attemptId: node.current_attempt_id ?? task?.current_attempt_id,
          isCurrent: rowIsCurrent(currentWorkspaceTaskId, node.workspace_task_id, node.id),
          iterationIndex: planNodeIterationIndex(node),
          order: planNodeOrder(node, index),
        };
      })
      .sort(sortWorkspaceTaskPlanRows);
  }

  return tasks
    .map((task, index) => ({
      id: `task:${task.id}`,
      entityId: task.id,
      title: taskTitle(task),
      description: task.description || task.blocker_reason,
      status: task.status,
      source: 'task' as const,
      updatedAt: task.updated_at ?? task.created_at,
      attemptId: task.current_attempt_id,
      isCurrent: rowIsCurrent(currentWorkspaceTaskId, task.id),
      iterationIndex: taskIterationIndex(task),
      order: taskPriorityOrder(task, index),
    }))
    .sort(sortWorkspaceTaskPlanRows);
}

export function buildWorkspaceTaskPlanIterationGroups(
  rows: WorkspaceTaskPlanRow[]
): WorkspaceTaskPlanIterationGroup[] {
  const groups = new Map<number | null, WorkspaceTaskPlanRow[]>();

  for (const row of rows) {
    const currentRows = groups.get(row.iterationIndex) ?? [];
    currentRows.push(row);
    groups.set(row.iterationIndex, currentRows);
  }

  return [...groups.entries()]
    .sort(([left], [right]) => {
      if (left === right) return 0;
      if (left === null) return 1;
      if (right === null) return -1;
      return left - right;
    })
    .map(([iterationIndex, groupRows]) => ({
      id: iterationIndex === null ? 'iteration:unassigned' : `iteration:${String(iterationIndex)}`,
      iterationIndex,
      rows: groupRows,
    }));
}

function sortWorkspaceTaskPlanRows(a: WorkspaceTaskPlanRow, b: WorkspaceTaskPlanRow): number {
  const iterationDelta =
    (a.iterationIndex ?? Number.MAX_SAFE_INTEGER) - (b.iterationIndex ?? Number.MAX_SAFE_INTEGER);
  if (iterationDelta !== 0) return iterationDelta;
  const statusDelta = WORKSPACE_STATUS_ORDER[a.status] - WORKSPACE_STATUS_ORDER[b.status];
  if (statusDelta !== 0) return statusDelta;
  return a.order - b.order || a.title.localeCompare(b.title);
}
