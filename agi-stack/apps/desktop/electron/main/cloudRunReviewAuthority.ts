export type CloudRunReviewTarget = Readonly<{
  runId: string;
  action: 'summary' | 'changes';
  scope: string | null;
  turnId: string | null;
  expectedRevision: number;
}>;

type ObservedProject = Readonly<{ tenantId: string; projectId: string | null }>;
type SummaryIdentity = Readonly<{ conversationId: string }>;

export function cloudRunReviewTarget(path: string): CloudRunReviewTarget | null {
  const target = new URL(path, 'https://desktop.invalid');
  const segments = target.pathname.split('/');
  if (
    segments.length !== 7 ||
    segments[1] !== 'api' ||
    segments[2] !== 'v1' ||
    segments[3] !== 'agent' ||
    segments[4] !== 'runs' ||
    (segments[6] !== 'summary' && segments[6] !== 'changes')
  )
    return null;
  return Object.freeze({
    runId: decodeURIComponent(segments[5]!),
    action: segments[6],
    scope: target.searchParams.get('scope'),
    turnId: target.searchParams.get('turn_id'),
    expectedRevision: Number(target.searchParams.get('expected_revision')),
  });
}

export function requireCloudRunSummaryScope(
  value: unknown,
  runId: string,
  context: ObservedProject,
): SummaryIdentity {
  if (
    !record(value) ||
    value.run_id !== runId ||
    value.tenant_id !== context.tenantId ||
    value.project_id !== context.projectId ||
    !context.projectId ||
    typeof value.conversation_id !== 'string' ||
    !value.conversation_id ||
    value.conversation_id !== value.conversation_id.trim()
  ) {
    throw new Error('cloud run summary scope mismatch');
  }
  return Object.freeze({ conversationId: value.conversation_id });
}

export function requireCloudRunChangesScope(
  value: unknown,
  target: CloudRunReviewTarget,
  identity: SummaryIdentity,
): void {
  if (
    !record(value) ||
    value.run_id !== target.runId ||
    value.conversation_id !== identity.conversationId ||
    value.scope !== target.scope ||
    value.run_revision !== target.expectedRevision ||
    value.turn_id !== target.turnId
  ) {
    throw new Error('cloud run changes scope mismatch');
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
