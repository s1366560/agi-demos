import type { AgentTimelineItem } from '../../types';

const childToolTypes = new Set([
  'subagent_tool_call',
  'subagent_tool_result',
  'subagent_tool_error',
]);

export type SubagentToolActivity = {
  id: string;
  toolName: string;
  status: 'running' | 'success' | 'error';
  input?: string;
  output?: string;
  error?: string;
};

export function isSubagentToolEvent(item: AgentTimelineItem): boolean {
  return childToolTypes.has(item.type);
}

export function subagentToolActivity(items: readonly AgentTimelineItem[]): SubagentToolActivity[] {
  const calls = new Map<string, SubagentToolActivity>();
  for (const item of items) {
    if (!isSubagentToolEvent(item)) continue;
    const data = item.payload ?? item.data;
    if (!data || typeof data !== 'object' || Array.isArray(data)) continue;
    const value = data as Record<string, unknown>;
    const { execution_id, subagent_id, parent_run_id, parent_run_revision, round, tool_name } =
      value;
    if (
      typeof execution_id !== 'string' ||
      !execution_id ||
      value.run_id !== execution_id ||
      typeof subagent_id !== 'string' ||
      !subagent_id ||
      typeof parent_run_id !== 'string' ||
      !parent_run_id ||
      typeof parent_run_revision !== 'number' ||
      !Number.isInteger(parent_run_revision) ||
      typeof round !== 'number' ||
      !Number.isInteger(round) ||
      round < 0 ||
      typeof tool_name !== 'string' ||
      !tool_name
    )
      continue;
    const key = JSON.stringify([
      execution_id,
      subagent_id,
      parent_run_id,
      parent_run_revision,
      round,
      tool_name,
    ]);
    const previous = calls.get(key);
    calls.set(key, {
      id: previous?.id ?? item.id,
      toolName: tool_name,
      status:
        item.type === 'subagent_tool_call'
          ? (previous?.status ?? 'running')
          : item.type === 'subagent_tool_error' || value.failed === true
            ? 'error'
            : 'success',
      input: typeof value.tool_input === 'string' ? value.tool_input : previous?.input,
      output: typeof value.tool_output === 'string' ? value.tool_output : previous?.output,
      error: typeof value.error === 'string' ? value.error : previous?.error,
    });
  }
  return [...calls.values()];
}
