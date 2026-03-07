/**
 * Timeline utility functions for HITL event handling and message conversion.
 *
 * Extracted from agentV3.ts to reduce file size and improve maintainability.
 * Contains pure functions with no store dependencies.
 */

import type { Message, TimelineEvent } from '../../types/agent';

/**
 * Update HITL event in timeline when user responds
 * Finds the matching event by requestId and updates its answered state
 *
 * @param timeline - Current timeline array
 * @param requestId - The HITL request ID to find
 * @param eventType - Type of HITL event to match
 * @param updates - Fields to update (answered, answer/decision/values)
 * @returns Updated timeline with the HITL event marked as answered
 */
export function updateHITLEventInTimeline(
  timeline: TimelineEvent[],
  requestId: string,
  eventType: 'clarification_asked' | 'decision_asked' | 'env_var_requested' | 'permission_asked',
  updates: {
    answered: boolean;
    answer?: string | undefined;
    decision?: string | undefined;
    values?: Record<string, string> | undefined;
    granted?: boolean | undefined;
  }
): TimelineEvent[] {
  return timeline.map((event) => {
    if (event.type === eventType && (event as any).requestId === requestId) {
      return { ...event, ...updates };
    }
    return event;
  });
}

/**
 * Merge HITL response events (_answered/_provided/_replied/_granted) into their
 * corresponding request events (_asked/_requested) so only one card renders.
 *
 * For each response event, find the matching request event by requestId,
 * mark it as answered with the response value, then remove the response event.
 */
export function mergeHITLResponseEvents(timeline: TimelineEvent[]): TimelineEvent[] {
  // Map from response type to { requestType, field to copy }
  const responseTypeMap: Record<
    string,
    {
      requestType: string;
      mapFn: (resp: any) => Record<string, unknown>;
    }
  > = {
    clarification_answered: {
      requestType: 'clarification_asked',
      mapFn: (r) => ({ answered: true, answer: r.answer }),
    },
    decision_answered: {
      requestType: 'decision_asked',
      mapFn: (r) => ({ answered: true, decision: r.decision }),
    },
    env_var_provided: {
      requestType: 'env_var_requested',
      mapFn: (r) => ({
        answered: true,
        providedVariables: r.variableNames,
        values: r.values,
      }),
    },
    permission_replied: {
      requestType: 'permission_asked',
      mapFn: (r) => ({ answered: true, granted: r.granted }),
    },
    permission_granted: {
      requestType: 'permission_asked',
      mapFn: (r) => ({
        answered: true,
        granted: r.granted !== undefined ? r.granted : true,
      }),
    },
  };

  // Collect response events keyed by requestId
  const responsesByRequestId = new Map<string, Record<string, unknown>>();
  const responseEventIds = new Set<string>();

  for (const event of timeline) {
    const mapping = responseTypeMap[event.type];
    if (mapping) {
      const requestId = (event as any).requestId;
      if (requestId) {
        responsesByRequestId.set(requestId, mapping.mapFn(event));
        responseEventIds.add(event.id);
      }
    }
  }

  if (responsesByRequestId.size === 0) return timeline;

  // Merge into request events and filter out response events
  return timeline
    .map((event) => {
      const requestId = (event as any).requestId;
      if (requestId && responsesByRequestId.has(requestId)) {
        const requestTypes = [
          'clarification_asked',
          'decision_asked',
          'env_var_requested',
          'permission_asked',
        ];
        if (requestTypes.includes(event.type)) {
          return {
            ...event,
            ...responsesByRequestId.get(requestId),
          };
        }
      }
      return event;
    })
    .filter((event) => !responseEventIds.has(event.id));
}

/**
 * Convert TimelineEvent[] to Message[] - Simple 1:1 conversion without merging
 * Each timeline event maps directly to a message for natural ordering
 */
export function timelineToMessages(timeline: TimelineEvent[]): Message[] {
  const messages: Message[] = [];

  for (const event of timeline) {
    switch (event.type) {
      case 'user_message':
        messages.push({
          id: event.id,
          conversation_id: '',
          role: 'user',
          content: (event as any).content || '',
          message_type: 'text' as const,
          created_at: new Date(event.timestamp).toISOString(),
        });
        break;

      case 'assistant_message':
        messages.push({
          id: event.id,
          conversation_id: '',
          role: 'assistant',
          content: (event as any).content || '',
          message_type: 'text' as const,
          created_at: new Date(event.timestamp).toISOString(),
        });
        break;

      case 'text_end':
        messages.push({
          id: event.id,
          conversation_id: '',
          role: 'assistant',
          content: (event as any).fullText || '',
          message_type: 'text' as const,
          created_at: new Date(event.timestamp).toISOString(),
        });
        break;

      // Other event types are rendered directly from timeline, not as messages
      default:
        break;
    }
  }

  return messages;
}
