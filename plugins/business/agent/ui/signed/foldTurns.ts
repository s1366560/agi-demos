import type { GroupedItem } from "../web/transcript/message/groupTimelineEvents";
import {
  applyTurnCollapse,
  computeTurns,
  isTurnPlaceholder,
} from "../web/transcript/message/turnFolding";
import type { TimelineEvent } from "@/types/agent";

import type { TranscriptRow } from "./transcriptRows";

/** One entry of the shown transcript: a row, or the placeholder of a folded turn. */
export type TranscriptEntry =
  | { kind: "row"; row: TranscriptRow }
  | { kind: "folded"; turnId: string; hiddenCount: number };

// The rows as the items the turn folding of the original transcript works on.
function grouped(rows: readonly TranscriptRow[]): GroupedItem[] {
  return rows.map((row, index): GroupedItem => {
    if (row.kind === "steps")
      return { kind: "timeline", steps: row.steps, startIndex: index };
    const type =
      row.kind === "message"
        ? row.message.role
        : row.kind === "thought"
          ? "thought"
          : row.event.type;
    return {
      kind: "event",
      event: { id: row.id, type } as TimelineEvent,
      index,
    };
  });
}

/** Hide what answers a user message when its turn is folded, as the original transcript does. */
export function foldTurns(
  rows: readonly TranscriptRow[],
  collapsed: ReadonlySet<string>,
): TranscriptEntry[] {
  const items = applyTurnCollapse(grouped(rows), collapsed);
  const at = (item: GroupedItem) =>
    rows[item.kind === "timeline" ? item.startIndex : item.index];
  return items.map(
    (item): TranscriptEntry =>
      isTurnPlaceholder(item)
        ? { kind: "folded", turnId: item.turnId, hiddenCount: item.hiddenCount }
        : { kind: "row", row: at(item) },
  );
}

/** The turns that have something to fold, by the id of the user message that opens them. */
export function foldableTurns(
  rows: readonly TranscriptRow[],
): Map<string, number> {
  const items = grouped(rows);
  const turns = new Map<string, number>();
  for (const turn of computeTurns(items)) {
    const opener = items[turn.userIndex];
    if (
      turn.userIndex < 0 ||
      !turn.agentIndices.length ||
      opener?.kind !== "event"
    )
      continue;
    turns.set(opener.event.id, turn.agentIndices.length);
  }
  return turns;
}
