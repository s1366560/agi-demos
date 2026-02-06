/**
 * Unit tests for useDateFormatter hook.
 *
 * TDD Phase 1 (RED): Tests written before implementation.
 *
 * These tests verify that:
 * 1. Formatter is created once on first render
 * 2. Formatter is memoized across renders with same locale
 * 3. Formatter is recreated when locale changes
 * 4. formatDate uses cached formatter
 * 5. Hook handles locale changes correctly
 * 6. Performance: formatter instance is stable
 */

import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { useDateFormatter } from '../../hooks/useDateFormatter';

describe('useDateFormatter', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Formatter Creation and Memoization', () => {
    it('should create formatter on first render', () => {
      const { result } = renderHook(() => useDateFormatter('en-US'));

      expect(result.current).toBeDefined();
      expect(typeof result.current.formatDate).toBe('function');
      expect(typeof result.current.formatTime).toBe('function');
      expect(typeof result.current.formatDateTime).toBe('function');
    });

    it('should memoize formatter across re-renders with same locale', () => {
      const { result, rerender } = renderHook((locale: string) => useDateFormatter(locale), {
        initialProps: 'en-US',
      });

      const firstFormatter = result.current;
      const firstFormatFn = result.current.formatDate;

      // Rerender with same locale
      rerender('en-US');

      const secondFormatter = result.current;
      const secondFormatFn = result.current.formatDate;

      // Formatter object should be the same (reference equality)
      expect(secondFormatter).toBe(firstFormatter);
      expect(secondFormatFn).toBe(firstFormatFn);
    });

    it('should create new formatter when locale changes', () => {
      const { result, rerender } = renderHook((locale: string) => useDateFormatter(locale), {
        initialProps: 'en-US',
      });

      const firstFormatter = result.current;
      const firstResult = firstFormatter.formatDate(new Date('2024-01-15'));

      // Change locale
      rerender('zh-CN');

      const secondFormatter = result.current;
      const secondResult = secondFormatter.formatDate(new Date('2024-01-15'));

      // Formatter should be different
      expect(secondFormatter).not.toBe(firstFormatter);

      // Format results should differ based on locale
      expect(firstResult).toBeDefined();
      expect(secondResult).toBeDefined();
    });

    it('should return stable function references across re-renders', () => {
      const { result, rerender } = renderHook(() => useDateFormatter('en-US'));

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
  });

  describe('Date Formatting', () => {
    it('should format date correctly with en-US locale', () => {
      const { result } = renderHook(() => useDateFormatter('en-US'));
      const date = new Date('2024-01-15T10:30:00Z');

      const formatted = result.current.formatDate(date);

      expect(formatted).toContain('2024');
      expect(formatted).toMatch(/Jan|January/);
    });

    it('should format time correctly', () => {
      const { result } = renderHook(() => useDateFormatter('en-US'));
      const date = new Date('2024-01-15T10:30:00Z');

      const formatted = result.current.formatTime(date);

      expect(formatted).toBeDefined();
      expect(typeof formatted).toBe('string');
    });

    it('should format date and time together', () => {
      const { result } = renderHook(() => useDateFormatter('en-US'));
      const date = new Date('2024-01-15T10:30:00Z');

      const formatted = result.current.formatDateTime(date);

      expect(formatted).toBeDefined();
      expect(typeof formatted).toBe('string');
    });

    it('should handle string date inputs', () => {
      const { result } = renderHook(() => useDateFormatter('en-US'));

      const formatted = result.current.formatDate('2024-01-15T10:30:00Z');

      expect(formatted).toBeDefined();
      expect(typeof formatted).toBe('string');
    });

    it('should handle timestamp inputs', () => {
      const { result } = renderHook(() => useDateFormatter('en-US'));
      const timestamp = new Date('2024-01-15').getTime();

      const formatted = result.current.formatDate(timestamp);

      expect(formatted).toBeDefined();
      expect(typeof formatted).toBe('string');
    });
  });

  describe('Relative Time Formatting', () => {
    it('should format relative time for just now', () => {
      const { result } = renderHook(() => useDateFormatter('en-US'));
      const now = Date.now();

      const formatted = result.current.formatRelative(now - 1000); // 1 second ago

      expect(formatted).toContain('just now');
    });

    it('should format relative time for minutes', () => {
      const { result } = renderHook(() => useDateFormatter('en-US'));
      const now = Date.now();

      const formatted = result.current.formatRelative(now - 5 * 60 * 1000); // 5 minutes ago

      expect(formatted).toContain('5');
      expect(formatted).toMatch(/m|min|minute/);
    });

    it('should format relative time for hours', () => {
      const { result } = renderHook(() => useDateFormatter('en-US'));
      const now = Date.now();

      const formatted = result.current.formatRelative(now - 3 * 60 * 60 * 1000); // 3 hours ago

      expect(formatted).toContain('3');
      expect(formatted).toMatch(/h|hour/);
    });

    it('should format relative time for days', () => {
      const { result } = renderHook(() => useDateFormatter('en-US'));
      const now = Date.now();

      const formatted = result.current.formatRelative(now - 5 * 24 * 60 * 60 * 1000); // 5 days ago

      expect(formatted).toContain('5');
      expect(formatted).toMatch(/d|day/);
    });

    it('should return absolute date for old dates', () => {
      const { result } = renderHook(() => useDateFormatter('en-US'));
      const oldDate = new Date('2020-01-15').getTime();

      const formatted = result.current.formatRelative(oldDate);

      expect(formatted).toBeDefined();
      expect(typeof formatted).toBe('string');
    });
  });

  describe('Edge Cases', () => {
    it('should handle invalid date gracefully', () => {
      const { result } = renderHook(() => useDateFormatter('en-US'));

      const formatted = result.current.formatDate('invalid-date');

      expect(formatted).toBeDefined();
    });

    it('should handle null date gracefully', () => {
      const { result } = renderHook(() => useDateFormatter('en-US'));

      const formatted = result.current.formatDate(null as any);

      expect(formatted).toBeDefined();
    });

    it('should handle undefined date gracefully', () => {
      const { result } = renderHook(() => useDateFormatter('en-US'));

      const formatted = result.current.formatDate(undefined as any);

      expect(formatted).toBeDefined();
    });

    it('should default to en-US when no locale provided', () => {
      const { result } = renderHook(() => useDateFormatter());

      expect(result.current).toBeDefined();
      expect(typeof result.current.formatDate).toBe('function');
    });
  });

  describe('Performance', () => {
    it('should not create new Intl.DateTimeFormat on every call', () => {
      const spy = vi.spyOn(Intl, 'DateTimeFormat');

      const { result } = renderHook(() => useDateFormatter('en-US'));

      // First render creates formatter
      expect(spy).toHaveBeenCalledTimes(1);

      // Multiple format calls should not create new formatters
      result.current.formatDate(new Date());
      result.current.formatDate(new Date());
      result.current.formatDate(new Date());

      // Should still be called only once (from initial creation)
      expect(spy).toHaveBeenCalledTimes(1);

      spy.mockRestore();
    });

    it('should cache formatter instances for multiple locales', () => {
      const { result, rerender } = renderHook((locale: string) => useDateFormatter(locale), {
        initialProps: 'en-US',
      });

      const enUsFormatter = result.current;

      // Switch to zh-CN
      rerender('zh-CN');
      const zhCnFormatter = result.current;

      // Switch back to en-US - should reuse cached formatter
      rerender('en-US');
      const enUsFormatterAgain = result.current;

      expect(enUsFormatterAgain).toBe(enUsFormatter);
      expect(zhCnFormatter).not.toBe(enUsFormatter);
    });
  });
});
