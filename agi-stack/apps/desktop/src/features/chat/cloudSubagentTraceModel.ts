import type { AgentTimelineItem } from "../../types";

const statuses = new Set([
  "pending",
  "running",
  "completed",
  "failed",
  "cancelled",
  "timed_out",
]);
const terminalTypes = new Set([
  "subagent_run_completed",
  "subagent_run_failed",
  "subagent_killed",
  "subagent_completed",
  "subagent_failed",
]);
const lifecycleTypes = new Set([
  "subagent_spawning",
  "subagent_started",
  "subagent_queued",
  "subagent_steered",
  ...terminalTypes,
]);

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function identity(value: unknown): value is string {
  return (
    typeof value === "string" && value.length > 0 && value === value.trim()
  );
}
function time(value: unknown): number | null {
  return typeof value === "string" && Number.isFinite(Date.parse(value))
    ? Date.parse(value)
    : null;
}

/** Only the currently retained registry records are represented; this is not conversation replay. */
export function projectCloudSubagentTrace(
  value: unknown,
  conversationId: string,
  observedAt: number,
): AgentTimelineItem[] {
  if (
    !record(value) ||
    value.conversation_id !== conversationId ||
    !Array.isArray(value.runs) ||
    !Number.isSafeInteger(value.total) ||
    value.total !== value.runs.length ||
    !Number.isSafeInteger(observedAt)
  ) {
    throw new Error("cloud_subagent_trace_contract_invalid");
  }
  const seen = new Set<string>();
  return value.runs.map((row) => {
    if (
      !record(row) ||
      row.conversation_id !== conversationId ||
      !identity(row.run_id) ||
      seen.has(row.run_id) ||
      !identity(row.subagent_name) ||
      typeof row.task !== "string" ||
      typeof row.status !== "string" ||
      !statuses.has(row.status) ||
      time(row.created_at) === null ||
      !record(row.metadata) ||
      ["started_at", "ended_at", "frozen_at"].some(
        (key) => row[key] != null && time(row[key]) === null,
      ) ||
      [
        "summary",
        "error",
        "frozen_result_text",
        "trace_id",
        "parent_span_id",
        "announce_state",
      ].some((key) => row[key] != null && typeof row[key] !== "string") ||
      ["tokens_used", "execution_time_ms"].some(
        (key) =>
          row[key] != null &&
          (!Number.isSafeInteger(row[key]) || Number(row[key]) < 0),
      )
    ) {
      throw new Error("cloud_subagent_trace_run_invalid");
    }
    seen.add(row.run_id);
    const timestamp =
      time(row.ended_at) ?? time(row.started_at) ?? time(row.created_at)!;
    const type =
      row.status === "pending"
        ? "subagent_queued"
        : row.status === "running"
          ? "subagent_started"
          : row.status === "completed"
            ? "subagent_run_completed"
            : row.status === "cancelled"
              ? "subagent_killed"
              : "subagent_run_failed";
    return {
      id: `subagent-trace:${JSON.stringify([conversationId, row.run_id])}`,
      type,
      cursorSource: "project_lifecycle",
      eventTimeUs: timestamp * 1000,
      eventCounter: 0,
      timestamp,
      metadata: { cloud_subagent_trace_snapshot: true, observedAt },
      payload: {
        conversation_id: conversationId,
        run_id: row.run_id,
        execution_id: row.run_id,
        subagent_name: row.subagent_name,
        task: row.task,
        status: row.status,
        summary: row.summary ?? row.frozen_result_text ?? "",
        error: row.error ?? "",
        tokens_used: row.tokens_used ?? null,
        execution_time_ms: row.execution_time_ms ?? null,
      },
    };
  });
}

function runId(item: AgentTimelineItem): string | null {
  const data = item.payload;
  return item.cursorSource === "project_lifecycle" &&
    lifecycleTypes.has(item.type) &&
    record(data) &&
    identity(data.run_id) &&
    data.execution_id === data.run_id
    ? data.run_id
    : null;
}
function sameRun(a: AgentTimelineItem, b: AgentTimelineItem): boolean {
  return (
    runId(a) !== null &&
    runId(a) === runId(b) &&
    record(a.payload) &&
    record(b.payload) &&
    a.payload.conversation_id === b.payload.conversation_id
  );
}
function snapshot(item: AgentTimelineItem): boolean {
  return item.metadata?.cloud_subagent_trace_snapshot === true;
}
function withUpdate(
  base: AgentTimelineItem,
  update: AgentTimelineItem,
): AgentTimelineItem {
  if (terminalTypes.has(base.type) && !terminalTypes.has(update.type))
    return base;
  return {
    ...base,
    type: update.type,
    payload: {
      ...(record(base.payload) ? base.payload : {}),
      ...(record(update.payload) ? update.payload : {}),
    },
    eventTimeUs: Math.max(base.eventTimeUs, update.eventTimeUs),
    timestamp: Math.max(base.timestamp ?? 0, update.timestamp ?? 0),
  };
}

/** Keep one registry snapshot per exact execution, preserving newer in-flight lifecycle updates. */
export function mergeCloudSubagentTraceItems(
  existing: AgentTimelineItem[],
  snapshots: AgentTimelineItem[],
): AgentTimelineItem[] {
  let items = existing.filter(
    (item) =>
      !snapshot(item) || snapshots.some((incoming) => sameRun(item, incoming)),
  );
  for (const incoming of snapshots) {
    let merged = incoming;
    for (const item of items) {
      if (!sameRun(item, incoming)) continue;
      const observedAt = Number(incoming.metadata?.observedAt);
      if (
        (terminalTypes.has(item.type) && !terminalTypes.has(incoming.type)) ||
        item.eventTimeUs > observedAt * 1000
      )
        merged = withUpdate(merged, item);
    }
    items = [...items.filter((item) => !sameRun(item, incoming)), merged];
  }
  return items.sort(
    (a, b) => a.eventTimeUs - b.eventTimeUs || a.eventCounter - b.eventCounter,
  );
}

/** A live notification updates an existing restored card, rather than adding a second terminal card. */
export function mergeCloudSubagentTraceLiveItem(
  existing: AgentTimelineItem[],
  incoming: AgentTimelineItem,
): AgentTimelineItem[] | null {
  const index = existing.findIndex(
    (item) => snapshot(item) && sameRun(item, incoming),
  );
  if (index < 0) return null;
  return existing.map((item, i) =>
    i === index ? withUpdate(item, incoming) : item,
  );
}
