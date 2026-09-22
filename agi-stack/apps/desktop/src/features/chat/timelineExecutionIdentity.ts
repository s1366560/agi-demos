import type { AgentTimelineItem } from '../../types';

function identityField(item: AgentTimelineItem, names: readonly string[]): string | null {
  const records = [item, item.payload, item.metadata].filter(
    (value): value is Record<string, unknown> =>
      typeof value === 'object' && value !== null && !Array.isArray(value),
  );
  const values = records
    .flatMap((record) => names.map((name) => record[name]))
    .filter((value) => value !== undefined && value !== null);
  if (values.some((value) => typeof value !== 'string' || value.length === 0)) return null;
  return new Set(values).size <= 1 ? ((values[0] as string | undefined) ?? '') : null;
}

const scopes = [
  ['conversation_id', 'conversationId'],
  ['run_id', 'runId'],
  ['round_id', 'roundId'],
  ['subagent_id', 'subagentId'],
] as const;

/** A scope is available only when the producer supplies an explicit run identity. */
export function timelineExecutionScope(item: AgentTimelineItem): string | null {
  const values = scopes.map((names) => identityField(item, names));
  if (values.some((value) => value === null) || !values[1]) return null;
  return JSON.stringify(values);
}

/** No names, timestamps, payload similarity, or message IDs establish tool identity. */
export function sameTimelineExecution(call: AgentTimelineItem, result: AgentTimelineItem): boolean {
  for (const names of scopes) {
    const left = identityField(call, names);
    const right = identityField(result, names);
    if (left === null || right === null || (left && right && left !== right)) return false;
  }
  const executionNames = ['execution_id', 'tool_execution_id'];
  const callNames = ['tool_call_id', 'call_id', 'toolCallId'];
  const leftExecution = identityField(call, executionNames);
  const rightExecution = identityField(result, executionNames);
  const leftCall = identityField(call, callNames);
  const rightCall = identityField(result, callNames);
  if ([leftExecution, rightExecution, leftCall, rightCall].some((value) => value === null))
    return false;
  if (leftCall && rightCall && leftCall !== rightCall) return false;
  if (leftExecution && rightExecution) return leftExecution === rightExecution;
  return Boolean(leftCall && leftCall === rightCall);
}

/** Ambiguous duplicate IDs are retained independently rather than guessing an owner. */
export function exactToolResults(
  items: readonly AgentTimelineItem[],
): Map<string, AgentTimelineItem> {
  const unique = [...new Map(items.map((item) => [item.id, item])).values()];
  const calls = unique.filter((item) => item.type === 'act');
  const results = unique.filter((item) => item.type === 'observe');
  const linked = new Map<string, AgentTimelineItem>();
  for (const call of calls) {
    const candidates = results.filter((result) => sameTimelineExecution(call, result));
    if (candidates.length !== 1) continue;
    const result = candidates[0];
    if (calls.filter((candidate) => sameTimelineExecution(candidate, result)).length !== 1)
      continue;
    linked.set(call.id, result);
  }
  return linked;
}
