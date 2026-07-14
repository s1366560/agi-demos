import type {
  ChangeFile,
  ChangeLine,
  ChangeSnapshot,
  CodeRangeReference,
  DesktopRunStatus,
  RunInputDelivery,
} from '../../types';

export function allowedRunInputDeliveries(
  status: DesktopRunStatus | null | undefined,
  attached: boolean,
): RunInputDelivery[] {
  if (status !== 'running') return [];
  return attached ? ['steer_now', 'queue_next'] : ['queue_next'];
}

export function effectiveRunInputDelivery(
  selected: RunInputDelivery | null,
  allowed: readonly RunInputDelivery[],
): RunInputDelivery | null {
  return selected && allowed.includes(selected) ? selected : (allowed[0] ?? null);
}

export function referenceForChangeLine(
  snapshot: ChangeSnapshot,
  file: ChangeFile,
  line: ChangeLine,
): CodeRangeReference | null {
  if (snapshot.status !== 'ready' || !snapshot.environment_id) return null;
  const side = line.kind === 'deletion' ? 'old' : 'new';
  const lineNumber = side === 'old' ? line.old_line : line.new_line;
  if (!lineNumber || lineNumber < 1) return null;
  return {
    type: 'code_range',
    snapshot_id: snapshot.id,
    environment_id: snapshot.environment_id,
    path: file.path,
    start_line: lineNumber,
    end_line: lineNumber,
    side,
    patch_digest: file.patch_digest,
  };
}

export function toggleRunInputReference(
  references: CodeRangeReference[],
  reference: CodeRangeReference,
): CodeRangeReference[] {
  const key = runInputReferenceKey(reference);
  const exists = references.some((candidate) => runInputReferenceKey(candidate) === key);
  return exists
    ? references.filter((candidate) => runInputReferenceKey(candidate) !== key)
    : [...references, reference];
}

export function runInputReferenceKey(reference: CodeRangeReference): string {
  return [
    reference.snapshot_id,
    reference.environment_id,
    reference.path,
    reference.side,
    reference.start_line,
    reference.end_line,
    reference.patch_digest,
  ].join(':');
}

export function runInputReferenceLabel(reference: CodeRangeReference): string {
  const range =
    reference.start_line === reference.end_line
      ? `${reference.start_line}`
      : `${reference.start_line}-${reference.end_line}`;
  return `${reference.path}#${reference.side === 'old' ? 'L-' : 'L'}${range}`;
}

export function snapshotMatchesRun(
  snapshot: ChangeSnapshot | null,
  runId: string | null | undefined,
  runRevision: number | null | undefined,
): boolean {
  return Boolean(
    snapshot &&
      runId &&
      snapshot.run_id === runId &&
      typeof runRevision === 'number' &&
      snapshot.run_revision === runRevision,
  );
}
