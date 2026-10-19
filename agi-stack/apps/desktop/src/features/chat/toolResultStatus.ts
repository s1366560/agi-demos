import type { AgentTimelineItem } from '../../types';

export type ToolResultStatus = 'complete' | 'failed' | 'paused' | 'stopped';

/** Only the runtime-owned event field denotes a user control outcome. */
export function timelineToolControlStatus(item: AgentTimelineItem): 'paused' | 'stopped' | null {
  if (!['observe', 'tool_result'].includes(item.type) || timelineToolResultFailed(item)) return null;
  const payload = item.payload && typeof item.payload === 'object' && !Array.isArray(item.payload)
    ? item.payload as Record<string, unknown> : {};
  const outcome = item.controlOutcome ?? payload.control_outcome;
  return outcome === 'user_paused' ? 'paused' : outcome === 'user_stopped' ? 'stopped' : null;
}

export function timelineToolResultStatus(item: AgentTimelineItem): ToolResultStatus {
  return timelineToolResultFailed(item) ? 'failed' : timelineToolControlStatus(item) ?? 'complete';
}

/** Protocol-level failure only; prose and nested user data are not classified. */
export function structuredToolResultFailed(output: unknown): boolean {
  if (typeof output === 'string') {
    try {
      output = JSON.parse(output);
    } catch {
      return false;
    }
  }
  if (!output || typeof output !== 'object' || Array.isArray(output))
    return false;
  const result = output as Record<string, unknown>;
  return (
    result.isError === true ||
    result.is_error === true ||
    result.success === false ||
    (typeof result.error === 'string' && result.error.trim().length > 0) ||
    (result.error !== null &&
      typeof result.error === 'object' &&
      !Array.isArray(result.error))
  );
}

/** Covers historical records that predate normalized isError fields. */
export function timelineToolResultFailed(item: AgentTimelineItem): boolean {
  const payload =
    item.payload &&
    typeof item.payload === 'object' &&
    !Array.isArray(item.payload)
      ? (item.payload as Record<string, unknown>)
      : {};
  return (
    Boolean(item.isError || item.error) ||
    payload.is_error === true ||
    payload.isError === true ||
    structuredToolResultFailed(
      item.toolOutput ??
        payload.observation ??
        payload.tool_output ??
        payload.toolOutput,
    )
  );
}
