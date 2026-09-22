import { timelineToolResultFailed } from '../chat/toolResultStatus';
import { exactToolResults } from '../chat/timelineExecutionIdentity';
import type { AgentTimelineItem } from '../../types';

export type TimelineStepDetails = {
  title: string | null;
  summary: string | null;
  status: string | null;
  input: unknown[];
  output: unknown[];
  diagnostics: Array<{ key: string; value: unknown }>;
  files: string[];
  events: readonly AgentTimelineItem[];
};

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

export function serializeRawTimelineDetail(value: unknown): string {
  return typeof value === 'string' ? value : (JSON.stringify(value, null, 2) ?? '');
}

// JSON decoding is presentation-only. Keep source events and raw copies unchanged.
export function serializeTimelineDetail(value: unknown): string {
  return serializeRawTimelineDetail(decodeTimelinePresentation(value, true));
}

function decodeTimelinePresentation(value: unknown, decodeString = false, depth = 0): unknown {
  if (depth >= 32) return value;
  if (typeof value === 'string') {
    if (!decodeString) return value;
    try {
      const decoded: unknown = JSON.parse(value);
      return decodeTimelinePresentation(decoded, true, depth + 1);
    } catch {
      return value;
    }
  }
  if (Array.isArray(value)) {
    return value.map((entry) => decodeTimelinePresentation(entry, false, depth + 1));
  }
  if (value === null || typeof value !== 'object') return value;
  return Object.fromEntries(
    Object.entries(value).map(([key, entry]) => {
      if (key === 'content' && Array.isArray(entry)) {
        return [
          key,
          entry.map((block) => {
            if (block === null || typeof block !== 'object' || Array.isArray(block)) return block;
            return Object.fromEntries(
              Object.entries(block).map(([field, content]) => [
                field,
                decodeTimelinePresentation(content, field === 'text', depth + 1),
              ]),
            );
          }),
        ];
      }
      return [key, decodeTimelinePresentation(entry, false, depth + 1)];
    }),
  );
}

function uniqueValues(values: unknown[]): unknown[] {
  const serialized = new Set<string>();
  return values.filter((value) => {
    if (value === undefined || value === null || value === '') return false;
    const key = serializeRawTimelineDetail(value);
    if (serialized.has(key)) return false;
    serialized.add(key);
    return true;
  });
}

// Read declared event fields only. Never infer tools, files or outcomes from prose.
export function buildTimelineStepDetails(items: readonly AgentTimelineItem[]): TimelineStepDetails {
  const events = [...new Map(items.map((item) => [item.id, item])).values()];
  const latest = events.at(-1);
  const input = uniqueValues(
    events.map((item) => {
      const payload = record(item.payload);
      return item.toolInput ?? payload.tool_input ?? payload.input ?? payload.arguments;
    }),
  );
  const output = uniqueValues(
    events.map((item) => {
      const payload = record(item.payload);
      return (
        item.toolOutput ??
        payload.tool_output ??
        payload.output ??
        payload.result ??
        (item.type === 'observe' || item.type === 'tool_result' ? item.payload : undefined)
      );
    }),
  );
  const files = new Set<string>();
  const diagnostics = new Map<string, unknown>();
  for (const item of events) {
    const toolOutput = record(item.toolOutput);
    const metadata = record(
      item.fileMetadata ?? toolOutput.fileMetadata ?? toolOutput.file_metadata,
    );
    for (const path of Array.isArray(metadata.paths) ? metadata.paths : []) {
      const value = text(record(path).path) ?? text(record(path).relativePath);
      if (value) files.add(value);
    }
    const payload = record(item.payload);
    for (const key of [
      'error',
      'reason',
      'duration_ms',
      'exit_code',
      'invocation_id',
      'trace_id',
    ]) {
      const value =
        item[key] ??
        payload[key] ??
        (key === 'error' && item.type === 'error' ? item.content : undefined);
      if (value !== undefined && value !== null && value !== '') diagnostics.set(key, value);
    }
  }
  const display = record(latest?.display ?? record(latest?.toolOutput).display);
  const summary = text(display.summary) ?? text(latest?.description) ?? text(latest?.error);
  const content = text(latest?.content);
  if (!output.length && content && content !== summary && latest?.type !== 'error')
    output.push(content);
  return {
    title: text(display.title) ?? text(latest?.toolName) ?? text(events[0]?.toolName),
    summary,
    status:
      latest && (timelineToolResultFailed(latest) || latest.type === 'error')
        ? 'failed'
        : (text(display.status) ?? text(latest?.status)),
    input,
    output,
    diagnostics: [...diagnostics].map(([key, value]) => ({ key, value })),
    files: [...files],
    events,
  };
}

export function resolveTimelineInspectionItems(
  selected: readonly AgentTimelineItem[],
  timeline: readonly AgentTimelineItem[],
): AgentTimelineItem[] {
  const latestById = new Map(timeline.map((item) => [item.id, item]));
  const results = exactToolResults(timeline);
  const resolved = new Map<string, AgentTimelineItem>();
  for (const item of selected) {
    resolved.set(item.id, latestById.get(item.id) ?? item);
    const result = results.get(item.id);
    if (result) resolved.set(result.id, result);
  }
  return [...resolved.values()];
}
