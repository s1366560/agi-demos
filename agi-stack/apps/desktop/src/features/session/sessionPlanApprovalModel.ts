import type {
  AgentPlanTask,
  ApprovePlanAndStartRequest,
  DesktopExecutionEnvironmentKind,
  DesktopPermissionProfile,
} from '../../types';
import { buildExecutionPrompt } from '../task/newTaskPlanModel';
import type {
  SessionProjectionCapabilities,
  SessionProjectionPlan,
  SessionProjectionTask,
} from './sessionProjectionTypes';
import type { SessionCapabilityMode } from './sessionViewModel';

export type SessionPlanApprovalSelection = {
  environmentKind: DesktopExecutionEnvironmentKind;
  permissionProfile: DesktopPermissionProfile;
};

export type SessionPlanApprovalIdentityInput = SessionPlanApprovalSelection & {
  conversationId: string;
  plan: SessionProjectionPlan;
};

export type SessionPlanApprovalRequestInput = SessionPlanApprovalIdentityInput & {
  projectId: string;
  requestId: string;
};

export function normalizeSessionTaskListPlan(
  tasks: SessionProjectionTask[],
  conversationId: string,
): AgentPlanTask[] | null {
  if (!tasks.length || !conversationId.trim()) return null;
  const normalized: AgentPlanTask[] = [];
  for (const task of tasks) {
    const id = typeof task.id === 'string' ? task.id.trim() : '';
    const scopedConversationId =
      typeof task.conversation_id === 'string' ? task.conversation_id.trim() : '';
    const content = typeof task.content === 'string' ? task.content.trim() : '';
    const status = typeof task.status === 'string' ? task.status.trim() : '';
    const priority = typeof task.priority === 'string' ? task.priority.trim() : '';
    const orderIndex = task.order_index;
    const createdAt = typeof task.created_at === 'string' ? task.created_at.trim() : '';
    const updatedAt =
      typeof task.updated_at === 'string' ? task.updated_at.trim() : '';
    if (
      !id ||
      scopedConversationId !== conversationId ||
      !content ||
      !status ||
      !priority ||
      typeof orderIndex !== 'number' ||
      !Number.isInteger(orderIndex) ||
      orderIndex < 0 ||
      !createdAt ||
      (task.updated_at !== null && typeof task.updated_at !== 'string')
    ) {
      return null;
    }
    normalized.push({
      id,
      conversation_id: scopedConversationId,
      content,
      status,
      priority,
      order_index: orderIndex,
      created_at: createdAt,
      updated_at: updatedAt,
    });
  }
  return normalized.sort((left, right) => left.order_index - right.order_index);
}

export function sessionPlanTaskStatusTranslationKey(status: string): string {
  if (
    status === 'pending' ||
    status === 'in_progress' ||
    status === 'completed' ||
    status === 'blocked' ||
    status === 'cancelled' ||
    status === 'failed'
  ) {
    return `session.planTaskState.${status}`;
  }
  return 'session.planTaskState.unknown';
}

export function sessionPlanTaskPriorityTranslationKey(priority: string): string {
  if (priority === 'high') return 'task.priorityHigh';
  if (priority === 'medium') return 'task.priorityMedium';
  if (priority === 'low') return 'task.priorityLow';
  return 'task.priorityUnknown';
}

export function canApproveSessionPlan(
  plan: SessionProjectionPlan | null,
  capabilities: SessionProjectionCapabilities | null,
): boolean {
  return Boolean(
    plan?.status === 'draft' &&
      plan.tasks.length > 0 &&
      capabilities?.canApprovePlan &&
      capabilities.allowedActions.includes('approve_plan_and_start'),
  );
}

export function defaultSessionPlanApprovalSelection(
  capabilityMode: SessionCapabilityMode,
): SessionPlanApprovalSelection {
  return capabilityMode === 'code'
    ? { environmentKind: 'worktree', permissionProfile: 'workspace_write' }
    : { environmentKind: 'local', permissionProfile: 'read_only' };
}

export function sessionPlanApprovalIdentity(input: SessionPlanApprovalIdentityInput): string {
  return [
    input.conversationId,
    input.plan.id,
    input.plan.version,
    input.environmentKind,
    input.permissionProfile,
  ].join(':');
}

export function sessionPlanApprovalRequest(
  input: SessionPlanApprovalRequestInput,
): ApprovePlanAndStartRequest {
  return {
    conversationId: input.conversationId,
    projectId: input.projectId,
    planVersionId: input.plan.id,
    expectedPlanVersion: input.plan.version,
    permissionProfile: input.permissionProfile,
    message: buildExecutionPrompt(),
    messageId: `desktop-build-${input.requestId}`,
    idempotencyKey: `desktop-plan-approval-${input.requestId}`,
    environmentKind: input.environmentKind,
  };
}
