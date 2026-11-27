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
function grouped(rows: readonly TranscriptRow[]) {
  const items: GroupedItem[] = [];
  const rowOf = new Map<GroupedItem, TranscriptRow>();
  rows.forEach((row, index) => {
    const item: GroupedItem =
      row.kind === "steps"
        ? { kind: "timeline", steps: row.steps, startIndex: index }
        : {
            kind: "event",
            event: {
              id: row.id,
              type:
                row.kind === "message"
                  ? row.message.role
                  : row.kind === "thought"
                    ? "thought"
                    : row.event.type,
            } as TimelineEvent,
            index,
          };
    items.push(item);
    rowOf.set(item, row);
  });
  return { items, rowOf };
}

/** Hide what answers a user message when its turn is folded, as the original transcript does. */
export function foldTurns(
  rows: readonly TranscriptRow[],
  collapsed: ReadonlySet<string>,
): TranscriptEntry[] {
  const { items, rowOf } = grouped(rows);
  // Every item comes from a row of this list, so the lookup never misses.
  const row = (item: GroupedItem) => rowOf.get(item) as TranscriptRow;
  return applyTurnCollapse(items, collapsed).map(
    (item): TranscriptEntry =>
      isTurnPlaceholder(item)
        ? { kind: "folded", turnId: item.turnId, hiddenCount: item.hiddenCount }
        : { kind: "row", row: row(item) },
  );
}

/** The turns that have something to fold, by the id of the user message that opens them. */
export function foldableTurns(
  rows: readonly TranscriptRow[],
): Map<string, number> {
  const { items } = grouped(rows);
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
