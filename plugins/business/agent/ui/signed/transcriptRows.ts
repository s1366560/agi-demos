import type { TimelineEvent } from "@/types/agent";

import { coalesceToolCallDrafts } from "@/utils/toolCallTimeline";
import { normalizeExecutionSummary } from "@/utils/executionSummary";
import {
  filterAutomaticPermissionEvents,
  mergeHITLResponseEvents,
} from "../web/stores/agent/timelineUtils";
import { groupTimelineEvents } from "../web/transcript/message/groupTimelineEvents";
import type { TimelineStep } from "../web/transcript/timeline/ExecutionTimeline";

import type { InteractionEvent } from "./useInteractions";
import type { Message, Thought } from "./useChat";

export type { Thought } from "./useChat";

export type TranscriptRow =
  | { kind: "message"; id: string; message: Message }
  | { kind: "thought"; id: string; content: string; timestamp?: number }
  | { kind: "steps"; id: string; steps: TimelineStep[] }
  /** A human-in-the-loop card or an error notice, drawn from its event. */
  | { kind: "event"; id: string; event: InteractionEvent }
  /** A memory step of a turn: what was recalled or captured at that point. */
  | { kind: "memory"; id: string; event: InteractionEvent };

/** Event time and counter locate a row inside the conversation timeline. */
type Position = [time: number, counter: number];
type Positioned<T> = T & { at: Position };

// Every other event keeps its place and is not drawn.
const MEMORY = new Set(["memory_recalled", "memory_captured"]);
const REQUESTS = new Set([
  "permission_asked",
  "permission_requested",
  "clarification_asked",
  "decision_asked",
  "env_var_requested",
]);
const DRAWN = new Set([
  "error",
  ...REQUESTS,
  "permission_replied",
  "permission_granted",
  "clarification_answered",
  "decision_answered",
  "env_var_provided",
  ...MEMORY,
]);

/**
 * A request that is still waiting is answered from the panel of the page. The
 * transcript draws it once it is answered, where it was asked.
 */
function answered(event: TimelineEvent): boolean {
  return (
    !REQUESTS.has(event.type) ||
    (event as { answered?: boolean }).answered === true
  );
}

function position(row: {
  eventTimeUs?: number;
  eventCounter?: number;
}): Position | null {
  return typeof row.eventTimeUs === "number"
    ? [row.eventTimeUs, row.eventCounter ?? 0]
    : null;
}

function compare(a: Position, b: Position): number {
  return a[0] - b[0] || a[1] - b[1];
}

/**
 * Place every row of the loaded history on the timeline. A row that both commands
 * report is placed once, from the one that carries its text.
 */
function load(
  messages: readonly Message[],
  thoughts: readonly Thought[],
  events: readonly InteractionEvent[],
) {
  const placed = new Map<string, Position>();
  const timeline: TimelineEvent[] = [];
  const rows = new Map<string, TranscriptRow>();
  const place = (
    id: string,
    at: Position | null,
    event: TimelineEvent,
    row?: TranscriptRow,
  ) => {
    if (!at || placed.has(id)) return false;
    placed.set(id, at);
    timeline.push(event);
    if (row) rows.set(id, row);
    return true;
  };
  const streaming: Message[] = [];
  for (const message of messages) {
    const row: TranscriptRow = { kind: "message", id: message.id, message };
    if (
      !place(
        message.id,
        position(message),
        {
          id: message.id,
          type: message.role,
          timestamp: message.timestamp,
        } as TimelineEvent,
        row,
      )
    )
      streaming.push(message);
  }
  const live: Thought[] = [];
  for (const thought of thoughts) {
    const row: TranscriptRow = {
      kind: "thought",
      id: thought.id,
      content: thought.content,
      timestamp: thought.timestamp,
    };
    if (
      !place(
        thought.id,
        position(thought),
        {
          id: thought.id,
          type: "thought",
          content: thought.content,
          timestamp: thought.timestamp,
        } as TimelineEvent,
        row,
      )
    )
      live.push(thought);
  }
  const stepAt = new Map<string, Position>();
  for (const event of events) {
    const at = position(event);
    const drawn: TranscriptRow | undefined = !DRAWN.has(event.type)
      ? undefined
      : {
          kind: MEMORY.has(event.type) ? "memory" : "event",
          id: event.id,
          event,
        };
    if (!place(event.id, at, event as unknown as TimelineEvent, drawn))
      continue;
    if (event.type === "act") stepAt.set(event.execution_id ?? event.id, at!);
  }
  timeline.sort((a, b) => compare(placed.get(a.id)!, placed.get(b.id)!));

  return { placed, timeline, rows, streaming, live, stepAt };
}

/** The rows of the timeline, counted the way the original transcript counts them. */
export function timelineCount(
  messages: readonly Message[],
  thoughts: readonly Thought[],
  events: readonly InteractionEvent[],
): number {
  const { timeline } = load(messages, thoughts, events);
  return coalesceToolCallDrafts(mergeHITLResponseEvents(timeline)).length;
}

/**
 * Order the loaded history of a conversation the way the original workbench
 * transcript does: a turn shows its reasoning, its tool steps, its messages, its
 * requests and its errors in the order they happened, and an answer is shown on
 * the request it belongs to. The merging, the grouping and the hiding of
 * automatically allowed permissions are the functions of the original transcript.
 *
 * Messages and reasoning come from the history command and the other events from
 * the interactions command. Rows that are still being sent have no position yet
 * and follow the loaded history.
 */
export function transcriptRows(
  messages: readonly Message[],
  thoughts: readonly Thought[],
  events: readonly InteractionEvent[],
): TranscriptRow[] {
  const { placed, timeline, rows, streaming, live, stepAt } = load(
    messages,
    thoughts,
    events,
  );

  // The original transcript, in its order: an answer is merged into its request,
  // an argument draft gives way to its execution, an automatically allowed
  // permission is hidden, then consecutive tool steps are grouped.
  const grouped: Positioned<TranscriptRow>[] = [];
  for (const item of groupTimelineEvents(
    filterAutomaticPermissionEvents(
      coalesceToolCallDrafts(mergeHITLResponseEvents(timeline)),
    ),
  )) {
    if (item.kind === "subagent") continue;
    if (item.kind === "timeline") {
      const first = item.steps[0];
      const at = first && stepAt.get(first.id);
      if (at)
        grouped.push({
          kind: "steps",
          id: `steps:${first!.id}`,
          steps: item.steps,
          at,
        });
    } else {
      const at = placed.get(item.event.id);
      const row = rows.get(item.event.id);
      // A card reads the event after the answer was merged into it.
      if (at && row && answered(item.event))
        grouped.push(
          "event" in row
            ? { ...row, event: item.event as unknown as InteractionEvent, at }
            : { ...row, at },
        );
    }
  }

  const rowsOf = (positioned: Positioned<TranscriptRow>[]) =>
    positioned.map(({ at: _at, ...row }) => row);
  const messageRow = (message: Message): TranscriptRow => ({
    kind: "message",
    id: message.id,
    message,
  });
  const thoughtRow = (thought: Thought): TranscriptRow => ({
    kind: "thought",
    id: thought.id,
    content: thought.content,
    timestamp: thought.timestamp,
  });
  const answer =
    streaming.at(-1)?.role === "assistant_message"
      ? streaming.at(-1)
      : undefined;
  const settled = answer ? streaming.slice(0, -1) : streaming;
  const sending = settled[0]?.role === "user_message" ? settled[0] : undefined;
  const rest = [
    ...settled.slice(1).map(messageRow),
    ...(answer ? [messageRow(answer)] : []),
  ];
  // Reasoning that arrives while the page streams has no position of its own yet.
  // It follows the events that were read when it arrived, and at least the last
  // message of the history, until the page reads its position.
  const turn = (
    arrived: readonly Thought[],
    rows: readonly Positioned<TranscriptRow>[],
    floor: Position | undefined,
  ): TranscriptRow[] => {
    const pending = arrived.map((thought) => {
      const anchor = latestPosition([
        { eventTimeUs: thought.after?.[0], eventCounter: thought.after?.[1] },
        { eventTimeUs: floor?.[0], eventCounter: floor?.[1] },
      ]);
      return {
        thought,
        key: anchor ? ([anchor[0], anchor[1] + 0.25] as Position) : null,
      };
    });
    const out: TranscriptRow[] = [];
    let next = 0;
    const read = (limit: Position | null) => {
      while (next < pending.length) {
        const entry = pending[next];
        // Reasoning with nothing read before it comes first.
        if (entry.key && limit && compare(entry.key, limit) >= 0) break;
        out.push(thoughtRow(entry.thought));
        next++;
      }
    };
    for (const row of rows) {
      read(row.at);
      out.push(rowsOf([row])[0]);
    }
    read(null);
    return out;
  };
  const lastLoaded = messages
    .map(position)
    .filter(Boolean)
    .sort(compare)
    .at(-1);
  // The first turn of a conversation has no history to anchor the message being
  // sent: it comes first, and what happened in its turn follows it.
  if (!lastLoaded && sending && grouped.length && streaming.length <= 2)
    return [messageRow(sending), ...turn(live, grouped, undefined), ...rest];
  // A message on its way is the boundary: what happened before it is history, and
  // later reasoning and tool steps belong to the turn it starts. Its answer is
  // streamed without a position and therefore stays last.
  if (lastLoaded && sending) {
    const boundary: Position = [lastLoaded[0], lastLoaded[1] + 0.5];
    return [
      ...rowsOf(grouped.filter((row) => compare(row.at, boundary) < 0)),
      messageRow(sending),
      ...turn(
        live,
        grouped.filter((row) => compare(row.at, boundary) > 0),
        lastLoaded,
      ),
      ...rest,
    ];
  }
  // Without a boundary, a history keeps its own order. Reasoning that arrives while
  // the page streams is placed before the answer that is still being written.
  return [
    ...rowsOf(grouped),
    ...settled.map(messageRow),
    ...live.map(thoughtRow),
    ...(answer ? [messageRow(answer)] : []),
  ];
}

/** The last position among events, to place what arrives after them. */
export function latestPosition(
  events: readonly { eventTimeUs?: number; eventCounter?: number }[],
): Position | undefined {
  const last = events.map(position).filter(Boolean).sort(compare).at(-1);
  return last;
}

/** The original transcript draws no bubble for an answer without text once its turn is over. */
export function hasBubble(message: Message, streaming: boolean): boolean {
  return (
    !!message.content ||
    streaming ||
    normalizeExecutionSummary(message.summary) !== null
  );
}
