import type { ExecutionSummary, ExecutionTaskSummary, ExecutionTokenSummary } from '@/types/agent';

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readNumber(record: UnknownRecord, camelKey: string, snakeKey: string): number {
  const value = record[camelKey] ?? record[snakeKey];
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function readString(record: UnknownRecord, camelKey: string, snakeKey: string): string {
  const value = record[camelKey] ?? record[snakeKey];
  return typeof value === 'string' ? value : '';
}

function normalizeTokens(value: unknown): ExecutionTokenSummary {
  const record = isRecord(value) ? value : {};
  return {
    input: readNumber(record, 'input', 'input'),
    output: readNumber(record, 'output', 'output'),
    reasoning: readNumber(record, 'reasoning', 'reasoning'),
    cacheRead: readNumber(record, 'cacheRead', 'cache_read'),
    cacheWrite: readNumber(record, 'cacheWrite', 'cache_write'),
    total: readNumber(record, 'total', 'total'),
  };
}

function normalizeTasks(value: unknown): ExecutionTaskSummary | undefined {
  if (!isRecord(value)) {
    return undefined;
  }
  return {
    total: readNumber(value, 'total', 'total'),
    completed: readNumber(value, 'completed', 'completed'),
    remaining: readNumber(value, 'remaining', 'remaining'),
    pending: readNumber(value, 'pending', 'pending'),
    inProgress: readNumber(value, 'inProgress', 'in_progress'),
    failed: readNumber(value, 'failed', 'failed'),
    cancelled: readNumber(value, 'cancelled', 'cancelled'),
    other: readNumber(value, 'other', 'other'),
  };
}

export function normalizeExecutionSummary(value: unknown): ExecutionSummary | null {
  if (!isRecord(value)) {
    return null;
  }

  return {
    stepCount: readNumber(value, 'stepCount', 'step_count'),
    artifactCount: readNumber(value, 'artifactCount', 'artifact_count'),
    callCount: readNumber(value, 'callCount', 'call_count'),
    totalCost: readNumber(value, 'totalCost', 'total_cost'),
    totalCostFormatted:
      readString(value, 'totalCostFormatted', 'total_cost_formatted') || '$0.000000',
    totalTokens: normalizeTokens(value.totalTokens ?? value.total_tokens),
    tasks: normalizeTasks(value.tasks),
  };
}
