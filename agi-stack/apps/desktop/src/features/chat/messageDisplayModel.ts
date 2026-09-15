import type { AgentTimelineItem } from '../../types';

export function validMessageDisplayContent(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0 &&
    new TextEncoder().encode(value).byteLength <= 65_536;
}

/** Only explicit presentation metadata changes display; execution text is never parsed. */
export function userMessageForDisplay(item: AgentTimelineItem): AgentTimelineItem {
  if (item.type !== 'user_message') return item;
  const payload = record(item.payload);
  const metadata = record(item.metadata) ?? record(payload?.metadata);
  const display = record(item)?.display_content ?? payload?.display_content ?? metadata?.display_content;
  if (!validMessageDisplayContent(display)) return item;
  return { ...item, content: display, payload: { ...payload, raw_content: payload?.raw_content ?? item.content } };
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}
