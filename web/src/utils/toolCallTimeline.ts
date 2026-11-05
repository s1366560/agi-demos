import type { ActEvent, TimelineEvent } from '../types/agent';

const isDraft = (event: ActEvent): boolean => event.metadata?.sourceEventType === 'act_delta';

/** Map persisted execution protocol states to their transcript presentation. */
export function getPersistedToolStatus(
  status: string | undefined
): 'success' | 'error' | 'cancelled' | undefined {
  switch (status) {
    case 'success':
    case 'completed':
      return 'success';
    case 'failed':
    case 'permission_denied':
    case 'timeout':
      return 'error';
    case 'cancelled':
      return 'cancelled';
    default:
      return undefined;
  }
}

/** Replayed argument drafts and actual executions share a model call ID, not an execution ID. */
export function coalesceToolCallDrafts(timeline: TimelineEvent[]): TimelineEvent[] {
  let turn = 0;
  const callKeys = new Map<ActEvent, string>();
  const executions = new Map<string, Set<string | undefined>>();
  const latestDrafts = new Map<string, ActEvent>();

  for (const event of timeline) {
    if (event.type === 'user_message') turn += 1;
    if (event.type !== 'act' || !event.call_id) continue;

    const scope = event.message_id ? ['message', event.message_id] : ['turn', turn];
    const key = JSON.stringify([...scope, event.call_id]);
    callKeys.set(event, key);
    if (isDraft(event)) {
      // Older projections used call_id as the draft's execution_id fallback.
      const explicitExecution =
        event.execution_id === event.call_id ? undefined : event.execution_id;
      latestDrafts.set(JSON.stringify([key, explicitExecution]), event);
    } else {
      const ids = executions.get(key) ?? new Set<string | undefined>();
      ids.add(event.execution_id);
      executions.set(key, ids);
    }
  }

  return timeline.filter((event) => {
    if (event.type !== 'act' || !isDraft(event)) return true;
    const key = callKeys.get(event);
    if (!key) return true;
    const explicitExecution = event.execution_id === event.call_id ? undefined : event.execution_id;
    const matchingExecutions = executions.get(key);
    if (
      matchingExecutions &&
      (explicitExecution === undefined || matchingExecutions.has(explicitExecution))
    ) {
      return false;
    }
    return latestDrafts.get(JSON.stringify([key, explicitExecution])) === event;
  });
}
