/**
 * Tests for timeline utility functions
 */

import { describe, it, expect } from 'vitest';

import {
  compareTimelineEvents,
  sortTimelineBySequence,
  isTimelineSorted,
  getNextSequenceNumber,
  mergeTimelines,
} from '../../utils/timelineUtils';

import type { TimelineEvent } from '../../types/agent';

describe('timelineUtils', () => {
  describe('compareTimelineEvents', () => {
    it('should sort by sequence number when both are valid', () => {
      const a: TimelineEvent = {
        id: 'a',
        type: 'user_message',
        sequenceNumber: 1,
        timestamp: 1000,
        content: 'First',
        role: 'user',
      };
      const b: TimelineEvent = {
        id: 'b',
        type: 'user_message',
        sequenceNumber: 2,
        timestamp: 2000,
        content: 'Second',
        role: 'user',
      };

      expect(compareTimelineEvents(a, b)).toBeLessThan(0);
      expect(compareTimelineEvents(b, a)).toBeGreaterThan(0);
      expect(compareTimelineEvents(a, a)).toBe(0);
    });

    it('should place null sequence numbers at the end', () => {
      const withSeq: TimelineEvent = {
        id: 'a',
        type: 'user_message',
        sequenceNumber: 1,
        timestamp: 1000,
        content: 'With sequence',
        role: 'user',
      };
      const withoutSeq: TimelineEvent = {
        id: 'b',
        type: 'thought',
        sequenceNumber: null as any,
        timestamp: 500,
        content: 'Without sequence',
      };

      expect(compareTimelineEvents(withSeq, withoutSeq)).toBeLessThan(0);
      expect(compareTimelineEvents(withoutSeq, withSeq)).toBeGreaterThan(0);
    });

    it('should place undefined sequence numbers at the end', () => {
      const withSeq: TimelineEvent = {
        id: 'a',
        type: 'user_message',
        sequenceNumber: 1,
        timestamp: 1000,
        content: 'With sequence',
        role: 'user',
      };
      const withoutSeq: TimelineEvent = {
        id: 'b',
        type: 'thought',
        sequenceNumber: undefined as any,
        timestamp: 500,
        content: 'Without sequence',
      };

      expect(compareTimelineEvents(withSeq, withoutSeq)).toBeLessThan(0);
      expect(compareTimelineEvents(withoutSeq, withSeq)).toBeGreaterThan(0);
    });

    it('should fall back to timestamp when both sequence numbers are invalid', () => {
      const a: TimelineEvent = {
        id: 'a',
        type: 'thought',
        sequenceNumber: null as any,
        timestamp: 1000,
        content: 'First by timestamp',
      };
      const b: TimelineEvent = {
        id: 'b',
        type: 'thought',
        sequenceNumber: undefined as any,
        timestamp: 2000,
        content: 'Second by timestamp',
      };

      expect(compareTimelineEvents(a, b)).toBeLessThan(0);
      expect(compareTimelineEvents(b, a)).toBeGreaterThan(0);
    });

    it('should fall back to id when both sequence numbers and timestamps are equal', () => {
      const a: TimelineEvent = {
        id: 'a',
        type: 'thought',
        sequenceNumber: null as any,
        timestamp: 1000,
        content: 'A',
      };
      const b: TimelineEvent = {
        id: 'b',
        type: 'thought',
        sequenceNumber: null as any,
        timestamp: 1000,
        content: 'B',
      };

      expect(compareTimelineEvents(a, b)).toBeLessThan(0);
      expect(compareTimelineEvents(b, a)).toBeGreaterThan(0);
    });

    it('should handle NaN sequence numbers', () => {
      const withSeq: TimelineEvent = {
        id: 'a',
        type: 'user_message',
        sequenceNumber: 1,
        timestamp: 1000,
        content: 'With sequence',
        role: 'user',
      };
      const withNaN: TimelineEvent = {
        id: 'b',
        type: 'thought',
        sequenceNumber: NaN,
        timestamp: 500,
        content: 'With NaN',
      };

      expect(compareTimelineEvents(withSeq, withNaN)).toBeLessThan(0);
      expect(compareTimelineEvents(withNaN, withSeq)).toBeGreaterThan(0);
    });
  });

  describe('sortTimelineBySequence', () => {
    it('should sort timeline by sequence number in ascending order', () => {
      const timeline: TimelineEvent[] = [
        {
          id: 'c',
          type: 'thought',
          sequenceNumber: 3,
          timestamp: 3000,
          content: 'Third',
        },
        {
          id: 'a',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'First',
          role: 'user',
        },
        {
          id: 'b',
          type: 'assistant_message',
          sequenceNumber: 2,
          timestamp: 2000,
          content: 'Second',
          role: 'assistant',
        },
      ];

      const sorted = sortTimelineBySequence(timeline);

      expect(sorted[0].sequenceNumber).toBe(1);
      expect(sorted[1].sequenceNumber).toBe(2);
      expect(sorted[2].sequenceNumber).toBe(3);
      expect(sorted[0].id).toBe('a');
      expect(sorted[1].id).toBe('b');
      expect(sorted[2].id).toBe('c');
    });

    it('should place events with null/undefined sequence numbers at the end', () => {
      const timeline: TimelineEvent[] = [
        {
          id: 'null-seq',
          type: 'thought',
          sequenceNumber: null as any,
          timestamp: 500,
          content: 'Null sequence',
        },
        {
          id: 'valid-seq',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'Valid sequence',
          role: 'user',
        },
        {
          id: 'undefined-seq',
          type: 'thought',
          sequenceNumber: undefined as any,
          timestamp: 600,
          content: 'Undefined sequence',
        },
      ];

      const sorted = sortTimelineBySequence(timeline);

      expect(sorted[0].id).toBe('valid-seq');
      // The other two should be at the end, sorted by timestamp
      expect(sorted[1].id).toBe('null-seq');
      expect(sorted[2].id).toBe('undefined-seq');
    });

    it('should not mutate the original array', () => {
      const timeline: TimelineEvent[] = [
        {
          id: 'b',
          type: 'thought',
          sequenceNumber: 2,
          timestamp: 2000,
          content: 'Second',
        },
        {
          id: 'a',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'First',
          role: 'user',
        },
      ];

      const sorted = sortTimelineBySequence(timeline);

      // Original should remain unchanged
      expect(timeline[0].id).toBe('b');
      expect(timeline[1].id).toBe('a');

      // Sorted should be in correct order
      expect(sorted[0].id).toBe('a');
      expect(sorted[1].id).toBe('b');
    });

    it('should handle empty array', () => {
      const sorted = sortTimelineBySequence([]);
      expect(sorted).toEqual([]);
    });

    it('should handle single element', () => {
      const timeline: TimelineEvent[] = [
        {
          id: 'only',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'Only',
          role: 'user',
        },
      ];

      const sorted = sortTimelineBySequence(timeline);
      expect(sorted).toHaveLength(1);
      expect(sorted[0].id).toBe('only');
    });
  });

  describe('isTimelineSorted', () => {
    it('should return true for sorted timeline', () => {
      const timeline: TimelineEvent[] = [
        {
          id: 'a',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'A',
          role: 'user',
        },
        { id: 'b', type: 'thought', sequenceNumber: 2, timestamp: 2000, content: 'B' },
        {
          id: 'c',
          type: 'assistant_message',
          sequenceNumber: 3,
          timestamp: 3000,
          content: 'C',
          role: 'assistant',
        },
      ];

      expect(isTimelineSorted(timeline)).toBe(true);
    });

    it('should return false for unsorted timeline', () => {
      const timeline: TimelineEvent[] = [
        { id: 'b', type: 'thought', sequenceNumber: 2, timestamp: 2000, content: 'B' },
        {
          id: 'a',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'A',
          role: 'user',
        },
        {
          id: 'c',
          type: 'assistant_message',
          sequenceNumber: 3,
          timestamp: 3000,
          content: 'C',
          role: 'assistant',
        },
      ];

      expect(isTimelineSorted(timeline)).toBe(false);
    });

    it('should skip invalid sequence numbers during check', () => {
      const timeline: TimelineEvent[] = [
        {
          id: 'a',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'A',
          role: 'user',
        },
        { id: 'b', type: 'thought', sequenceNumber: null as any, timestamp: 2000, content: 'B' },
        {
          id: 'c',
          type: 'assistant_message',
          sequenceNumber: 3,
          timestamp: 3000,
          content: 'C',
          role: 'assistant',
        },
      ];

      expect(isTimelineSorted(timeline)).toBe(true);
    });

    it('should return true for empty array', () => {
      expect(isTimelineSorted([])).toBe(true);
    });

    it('should return true for single element', () => {
      const timeline: TimelineEvent[] = [
        {
          id: 'a',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'A',
          role: 'user',
        },
      ];
      expect(isTimelineSorted(timeline)).toBe(true);
    });
  });

  describe('getNextSequenceNumber', () => {
    it('should return 1 for empty timeline', () => {
      expect(getNextSequenceNumber([])).toBe(1);
    });

    it('should return next number for sorted timeline', () => {
      const timeline: TimelineEvent[] = [
        {
          id: 'a',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'A',
          role: 'user',
        },
        { id: 'b', type: 'thought', sequenceNumber: 2, timestamp: 2000, content: 'B' },
      ];

      expect(getNextSequenceNumber(timeline)).toBe(3);
    });

    it('should handle timeline with gaps', () => {
      const timeline: TimelineEvent[] = [
        {
          id: 'a',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'A',
          role: 'user',
        },
        { id: 'b', type: 'thought', sequenceNumber: 5, timestamp: 2000, content: 'B' },
      ];

      expect(getNextSequenceNumber(timeline)).toBe(6);
    });

    it('should handle timeline with invalid sequence numbers', () => {
      const timeline: TimelineEvent[] = [
        {
          id: 'a',
          type: 'user_message',
          sequenceNumber: null as any,
          timestamp: 1000,
          content: 'A',
          role: 'user',
        },
        { id: 'b', type: 'thought', sequenceNumber: 2, timestamp: 2000, content: 'B' },
      ];

      expect(getNextSequenceNumber(timeline)).toBe(3);
    });
  });

  describe('mergeTimelines', () => {
    it('should merge and sort two timelines', () => {
      const primary: TimelineEvent[] = [
        { id: 'b', type: 'thought', sequenceNumber: 2, timestamp: 2000, content: 'B' },
      ];
      const secondary: TimelineEvent[] = [
        {
          id: 'a',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'A',
          role: 'user',
        },
      ];

      const merged = mergeTimelines(primary, secondary);

      expect(merged).toHaveLength(2);
      expect(merged[0].sequenceNumber).toBe(1);
      expect(merged[1].sequenceNumber).toBe(2);
    });

    it('should deduplicate events by id', () => {
      const primary: TimelineEvent[] = [
        {
          id: 'a',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'A',
          role: 'user',
        },
      ];
      const secondary: TimelineEvent[] = [
        {
          id: 'a',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'A',
          role: 'user',
        },
        { id: 'b', type: 'thought', sequenceNumber: 2, timestamp: 2000, content: 'B' },
      ];

      const merged = mergeTimelines(primary, secondary);

      expect(merged).toHaveLength(2);
      expect(merged[0].id).toBe('a');
      expect(merged[1].id).toBe('b');
    });

    it('should prefer primary timeline for duplicates', () => {
      const primary: TimelineEvent[] = [
        {
          id: 'a',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'From Primary',
          role: 'user',
        },
      ];
      const secondary: TimelineEvent[] = [
        {
          id: 'a',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'From Secondary',
          role: 'user',
        },
      ];

      const merged = mergeTimelines(primary, secondary);

      expect(merged).toHaveLength(1);
      expect(merged[0].content).toBe('From Primary');
    });

    it('should handle empty primary', () => {
      const secondary: TimelineEvent[] = [
        {
          id: 'a',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'A',
          role: 'user',
        },
      ];

      const merged = mergeTimelines([], secondary);

      expect(merged).toHaveLength(1);
      expect(merged[0].id).toBe('a');
    });

    it('should handle empty secondary', () => {
      const primary: TimelineEvent[] = [
        {
          id: 'a',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'A',
          role: 'user',
        },
      ];

      const merged = mergeTimelines(primary, []);

      expect(merged).toHaveLength(1);
      expect(merged[0].id).toBe('a');
    });
  });
});
