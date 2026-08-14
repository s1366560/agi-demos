import type { WorkspaceAutonomyAttention } from '../../types';

export type WorkspaceAutonomyAttentionResolveAttempt = Readonly<{
  scopeKey: string;
  actorId: string;
  attentionId: string;
  expectedRevision: number;
  idempotencyKey: string;
}>;

export function workspaceAutonomyAttentionResolveAttemptIdentity(
  scopeKey: string,
  actorId: string,
  attentionId: string,
): string {
  return JSON.stringify([
    requiredValue(scopeKey, 'attention scope'),
    requiredValue(actorId, 'attention actor'),
    requiredValue(attentionId, 'attention id'),
  ]);
}

export function currentWorkspaceAutonomyAttentionResolveAttempt(
  attempts: ReadonlyMap<string, WorkspaceAutonomyAttentionResolveAttempt>,
  scopeKey: string,
  actorId: string,
  attentionId: string,
): WorkspaceAutonomyAttentionResolveAttempt | null {
  return (
    attempts.get(
      workspaceAutonomyAttentionResolveAttemptIdentity(scopeKey, actorId, attentionId),
    ) ?? null
  );
}

export function resolveWorkspaceAutonomyAttentionAttempt(
  attempts: Map<string, WorkspaceAutonomyAttentionResolveAttempt>,
  candidate: WorkspaceAutonomyAttentionResolveAttempt,
): WorkspaceAutonomyAttentionResolveAttempt {
  const identity = workspaceAutonomyAttentionResolveAttemptIdentity(
    candidate.scopeKey,
    candidate.actorId,
    candidate.attentionId,
  );
  const current = attempts.get(identity);
  if (current) return current;
  if (!Number.isSafeInteger(candidate.expectedRevision) || candidate.expectedRevision < 0) {
    throw new Error('Workspace authority revision is unavailable');
  }
  const attempt = Object.freeze({
    scopeKey: candidate.scopeKey,
    actorId: candidate.actorId,
    attentionId: candidate.attentionId,
    expectedRevision: candidate.expectedRevision,
    idempotencyKey: requiredValue(candidate.idempotencyKey, 'attention idempotency key'),
  });
  attempts.set(identity, attempt);
  return attempt;
}

export function discardWorkspaceAutonomyAttentionResolveAttempt(
  attempts: Map<string, WorkspaceAutonomyAttentionResolveAttempt>,
  scopeKey: string,
  actorId: string,
  attentionId: string,
): void {
  attempts.delete(
    workspaceAutonomyAttentionResolveAttemptIdentity(scopeKey, actorId, attentionId),
  );
}

export function retainOpenWorkspaceAutonomyAttentionResolveAttempts(
  attempts: Map<string, WorkspaceAutonomyAttentionResolveAttempt>,
  scopeKey: string,
  actorId: string,
  attentions: readonly WorkspaceAutonomyAttention[],
): void {
  const openAttentionIds = new Set(attentions.map((attention) => attention.attention_id));
  for (const [identity, attempt] of attempts) {
    if (
      attempt.scopeKey === scopeKey &&
      attempt.actorId === actorId &&
      !openAttentionIds.has(attempt.attentionId)
    ) {
      attempts.delete(identity);
    }
  }
}

function requiredValue(value: string, label: string): string {
  const trimmed = value.trim();
  if (!trimmed) throw new Error(`Missing ${label}`);
  return trimmed;
}
