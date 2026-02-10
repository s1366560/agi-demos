/**
 * Unit tests for useDateFormatter hook.
 *
 * Verifies that the hook delegates to unified utils/date.ts functions
 * and returns stable references across re-renders.
 */

import { renderHook } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { useDateFormatter } from '../../hooks/useDateFormatter';

describe('useDateFormatter', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Formatter Creation and Memoization', () => {
    it('should create formatter on first render', () => {
      const { result } = renderHook(() => useDateFormatter());

      expect(result.current).toBeDefined();
      expect(typeof result.current.formatDate).toBe('function');
      expect(typeof result.current.formatTime).toBe('function');
      expect(typeof result.current.formatDateTime).toBe('function');
      expect(typeof result.current.formatRelative).toBe('function');
    });

    it('should memoize formatter across re-renders', () => {
      const { result, rerender } = renderHook(() => useDateFormatter());

      const firstFormatter = result.current;
      const firstFormatFn = result.current.formatDate;

      rerender();

      const secondFormatter = result.current;
      const secondFormatFn = result.current.formatDate;

      expect(secondFormatter).toBe(firstFormatter);
      expect(secondFormatFn).toBe(firstFormatFn);
    });

    it('should return stable function references across re-renders', () => {
      const { result, rerender } = renderHook(() => useDateFormatter());

      const formatDate1 = result.current.formatDate;
      const formatTime1 = result.current.formatTime;
      const formatDateTime1 = result.current.formatDateTime;

      rerender();

      const formatDate2 = result.current.formatDate;
      const formatTime2 = result.current.formatTime;
      const formatDateTime2 = result.current.formatDateTime;

      expect(formatDate2).toBe(formatDate1);
      expect(formatTime2).toBe(formatTime1);
      expect(formatDateTime2).toBe(formatDateTime1);
    });

    it('should accept locale param for backward compatibility', () => {
      const { result } = renderHook(() => useDateFormatter('zh-CN'));
      expect(result.current).toBeDefined();
      expect(typeof result.current.formatDate).toBe('function');
    });
  });

  describe('Date Formatting (ISO style)', () => {
    it('should format date as YYYY-MM-DD', () => {
      const { result } = renderHook(() => useDateFormatter());
      const date = new Date('2024-01-15T10:30:00');

      const formatted = result.current.formatDate(date);

      expect(formatted).toBe('2024-01-15');
    });

    it('should format time as HH:mm', () => {
      const { result } = renderHook(() => useDateFormatter());
      const date = new Date('2024-01-15T10:30:00');

      const formatted = result.current.formatTime(date);

      expect(formatted).toBe('10:30');
    });

    it('should format date and time as YYYY-MM-DD HH:mm', () => {
      const { result } = renderHook(() => useDateFormatter());
      const date = new Date('2024-01-15T10:30:00');

      const formatted = result.current.formatDateTime(date);

      expect(formatted).toBe('2024-01-15 10:30');
    });

    it('should handle string date inputs', () => {
      const { result } = renderHook(() => useDateFormatter());

      const formatted = result.current.formatDate('2024-01-15T10:30:00');

      expect(formatted).toBe('2024-01-15');
    });

    it('should handle timestamp inputs', () => {
      const { result } = renderHook(() => useDateFormatter());
      const timestamp = new Date('2024-01-15T00:00:00').getTime();

      const formatted = result.current.formatDate(timestamp);

      expect(formatted).toBe('2024-01-15');
    });
  });

  describe('Relative Time Formatting', () => {
    it('should format relative time for just now', () => {
      const { result } = renderHook(() => useDateFormatter());
      const now = Date.now();

      const formatted = result.current.formatRelative(now - 1000);

      expect(formatted).toBe('just now');
    });

    it('should format relative time for minutes', () => {
      const { result } = renderHook(() => useDateFormatter());
      const now = Date.now();

      const formatted = result.current.formatRelative(now - 5 * 60 * 1000);

      expect(formatted).toBe('5m ago');
    });

    it('should format relative time for hours', () => {
      const { result } = renderHook(() => useDateFormatter());
      const now = Date.now();

      const formatted = result.current.formatRelative(now - 3 * 60 * 60 * 1000);

      expect(formatted).toBe('3h ago');
    });

    it('should format relative time for days', () => {
      const { result } = renderHook(() => useDateFormatter());
      const now = Date.now();

      const formatted = result.current.formatRelative(now - 5 * 24 * 60 * 60 * 1000);

      expect(formatted).toBe('5d ago');
    });

    it('should return absolute date for old dates', () => {
      const { result } = renderHook(() => useDateFormatter());
      const oldDate = new Date('2020-01-15').getTime();

      const formatted = result.current.formatRelative(oldDate);

      expect(formatted).toBe('2020-01-15');
    });
  });

  describe('Edge Cases', () => {
    it('should handle invalid date gracefully', () => {
      const { result } = renderHook(() => useDateFormatter());

      const formatted = result.current.formatDate('invalid-date');

      expect(formatted).toBe('');
    });

    it('should handle null date gracefully', () => {
      const { result } = renderHook(() => useDateFormatter());

      const formatted = result.current.formatDate(null);

      expect(formatted).toBe('');
    });

    it('should handle undefined date gracefully', () => {
      const { result } = renderHook(() => useDateFormatter());

      const formatted = result.current.formatDate(undefined);

      expect(formatted).toBe('');
    });
  });
});
