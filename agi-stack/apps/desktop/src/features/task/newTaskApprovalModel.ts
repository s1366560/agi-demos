import type {
  AgentPlanApprovalCapability,
  AgentPlanTaskListResponse,
  DesktopPermissionProfile,
  DesktopPlanVersion,
} from '../../types';
import {
  orderedPlanTasks,
  planTaskSignature,
  type NewTaskKind,
} from './newTaskPlanModel';

export function planVersionIdentity(planVersion: DesktopPlanVersion | null | undefined): string {
  return planVersion ? `${planVersion.id}:${planVersion.version}` : '';
}

export function hasPlanVersionChanged(
  current: DesktopPlanVersion | null | undefined,
  next: DesktopPlanVersion | null | undefined,
): boolean {
  const nextIdentity = planVersionIdentity(next);
  return Boolean(nextIdentity) && nextIdentity !== planVersionIdentity(current);
}

export function canApprovePlanVersion(
  planVersion: DesktopPlanVersion | null | undefined,
  requiresReview: boolean,
): boolean {
  return Boolean(
    planVersion?.id &&
      planVersion.version > 0 &&
      planVersion.status === 'draft' &&
      !requiresReview,
  );
}

export function approvalCapability(
  response: AgentPlanTaskListResponse,
): AgentPlanApprovalCapability | null {
  if (response.approval) return response.approval;
  if (response.plan_version) {
    return { kind: 'versioned_atomic', plan_version: response.plan_version };
  }
  return null;
}

export function approvalPlanVersion(
  response: AgentPlanTaskListResponse,
): DesktopPlanVersion | null {
  const capability = approvalCapability(response);
  return capability?.kind === 'versioned_atomic'
    ? capability.plan_version
    : response.plan_version ?? null;
}

export function legacyPlanMatchesPreview(
  response: AgentPlanTaskListResponse,
  reviewedSignature: string,
): boolean {
  return (
    approvalCapability(response)?.kind === 'legacy_mode_switch' &&
    planTaskSignature(orderedPlanTasks(response.tasks ?? [])) === reviewedSignature
  );
}

export function canApprovePlan(
  capability: AgentPlanApprovalCapability | null | undefined,
  planVersion: DesktopPlanVersion | null | undefined,
  requiresReview: boolean,
  taskCount: number,
): boolean {
  if (!capability || taskCount < 1 || requiresReview) return false;
  if (capability.kind === 'legacy_mode_switch') return true;
  return canApprovePlanVersion(planVersion, false);
}

export function isPlanApprovalBlocked(
  planRequiresReview: boolean,
  revisionAwaitingPlan: boolean,
): boolean {
  return planRequiresReview || revisionAwaitingPlan;
}

export function defaultPermissionProfile(kind: NewTaskKind): DesktopPermissionProfile {
  return kind === 'programming' ? 'workspace_write' : 'read_only';
}
