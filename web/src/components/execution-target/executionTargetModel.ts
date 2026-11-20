export type ExecutionTarget = 'local' | 'cloud';
export type ExecutionTargetFilter = 'all' | ExecutionTarget;

export function executionTargetOf(value: unknown): ExecutionTarget {
  return value === 'local' ? 'local' : 'cloud';
}
