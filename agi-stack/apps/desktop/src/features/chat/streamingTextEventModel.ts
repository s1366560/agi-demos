import { protocolStreamMessageId } from './agentEventIdentityModel';

type StreamingTextDeltaParts = {
  messageId: string;
  delta: string;
  event: Record<string, unknown>;
  data: Record<string, unknown>;
};

function objectField(
  payload: Record<string, unknown>,
  key: string,
): Record<string, unknown> | null {
  const value = payload[key];
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readIdentifierField(
  payload: Record<string, unknown>,
  key: string,
): string | undefined {
  const value = payload[key];
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function readTextField(
  payload: Record<string, unknown>,
  key: string,
): string | undefined {
  const value = payload[key];
  return typeof value === 'string' ? value : undefined;
}

function streamingTextDeltaParts(event: unknown): StreamingTextDeltaParts | null {
  if (!event || typeof event !== 'object') return null;
  const payload = event as Record<string, unknown>;
  const type =
    readIdentifierField(payload, 'type') ??
    readIdentifierField(payload, 'event_type');
  if (type !== 'text_delta') return null;
  const data = objectField(payload, 'data') ?? objectField(payload, 'payload') ?? {};
  const delta =
    readTextField(data, 'delta') ??
    readTextField(data, 'text') ??
    readTextField(data, 'content') ??
    '';
  const messageId = protocolStreamMessageId(payload);
  return messageId ? { messageId, delta, event: payload, data } : null;
}

/**
 * Collapse consecutive deltas for one response while preserving every text
 * token verbatim. Whitespace-only deltas are content, not absent fields.
 */
export function coalesceStreamingTextEvents(events: unknown[]): unknown[] {
  const output: unknown[] = [];
  let runIndex = -1;
  let runMessageId: string | null = null;
  let runDelta = '';

  for (const event of events) {
    const parts = streamingTextDeltaParts(event);
    if (!parts) {
      runIndex = -1;
      runMessageId = null;
      runDelta = '';
      output.push(event);
      continue;
    }

    if (runIndex >= 0 && runMessageId === parts.messageId) {
      runDelta += parts.delta;
      output[runIndex] = {
        ...parts.event,
        data: { ...parts.data, delta: runDelta },
      };
      continue;
    }

    runIndex = output.length;
    runMessageId = parts.messageId;
    runDelta = parts.delta;
    output.push({
      ...parts.event,
      data: { ...parts.data, delta: runDelta },
    });
  }

  return output;
}
