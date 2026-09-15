import type { AgentWsEvent, DesktopRuntimeConfig } from "../types";

/** Peer completion is observational: its child identity never grants parent control. */
export function normalizeAgentLifecycleEnvelope(
  event: AgentWsEvent,
  context: Pick<DesktopRuntimeConfig, "mode" | "tenantId" | "projectId">,
): AgentWsEvent | null {
  if (
    context.mode !== "cloud" ||
    !context.tenantId ||
    !context.projectId ||
    event.tenant_id !== context.tenantId ||
    event.project_id !== context.projectId
  )
    return null;
  const inner = record(event.data);
  const data = record(inner?.data);
  if (
    !inner ||
    !data ||
    !["agent_completed", "agent_stopped"].includes(String(inner.type))
  )
    return null;
  const parent = identifier(data.parent_session_id);
  const child = identifier(data.child_session_id);
  const run = identifier(data.child_run_id);
  const spawn = identifier(data.spawn_id);
  if (
    !parent ||
    !child ||
    !run ||
    !spawn ||
    parent === child ||
    event.conversation_id !== parent ||
    data.session_id !== child ||
    !identifier(data.agent_id) ||
    !identifier(data.parent_agent_id)
  )
    return null;
  if (
    !["completed", "failed", "cancelled"].includes(String(data.status)) ||
    data.success !== (data.status === "completed") ||
    inner.type !==
      (data.status === "cancelled" ? "agent_stopped" : "agent_completed")
  )
    return null;
  for (const value of [inner, data]) {
    if (
      (value.tenant_id !== undefined && value.tenant_id !== context.tenantId) ||
      (value.project_id !== undefined &&
        value.project_id !== context.projectId) ||
      (value.conversation_id !== undefined && value.conversation_id !== parent)
    )
      return null;
  }
  const time = inner.event_time_us;
  const counter = inner.event_counter;
  if (
    typeof time !== "number" ||
    !Number.isSafeInteger(time) ||
    time <= 0 ||
    typeof counter !== "number" ||
    !Number.isSafeInteger(counter) ||
    counter < 0
  )
    return null;
  return {
    type: inner.type as string,
    event_id: `peer-terminal:${run}`,
    lifecycle_event_id: `${inner.type}-${time}-${counter}`,
    timeline_cursor_source: "project_lifecycle",
    tenant_id: context.tenantId,
    project_id: context.projectId,
    conversation_id: parent,
    event_time_us: time,
    // Project notifications must not advance the parent conversation stream counter.
    data: { ...data },
  };
}

function identifier(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}
function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}
