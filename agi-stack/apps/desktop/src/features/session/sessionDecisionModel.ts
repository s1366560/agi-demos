import type {
  DesktopApprovalRequest,
  HitlResponseSubmission,
} from '../../types';

export type ApprovalValidation = {
  complete: boolean;
  missing: string[];
  canApprove: boolean;
};

export type ApprovalResponseAction = 'approve' | 'request_changes';

function hasText(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

export function validateApprovalRequest(request: DesktopApprovalRequest): ApprovalValidation {
  if (!request.decision && request.kind === 'permission' && request.permission) {
    const permission = request.permission;
    const missing: string[] = [];
    if (!hasText(permission.tool_name)) missing.push('tool');
    if (!hasText(permission.action)) missing.push('action');
    if (!hasText(permission.description)) missing.push('description');
    if (!['low', 'medium', 'high'].includes(permission.risk_level)) missing.push('risk');
    return {
      complete: missing.length === 0,
      missing,
      canApprove: missing.length === 0 && request.status === 'pending',
    };
  }
  const decision = request.decision;
  const missing: string[] = [];
  if (!decision || !hasText(decision.action?.name) || !hasText(decision.action?.label)) {
    missing.push('action');
  }
  if (!decision || !hasText(decision.target?.kind) || !hasText(decision.target?.id)) {
    missing.push('target');
  }
  if (!decision || !hasText(decision.data?.summary)) missing.push('data');
  if (!decision || !hasText(decision.reason)) missing.push('reason');
  if (
    !decision ||
    !['low', 'medium', 'high'].includes(decision.risk?.level) ||
    !hasText(decision.risk?.rationale)
  ) {
    missing.push('risk');
  }
  if (
    !decision ||
    !['reversible', 'partial', 'irreversible'].includes(decision.reversibility?.mode)
  ) {
    missing.push('reversibility');
  }
  if (
    !decision ||
    !hasText(decision.scope?.kind) ||
    !Array.isArray(decision.scope?.ids) ||
    decision.scope.ids.length === 0 ||
    !decision.scope.ids.every(hasText)
  ) {
    missing.push('scope');
  }
  if (
    !decision ||
    !Array.isArray(decision.evidence) ||
    decision.evidence.length === 0 ||
    !decision.evidence.every(
      (item) => hasText(item.kind) && hasText(item.id) && hasText(item.label),
    )
  ) {
    missing.push('evidence');
  }
  return {
    complete: missing.length === 0,
    missing,
    canApprove: missing.length === 0 && request.status === 'pending',
  };
}

export function latestPendingApproval(
  requests: DesktopApprovalRequest[],
  runId?: string | null,
): DesktopApprovalRequest | null {
  return (
    requests
      .filter(
        (request) =>
          request.status === 'pending' &&
          Boolean(request.decision || request.permission) &&
          (!runId || request.run_id === runId),
      )
      .sort((left, right) => {
        const time = Date.parse(right.created_at) - Date.parse(left.created_at);
        return Number.isFinite(time) && time !== 0 ? time : right.id.localeCompare(left.id);
      })[0] ?? null
  );
}

export function approvalResponseSubmission(
  request: DesktopApprovalRequest,
  action: ApprovalResponseAction,
  feedback?: string,
): HitlResponseSubmission {
  const normalizedFeedback = feedback?.trim();
  const responseData =
    request.kind === 'permission'
      ? {
          granted: action === 'approve',
          ...(normalizedFeedback ? { feedback: normalizedFeedback } : {}),
        }
      : {
          decision: action === 'approve' ? 'approved' : 'changes_requested',
          ...(normalizedFeedback ? { feedback: normalizedFeedback } : {}),
        };
  const revision =
    typeof request.run_revision === 'number' && Number.isFinite(request.run_revision)
      ? request.run_revision
      : undefined;
  return {
    requestId: request.id,
    hitlType: request.kind,
    ...(revision === undefined ? {} : { expectedRevision: revision }),
    idempotencyKey: [request.id, revision ?? 'unversioned', action].join(':'),
    responseData,
  };
}
