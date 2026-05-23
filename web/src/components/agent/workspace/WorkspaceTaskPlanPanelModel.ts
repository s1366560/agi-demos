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
  order: number;
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

export function buildWorkspaceTaskPlanRows(
  tasks: WorkspaceTask[],
  snapshot: WorkspacePlanSnapshot | null,
  currentWorkspaceTaskId: string | null | undefined
): WorkspaceTaskPlanRow[] {
  const planNodes = (snapshot?.plan?.nodes ?? []).filter(
    (node) => node.kind === 'task' || node.kind === 'verify'
  );
  const nodeByWorkspaceTaskId = new Map<string, WorkspacePlanNode>();
  for (const node of planNodes) {
    if (node.workspace_task_id) {
      nodeByWorkspaceTaskId.set(node.workspace_task_id, node);
    }
  }

  const rows: WorkspaceTaskPlanRow[] = tasks.map((task, index) => {
    const node = nodeByWorkspaceTaskId.get(task.id);
    return {
      id: `task:${task.id}`,
      entityId: task.id,
      title: taskTitle(task, node),
      description: task.description || node?.description || task.blocker_reason,
      status: task.status,
      source: 'task',
      kind: node?.kind,
      updatedAt: task.updated_at ?? task.created_at,
      progressPercent: node?.progress?.percent,
      attemptId: task.current_attempt_id ?? node?.current_attempt_id,
      isCurrent: rowIsCurrent(currentWorkspaceTaskId, task.id, node?.id),
      order: node?.priority ?? taskPriorityOrder(task, index),
    };
  });

  const taskIds = new Set(tasks.map((task) => task.id));
  planNodes.forEach((node, index) => {
    if (node.workspace_task_id && taskIds.has(node.workspace_task_id)) return;
    rows.push({
      id: `plan:${node.id}`,
      entityId: node.id,
      title: node.title || node.id,
      description: node.description,
      status: statusFromPlanNode(node),
      source: 'plan',
      kind: node.kind,
      updatedAt: node.updated_at ?? node.completed_at ?? node.created_at,
      progressPercent: node.progress?.percent,
      attemptId: node.current_attempt_id,
      isCurrent: rowIsCurrent(currentWorkspaceTaskId, node.workspace_task_id, node.id),
      order: node.priority ?? tasks.length + index,
    });
  });

  return rows.sort((a, b) => {
    const statusDelta = WORKSPACE_STATUS_ORDER[a.status] - WORKSPACE_STATUS_ORDER[b.status];
    if (statusDelta !== 0) return statusDelta;
    return a.order - b.order || a.title.localeCompare(b.title);
  });
}
