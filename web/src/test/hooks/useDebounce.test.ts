/**
 * Unit tests for useDebounce hook.
 *
 * TDD Phase 1 (RED): Tests written before implementation.
 *
 * These tests verify that:
 * 1. Debounced value updates after delay
 * 2. Debounced value does not update immediately
 * 3. Delay value is respected
 * 4. Debounce works with rapid value changes
 * 5. Cleanup on unmount works correctly
 * 6. Edge cases (zero delay, negative delay, very long delay)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useDebounce } from '../../hooks/useDebounce';

describe('useDebounce', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  describe('Basic Debouncing', () => {
    it('should return initial value immediately', () => {
      const { result } = renderHook(() => useDebounce('initial', 500));

      expect(result.current).toBe('initial');
    });

    it('should update debounced value after delay', async () => {
      const { result, rerender } = renderHook(
        ({ value, delay }) => useDebounce(value, delay),
        {
          initialProps: { value: 'initial', delay: 500 },
        }
      );

      expect(result.current).toBe('initial');

      // Change the value
      rerender({ value: 'updated', delay: 500 });

      // Value should still be initial before delay
      expect(result.current).toBe('initial');

      // Fast-forward past the delay
      await act(async () => {
        vi.advanceTimersByTime(500);
      });

      // Value should now be updated
      expect(result.current).toBe('updated');
    });

    it('should not update before the delay has passed', () => {
      const { result, rerender } = renderHook(
        ({ value, delay }) => useDebounce(value, delay),
        {
          initialProps: { value: 'initial', delay: 500 },
        }
      );

      act(() => {
        rerender({ value: 'updated', delay: 500 });
        // Fast-forward just before the delay
        vi.advanceTimersByTime(499);
      });

      expect(result.current).toBe('initial');
    });

    it('should reset timer on rapid value changes', () => {
      const { result, rerender } = renderHook(
        ({ value, delay }) => useDebounce(value, delay),
        {
          initialProps: { value: 'v1', delay: 500 },
        }
      );

      // Change value multiple times rapidly
      rerender({ value: 'v2', delay: 500 });
      act(() => {
        vi.advanceTimersByTime(300);
      });
      expect(result.current).toBe('v1');

      rerender({ value: 'v3', delay: 500 });
      act(() => {
        vi.advanceTimersByTime(300);
      });
      expect(result.current).toBe('v1');

      rerender({ value: 'v4', delay: 500 });
      act(() => {
        vi.advanceTimersByTime(300);
      });
      expect(result.current).toBe('v1');

      // Finally advance past the full delay
      act(() => {
        vi.advanceTimersByTime(200);
      });

      expect(result.current).toBe('v4');
    });
  });

  describe('Delay Configuration', () => {
    it('should respect custom delay value', () => {
      const { result, rerender } = renderHook(
        ({ value, delay }) => useDebounce(value, delay),
        {
          initialProps: { value: 'initial', delay: 1000 },
        }
      );

      rerender({ value: 'updated', delay: 1000 });

      act(() => {
        vi.advanceTimersByTime(999);
      });

      expect(result.current).toBe('initial');

      act(() => {
        vi.advanceTimersByTime(1);
      });

      expect(result.current).toBe('updated');
    });

    it('should handle zero delay (immediate update)', () => {
      const { result, rerender } = renderHook(
        ({ value, delay }) => useDebounce(value, delay),
        {
          initialProps: { value: 'initial', delay: 0 },
        }
      );

      rerender({ value: 'updated', delay: 0 });

      // With zero delay, should update immediately (or in next microtask)
      act(() => {
        vi.advanceTimersByTime(0);
      });

      expect(result.current).toBe('updated');
    });

    it('should handle delay change between renders', () => {
      const { result, rerender } = renderHook(
        ({ value, delay }) => useDebounce(value, delay),
        {
          initialProps: { value: 'initial', delay: 500 },
        }
      );

      rerender({ value: 'updated', delay: 200 });

      act(() => {
        vi.advanceTimersByTime(200);
      });

      expect(result.current).toBe('updated');
    });
  });

  describe('Type Support', () => {
    it('should work with string values', () => {
      const { result, rerender } = renderHook(
        ({ value, delay }) => useDebounce(value, delay),
        {
          initialProps: { value: 'hello', delay: 100 },
        }
      );

      rerender({ value: 'world', delay: 100 });

      act(() => {
        vi.advanceTimersByTime(100);
      });

      expect(result.current).toBe('world');
    });

    it('should work with number values', () => {
      const { result, rerender } = renderHook(
        ({ value, delay }) => useDebounce(value, delay),
        {
          initialProps: { value: 42, delay: 100 },
        }
      );

      rerender({ value: 100, delay: 100 });

      act(() => {
        vi.advanceTimersByTime(100);
      });

      expect(result.current).toBe(100);
    });

    it('should work with boolean values', () => {
      const { result, rerender } = renderHook(
        ({ value, delay }) => useDebounce(value, delay),
        {
          initialProps: { value: false, delay: 100 },
        }
      );

      rerender({ value: true, delay: 100 });

      act(() => {
        vi.advanceTimersByTime(100);
      });

      expect(result.current).toBe(true);
    });

    it('should work with object values', () => {
      const initialObj = { name: 'Alice', age: 30 };
      const updatedObj = { name: 'Bob', age: 25 };

      const { result, rerender } = renderHook(
        ({ value, delay }) => useDebounce(value, delay),
        {
          initialProps: { value: initialObj, delay: 100 },
        }
      );

      rerender({ value: updatedObj, delay: 100 });

      act(() => {
        vi.advanceTimersByTime(100);
      });

      expect(result.current).toEqual(updatedObj);
    });

    it('should work with array values', () => {
      const { result, rerender } = renderHook(
        ({ value, delay }) => useDebounce(value, delay),
        {
          initialProps: { value: [1, 2, 3], delay: 100 },
        }
      );

      rerender({ value: [4, 5, 6], delay: 100 });

      act(() => {
        vi.advanceTimersByTime(100);
      });

      expect(result.current).toEqual([4, 5, 6]);
    });

    it('should work with null values', () => {
      const { result, rerender } = renderHook(
        ({ value, delay }) => useDebounce(value, delay),
        {
          initialProps: { value: null as string | null, delay: 100 },
        }
      );

      rerender({ value: 'not null', delay: 100 });

      act(() => {
        vi.advanceTimersByTime(100);
      });

      expect(result.current).toBe('not null');
    });

    it('should work with undefined values', () => {
      const { result, rerender } = renderHook(
        ({ value, delay }) => useDebounce(value, delay),
        {
          initialProps: { value: 'initial', delay: 100 },
        }
      );

      rerender({ value: undefined as string | undefined, delay: 100 });

      act(() => {
        vi.advanceTimersByTime(100);
      });

      expect(result.current).toBeUndefined();
    });
  });

  describe('Cleanup and Unmount', () => {
    it('should clear pending timer on unmount', () => {
      const { result, rerender, unmount } = renderHook(
        ({ value, delay }) => useDebounce(value, delay),
        {
          initialProps: { value: 'initial', delay: 500 },
        }
      );

      rerender({ value: 'updated', delay: 500 });

      // Unmount before timer completes
      act(() => {
        unmount();
      });

      // Should not throw any errors
      expect(result.current).toBe('initial');
    });

    it('should clear timer when delay changes', () => {
      const { result, rerender } = renderHook(
        ({ value, delay }) => useDebounce(value, delay),
        {
          initialProps: { value: 'initial', delay: 500 },
        }
      );

      rerender({ value: 'v1', delay: 500 });

      // Change delay before first timer completes
      rerender({ value: 'v1', delay: 1000 });

      act(() => {
        vi.advanceTimersByTime(500);
      });

      // Should still be initial because timer was reset
      expect(result.current).toBe('initial');

      act(() => {
        vi.advanceTimersByTime(500);
      });

      expect(result.current).toBe('v1');
    });
  });

  describe('Edge Cases', () => {
    it('should handle same value re-render', () => {
      const { result, rerender } = renderHook(
        ({ value, delay }) => useDebounce(value, delay),
        {
          initialProps: { value: 'same', delay: 100 },
        }
      );

      rerender({ value: 'same', delay: 100 });

      act(() => {
        vi.advanceTimersByTime(100);
      });

      expect(result.current).toBe('same');
    });

    it('should handle very long delay', () => {
      const { result, rerender } = renderHook(
        ({ value, delay }) => useDebounce(value, delay),
        {
          initialProps: { value: 'initial', delay: 100000 },
        }
      );

      rerender({ value: 'updated', delay: 100000 });

      act(() => {
        vi.advanceTimersByTime(100000);
      });

      expect(result.current).toBe('updated');
    });

    it('should handle NaN delay gracefully', () => {
      const { result, rerender } = renderHook(
        ({ value, delay }) => useDebounce(value, delay),
        {
          initialProps: { value: 'initial', delay: 500 },
        }
      );

      // NaN delay should still work (setTimeout treats NaN as 0)
      act(() => {
        rerender({ value: 'updated', delay: NaN });
      });

      // Should not crash - behavior is implementation dependent
      expect(result.current).toBe('initial');
    });

    it('should handle negative delay', () => {
      const { result, rerender } = renderHook(
        ({ value, delay }) => useDebounce(value, delay),
        {
          initialProps: { value: 'initial', delay: -100 },
        }
      );

      rerender({ value: 'updated', delay: -100 });

      // Negative delay - behavior implementation dependent
      // Should not crash
      act(() => {
        vi.advanceTimersByTime(0);
      });

      expect(result.current).toBeDefined();
    });
  });
});
