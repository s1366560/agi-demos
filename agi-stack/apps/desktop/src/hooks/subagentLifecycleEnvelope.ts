import { normalizeAgentLifecycleEnvelope } from "./agentLifecycleEnvelope";
import type { AgentWsEvent, DesktopRuntimeConfig } from "../types";

const lifecycleTypes = new Set([
  "subagent_spawning",
  "subagent_spawned",
  "subagent_ended",
  "subagent_killed",
  "subagent_failed",
  "subagent_completed",
  "subagent_queued",
  "subagent_spawn_rejected",
  "subagent_steered",
]);

/** Decode project notifications without granting control or advancing the conversation cursor. */
export function normalizeSubagentLifecycleEnvelope(
  event: AgentWsEvent,
  context: Pick<DesktopRuntimeConfig, "mode" | "tenantId" | "projectId">,
): AgentWsEvent | null {
  if (event.type === "agent_lifecycle") return normalizeAgentLifecycleEnvelope(event, context);
  if (event.type !== "subagent_lifecycle") return event;
  if (
    context.mode !== "cloud" ||
    !context.tenantId ||
    !context.projectId ||
    event.tenant_id !== context.tenantId ||
    event.project_id !== context.projectId
  )
    return null;
  const inner = record(event.data);
  if (
    !inner ||
    typeof inner.type !== "string" ||
    !lifecycleTypes.has(inner.type)
  )
    return null;
  const payload = inner.data === undefined ? inner : record(inner.data);
  if (!payload) return null;
  const records = [event, inner, payload];
  for (const [key, expected] of [
    ["tenant_id", context.tenantId],
    ["project_id", context.projectId],
  ]) {
    if (
      records.some(
        (value) => value[key] !== undefined && value[key] !== expected,
      )
    )
      return null;
  }
  const conversationId = consistentIdentity(records, "conversation_id");
  const runId = consistentIdentity(records, "run_id");
  if (!conversationId || !runId) return null;
  if (
    records.some(
      (value) => value.execution_id != null && value.execution_id !== runId,
    )
  )
    return null;

  let type = inner.type;
  if (type === "subagent_spawned") type = "subagent_started";
  if (type === "subagent_ended") {
    // Mirror the cloud trace snapshot's status→timeline mapping so live
    // ended notifications match the 3s snapshot projection, including
    // timed_out/pending runs (payload.status rides through unchanged).
    if (payload.status === "completed") type = "subagent_run_completed";
    else if (payload.status === "failed" || payload.status === "timed_out")
      type = "subagent_run_failed";
    else if (payload.status === "cancelled") type = "subagent_killed";
    else if (payload.status === "pending") type = "subagent_queued";
    else return null;
  }
  const timestamp = event.timestamp ?? inner.timestamp;
  const timeMs = typeof timestamp === "string" ? Date.parse(timestamp) : NaN;
  const producerId =
    typeof event.event_id === "string" && event.event_id
      ? event.event_id
      : null;
  if (!producerId && !Number.isFinite(timeMs)) return null;
  const eventId = `subagent-lifecycle:${JSON.stringify([
    context.tenantId,
    context.projectId,
    conversationId,
    runId,
    inner.type,
    producerId ?? timestamp,
  ])}`;
  return {
    type,
    event_id: eventId,
    lifecycle_event_id: eventId,
    timeline_cursor_source: "project_lifecycle",
    tenant_id: context.tenantId,
    project_id: context.projectId,
    conversation_id: conversationId,
    // No counter: lifecycle notifications use a separate channel from conversation replay.
    ...(Number.isFinite(timeMs)
      ? { event_time_us: Math.trunc(timeMs * 1000) }
      : {}),
    data: {
      ...payload,
      lifecycle_type: inner.type,
      conversation_id: conversationId,
      run_id: runId,
      execution_id: runId,
    },
  };
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function consistentIdentity(
  records: Record<string, unknown>[],
  key: string,
): string | null {
  const values = records
    .map((value) => value[key])
    .filter((value) => value !== undefined);
  const first = values[0];
  return typeof first === "string" &&
    first.trim() &&
    values.every((value) => value === first)
    ? first
    : null;
}
