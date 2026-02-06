/**
 * Timeline utility functions
 *
 * Provides helper functions for timeline operations including
 * safe sorting by sequence number with null/undefined handling.
 */

import type { TimelineEvent } from '../types/agent';

/**
 * Compare two timeline events by sequence number for sorting.
 *
 * Handles edge cases:
 * - null/undefined sequence numbers are treated as Infinity (placed at end)
 * - Falls back to timestamp comparison if both sequence numbers are invalid
 * - Stable sort: maintains original order for equal sequence numbers
 *
 * @param a - First timeline event
 * @param b - Second timeline event
 * @returns Negative if a < b, positive if a > b, 0 if equal
 */
export function compareTimelineEvents(a: TimelineEvent, b: TimelineEvent): number {
  const seqA = a.sequenceNumber;
  const seqB = b.sequenceNumber;

  // Handle null/undefined sequence numbers
  const hasSeqA = seqA !== null && seqA !== undefined && !isNaN(seqA);
  const hasSeqB = seqB !== null && seqB !== undefined && !isNaN(seqB);

  // Both have valid sequence numbers - compare normally
  if (hasSeqA && hasSeqB) {
    return seqA - seqB;
  }

  // Only a has valid sequence number - a comes first
  if (hasSeqA && !hasSeqB) {
    return -1;
  }

  // Only b has valid sequence number - b comes first
  if (!hasSeqA && hasSeqB) {
    return 1;
  }

  // Neither has valid sequence number - fall back to timestamp
  const timeA = a.timestamp ?? 0;
  const timeB = b.timestamp ?? 0;

  if (timeA !== timeB) {
    return timeA - timeB;
  }

  // Final fallback: stable sort using event id
  return a.id.localeCompare(b.id);
}

/**
 * Sort timeline events by sequence number in ascending order.
 *
 * Creates a new sorted array without mutating the original.
 * Events with null/undefined sequence numbers are placed at the end.
 *
 * @param timeline - Array of timeline events to sort
 * @returns New sorted array
 *
 * @example
 * ```typescript
 * const sorted = sortTimelineBySequence(unsortedTimeline);
 * // sorted[0] has lowest sequenceNumber
 * // sorted[sorted.length - 1] has highest sequenceNumber
 * ```
 */
export function sortTimelineBySequence(timeline: TimelineEvent[]): TimelineEvent[] {
  return [...timeline].sort(compareTimelineEvents);
}

/**
 * Check if timeline is properly sorted by sequence number.
 *
 * Useful for debugging and validation.
 *
 * @param timeline - Array of timeline events to check
 * @returns true if sorted correctly, false otherwise
 */
export function isTimelineSorted(timeline: TimelineEvent[]): boolean {
  for (let i = 1; i < timeline.length; i++) {
    const prev = timeline[i - 1];
    const curr = timeline[i];

    const prevSeq = prev.sequenceNumber;
    const currSeq = curr.sequenceNumber;

    // Skip comparison if either sequence number is invalid
    if (
      prevSeq === null ||
      prevSeq === undefined ||
      isNaN(prevSeq) ||
      currSeq === null ||
      currSeq === undefined ||
      isNaN(currSeq)
    ) {
      continue;
    }

    if (prevSeq > currSeq) {
      return false;
    }
  }

  return true;
}

/**
 * Find the next expected sequence number for a timeline.
 *
 * @param timeline - Array of timeline events
 * @returns Next sequence number (highest + 1), or 1 if empty
 */
export function getNextSequenceNumber(timeline: TimelineEvent[]): number {
  if (timeline.length === 0) {
    return 1;
  }

  const sorted = sortTimelineBySequence(timeline);
  const lastEvent = sorted[sorted.length - 1];

  const lastSeq = lastEvent?.sequenceNumber;
  if (lastSeq === null || lastSeq === undefined || isNaN(lastSeq)) {
    // If last event has no sequence number, count events and return next
    return timeline.length + 1;
  }

  return lastSeq + 1;
}

/**
 * Merge two timelines and sort by sequence number.
 *
 * Handles duplicate events (same id) by keeping the event from the primary timeline.
 *
 * @param primary - Primary timeline (takes precedence for duplicates)
 * @param secondary - Secondary timeline to merge
 * @returns Merged and sorted timeline
 */
export function mergeTimelines(
  primary: TimelineEvent[],
  secondary: TimelineEvent[]
): TimelineEvent[] {
  // Create a map of existing event IDs from primary
  const existingIds = new Set(primary.map((e) => e.id));

  // Filter out duplicates from secondary
  const uniqueSecondary = secondary.filter((e) => !existingIds.has(e.id));

  // Combine and sort
  return sortTimelineBySequence([...primary, ...uniqueSecondary]);
}
