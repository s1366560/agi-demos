/**
 * Timeline utility functions
 *
 * Provides helper functions for timeline operations including
 * safe sorting by eventTimeUs + eventCounter with null/undefined handling.
 */

import type { TimelineEvent } from '../types/agent';

/**
 * Compare two timeline events by eventTimeUs and eventCounter for sorting.
 *
 * Handles edge cases:
 * - null/undefined eventTimeUs are treated as Infinity (placed at end)
 * - Falls back to timestamp comparison if both eventTimeUs are missing
 * - Stable sort: maintains original order for equal keys
 *
 * @param a - First timeline event
 * @param b - Second timeline event
 * @returns Negative if a < b, positive if a > b, 0 if equal
 */
export function compareTimelineEvents(a: TimelineEvent, b: TimelineEvent): number {
  const timeA = a.eventTimeUs;
  const timeB = b.eventTimeUs;

  // Handle null/undefined eventTimeUs
  const hasTimeA = timeA !== null && timeA !== undefined && !isNaN(timeA);
  const hasTimeB = timeB !== null && timeB !== undefined && !isNaN(timeB);

  // Both have valid eventTimeUs - compare by time first, then counter
  if (hasTimeA && hasTimeB) {
    if (timeA !== timeB) {
      return timeA - timeB;
    }
    // Same time - compare by counter
    const counterA = a.eventCounter ?? 0;
    const counterB = b.eventCounter ?? 0;
    return counterA - counterB;
  }

  // Only a has valid eventTimeUs - a comes first
  if (hasTimeA && !hasTimeB) {
    return -1;
  }

  // Only b has valid eventTimeUs - b comes first
  if (!hasTimeA && hasTimeB) {
    return 1;
  }

  // Neither has valid eventTimeUs - fall back to timestamp
  const tsA = a.timestamp ?? 0;
  const tsB = b.timestamp ?? 0;

  if (tsA !== tsB) {
    return tsA - tsB;
  }

  // Final fallback: stable sort using event id
  return a.id.localeCompare(b.id);
}

/**
 * Sort timeline events by eventTimeUs + eventCounter in ascending order.
 *
 * Creates a new sorted array without mutating the original.
 * Events with null/undefined eventTimeUs are placed at the end.
 *
 * @param timeline - Array of timeline events to sort
 * @returns New sorted array
 */
export function sortTimeline(timeline: TimelineEvent[]): TimelineEvent[] {
  return [...timeline].sort(compareTimelineEvents);
}

/**
 * Alias for backward compatibility
 */
export const sortTimelineBySequence = sortTimeline;

/**
 * Check if timeline is properly sorted by eventTimeUs + eventCounter.
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

    const prevTime = prev.eventTimeUs;
    const currTime = curr.eventTimeUs;

    // Skip comparison if either eventTimeUs is invalid
    if (
      prevTime === null ||
      prevTime === undefined ||
      isNaN(prevTime) ||
      currTime === null ||
      currTime === undefined ||
      isNaN(currTime)
    ) {
      continue;
    }

    if (prevTime > currTime) {
      return false;
    }
    if (prevTime === currTime) {
      const prevCounter = prev.eventCounter ?? 0;
      const currCounter = curr.eventCounter ?? 0;
      if (prevCounter > currCounter) {
        return false;
      }
    }
  }

  return true;
}

/**
 * Merge two timelines and sort by eventTimeUs + eventCounter.
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
  return sortTimeline([...primary, ...uniqueSecondary]);
}
