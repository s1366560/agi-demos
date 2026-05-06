/**
 * Turn-aware folding for the agent message list.
 *
 * A "turn" starts at a user message and continues until the next user message.
 * Folding lets users collapse all agent activity (thoughts, tool calls, sub-agent
 * groups, assistant messages) emitted in response to a single prompt into a
 * single placeholder row.
 *
 * Inspired by Routa's `groupIntoConversationTurns` in `trace-panel.tsx`.
 *
 * The output extends `GroupedItem` with a `turn-placeholder` kind so the
 * existing virtualizer can render it without restructuring the list.
 */

import type { GroupedItem } from './groupTimelineEvents';

export interface TurnPlaceholderItem {
  kind: 'turn-placeholder';
  /** Stable id of the turn (== id of the user_message that opened it). */
  turnId: string;
  /** Number of grouped items being hidden. */
  hiddenCount: number;
  /** First and last positions in the original groupedItems array. */
  startIndex: number;
  endIndex: number;
}

export type DisplayItem = GroupedItem | TurnPlaceholderItem;

/**
 * Identify the turn id for an item. A turn id is the id of the user message
 * that opened the turn. Returns `null` if the item is itself the user message
 * (we treat the user message as the visible header for its turn) or if the
 * item appears before any user message in the conversation (preamble).
 */
export interface TurnInfo {
  /** Stable id for each turn (the user message id, or `__preamble__`). */
  turnId: string;
  /** Index of the user message in `groupedItems`, or `-1` for preamble. */
  userIndex: number;
  /** Indices in `groupedItems` belonging to this turn's agent block. */
  agentIndices: number[];
}

const PREAMBLE_TURN_ID = '__preamble__';

/**
 * Compute the list of turns from already-grouped items.
 */
export function computeTurns(items: GroupedItem[]): TurnInfo[] {
  const turns: TurnInfo[] = [];
  let current: TurnInfo = {
    turnId: PREAMBLE_TURN_ID,
    userIndex: -1,
    agentIndices: [],
  };

  items.forEach((item, idx) => {
    if (item.kind === 'event' && item.event.type === 'user_message') {
      // Push the previous turn (which may be the preamble) before opening a new one.
      if (current.userIndex !== -1 || current.agentIndices.length > 0) {
        turns.push(current);
      }
      current = {
        turnId: item.event.id || `turn-${String(idx)}`,
        userIndex: idx,
        agentIndices: [],
      };
      return;
    }
    current.agentIndices.push(idx);
  });

  if (current.userIndex !== -1 || current.agentIndices.length > 0) {
    turns.push(current);
  }

  return turns;
}

/**
 * Apply collapsed-turn state to the grouped items list. Indices in
 * `collapsedTurnIds` are replaced with a single `turn-placeholder` item so the
 * virtualizer can size and position it like any other row.
 *
 * Note: the user message itself stays visible — only the agent block under it
 * is collapsed, which gives the user a natural anchor to expand again.
 */
export function applyTurnCollapse(
  items: GroupedItem[],
  collapsedTurnIds: ReadonlySet<string>
): DisplayItem[] {
  if (collapsedTurnIds.size === 0) return items;
  const turns = computeTurns(items);
  const result: DisplayItem[] = [];
  const turnByStart = new Map<number, TurnInfo>();
  for (const turn of turns) {
    if (turn.agentIndices.length === 0) continue;
    const first = turn.agentIndices[0];
    if (typeof first === 'number') turnByStart.set(first, turn);
  }

  let i = 0;
  while (i < items.length) {
    const turn = turnByStart.get(i);
    if (turn && collapsedTurnIds.has(turn.turnId)) {
      const lastIndex = turn.agentIndices[turn.agentIndices.length - 1];
      const endIndex = typeof lastIndex === 'number' ? lastIndex : i;
      result.push({
        kind: 'turn-placeholder',
        turnId: turn.turnId,
        hiddenCount: turn.agentIndices.length,
        startIndex: i,
        endIndex,
      });
      i = endIndex + 1;
      continue;
    }
    const item = items[i];
    if (item) result.push(item);
    i += 1;
  }
  return result;
}

export function isTurnPlaceholder(item: DisplayItem): item is TurnPlaceholderItem {
  return (item as TurnPlaceholderItem).kind === 'turn-placeholder';
}
