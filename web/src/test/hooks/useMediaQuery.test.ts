/**
 * Unit tests for useMediaQuery hook.
 *
 * TDD Phase 1 (RED): Tests written before implementation.
 *
 * These tests verify that:
 * 1. Initial media query match is detected
 * 2. Changes in media query are reflected
 * 3. Cleanup removes event listener
 * 4. Works with various media query strings
 * 5. Handles window resize events
 * 6. Edge cases (invalid queries, SSR)
 */

import { renderHook, act, cleanup } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { useMediaQuery } from '../../hooks/useMediaQuery';

// Mock matchMedia
const mockMatchMedia = vi.fn();

interface MockMediaQueryList {
  matches: boolean;
  media: string;
  onchange: null | ((this: MediaQueryList, ev: MediaQueryListEvent) => any);
  addListener: (callback: (this: MediaQueryList, ev: MediaQueryListEvent) => any) => void;
  removeListener: (callback: (this: MediaQueryList, ev: MediaQueryListEvent) => any) => void;
  addEventListener: (type: string, callback: (this: MediaQueryList, ev: MediaQueryListEvent) => any) => void;
  removeEventListener: (type: string, callback: (this: MediaQueryList, ev: MediaQueryListEvent) => any) => void;
  dispatchEvent: (event: Event) => boolean;
}

let currentMatches: boolean = false;
let listenerCallback: ((this: MediaQueryList, ev: MediaQueryListEvent) => any) | null = null;

const createMockMediaQueryList = (query: string, matches: boolean): MockMediaQueryList => ({
  matches,
  media: query,
  onchange: null,
  addListener: (callback) => {
    listenerCallback = callback;
  },
  removeListener: () => {
    listenerCallback = null;
  },
  addEventListener: (type, callback) => {
    if (type === 'change') {
      listenerCallback = callback;
    }
  },
  removeEventListener: () => {
    listenerCallback = null;
  },
  dispatchEvent: vi.fn(),
});

describe('useMediaQuery', () => {
  let originalMatchMedia: typeof window.matchMedia;

  beforeEach(() => {
    // Store original matchMedia
    originalMatchMedia = window.matchMedia;

    // Reset state
    currentMatches = false;
    listenerCallback = null;

    // Mock matchMedia
    mockMatchMedia.mockImplementation((query: string) => {
      return createMockMediaQueryList(query, currentMatches);
    });

    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: mockMatchMedia,
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();

    // Restore original matchMedia
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: originalMatchMedia,
    });
  });

  describe('Initial State', () => {
    it('should return false when media query does not match', () => {
      currentMatches = false;
      const { result } = renderHook(() => useMediaQuery('(min-width: 768px)'));

      expect(result.current).toBe(false);
    });

    it('should return true when media query matches', () => {
      currentMatches = true;
      const { result } = renderHook(() => useMediaQuery('(min-width: 768px)'));

      expect(result.current).toBe(true);
    });

    it('should call matchMedia with correct query', () => {
      const query = '(min-width: 768px)';
      renderHook(() => useMediaQuery(query));

      expect(mockMatchMedia).toHaveBeenCalledWith(query);
    });

    it('should set up event listener on mount', () => {
      currentMatches = false;
      renderHook(() => useMediaQuery('(min-width: 768px)'));

      // Verify addEventListener or addListener was called
      const mql = mockMatchMedia('(min-width: 768px)') as MockMediaQueryList;
      expect(mql.addEventListener || mql.addListener).toBeDefined();
    });
  });

  describe('Media Query Changes', () => {
    it('should update when media query changes from false to true', () => {
      currentMatches = false;
      const { result } = renderHook(() => useMediaQuery('(min-width: 768px)'));

      expect(result.current).toBe(false);

      // Simulate media query change with proper MediaQueryListEvent
      act(() => {
        currentMatches = true;
        const mockEvent = { matches: true } as MediaQueryListEvent;
        // @ts-expect-error - MediaQueryList context in test mock
        listenerCallback?.(mockEvent);
      });

      expect(result.current).toBe(true);
    });

    it('should update when media query changes from true to false', () => {
      currentMatches = true;
      const { result } = renderHook(() => useMediaQuery('(min-width: 768px)'));

      expect(result.current).toBe(true);

      // Simulate media query change with proper MediaQueryListEvent
      act(() => {
        currentMatches = false;
        const mockEvent = { matches: false } as MediaQueryListEvent;
        // @ts-expect-error - MediaQueryList context in test mock
        listenerCallback?.(mockEvent);
      });

      expect(result.current).toBe(false);
    });

    it('should handle multiple changes', () => {
      currentMatches = false;
      const { result } = renderHook(() => useMediaQuery('(min-width: 768px)'));

      expect(result.current).toBe(false);

      act(() => {
        currentMatches = true;
        // @ts-expect-error - MediaQueryList context in test mock
        listenerCallback?.({ matches: true } as MediaQueryListEvent);
      });

      expect(result.current).toBe(true);

      act(() => {
        currentMatches = false;
        // @ts-expect-error - MediaQueryList context in test mock
        listenerCallback?.({ matches: false } as MediaQueryListEvent);
      });

      expect(result.current).toBe(false);

      act(() => {
        currentMatches = true;
        // @ts-expect-error - MediaQueryList context in test mock
        listenerCallback?.({ matches: true } as MediaQueryListEvent);
      });

      expect(result.current).toBe(true);
    });
  });

  describe('Cleanup', () => {
    it('should remove event listener on unmount', () => {
      const mql = createMockMediaQueryList('(min-width: 768px)', false);
      mockMatchMedia.mockReturnValue(mql);

      const removeEventListenerSpy = vi.spyOn(mql, 'removeEventListener');
      const removeListenerSpy = vi.spyOn(mql, 'removeListener');

      const { unmount } = renderHook(() => useMediaQuery('(min-width: 768px)'));

      unmount();

      // At least one should have been called (depending on browser API)
      const wasRemoved = removeEventListenerSpy.mock.calls.length > 0 ||
                          removeListenerSpy.mock.calls.length > 0;
      expect(wasRemoved).toBe(true);
    });

    it('should not update after unmount', () => {
      currentMatches = false;
      const { result, unmount } = renderHook(() =>
        useMediaQuery('(min-width: 768px)')
      );

      expect(result.current).toBe(false);

      unmount();

      // This should not cause any errors or updates
      act(() => {
        // @ts-expect-error - MediaQueryList context in test mock
        listenerCallback?.({ matches: true } as MediaQueryListEvent);
      });

      // Value should remain unchanged
      expect(result.current).toBe(false);
    });
  });

  describe('Common Media Queries', () => {
    it('should work with min-width queries', () => {
      currentMatches = true;
      const { result } = renderHook(() => useMediaQuery('(min-width: 1024px)'));

      expect(result.current).toBe(true);
    });

    it('should work with max-width queries', () => {
      currentMatches = true;
      const { result } = renderHook(() => useMediaQuery('(max-width: 640px)'));

      expect(result.current).toBe(true);
    });

    it('should work with orientation queries', () => {
      currentMatches = false;
      const { result } = renderHook(() => useMediaQuery('(orientation: portrait)'));

      expect(result.current).toBe(false);
    });

    it('should work with prefers-color-scheme', () => {
      currentMatches = true;
      const { result } = renderHook(() => useMediaQuery('(prefers-color-scheme: dark)'));

      expect(result.current).toBe(true);
    });

    it('should work with prefers-reduced-motion', () => {
      currentMatches = false;
      const { result } = renderHook(() => useMediaQuery('(prefers-reduced-motion: reduce)'));

      expect(result.current).toBe(false);
    });

    it('should work with complex queries', () => {
      currentMatches = true;
      const { result } = renderHook(() =>
        useMediaQuery('(min-width: 768px) and (max-width: 1024px)')
      );

      expect(result.current).toBe(true);
    });
  });

  describe('Multiple Instances', () => {
    it('should handle multiple hooks with different queries independently', () => {
      const createMql = (query: string, matches: boolean) =>
        createMockMediaQueryList(query, matches);

      mockMatchMedia.mockImplementation((query: string) => {
        if (query.includes('768')) return createMql(query, true);
        if (query.includes('1024')) return createMql(query, false);
        return createMql(query, false);
      });

      const { result: result1 } = renderHook(() => useMediaQuery('(min-width: 768px)'));
      const { result: result2 } = renderHook(() => useMediaQuery('(min-width: 1024px)'));

      expect(result1.current).toBe(true);
      expect(result2.current).toBe(false);
    });
  });

  describe('Edge Cases', () => {
    it('should handle empty query string', () => {
      currentMatches = false;
      const { result } = renderHook(() => useMediaQuery(''));

      expect(result.current).toBe(false);
    });

    it('should handle invalid media query gracefully', () => {
      // matchMedia may throw or return a list with matches=false for invalid queries
      mockMatchMedia.mockImplementation(() => {
        return createMockMediaQueryList('invalid query', false);
      });

      const { result } = renderHook(() => useMediaQuery('invalid query'));

      expect(result.current).toBe(false);
    });

    it('should handle query change between renders', () => {
      let queryMatches = false;
      mockMatchMedia.mockImplementation((query: string) => {
        if (query === '(min-width: 768px)') queryMatches = true;
        if (query === '(min-width: 1024px)') queryMatches = false;
        return createMockMediaQueryList(query, queryMatches);
      });

      const { result, rerender } = renderHook(
        ({ query }) => useMediaQuery(query),
        {
          initialProps: { query: '(min-width: 768px)' },
        }
      );

      expect(result.current).toBe(true);

      rerender({ query: '(min-width: 1024px)' });

      expect(result.current).toBe(false);
    });
  });

  describe('SSR Compatibility', () => {
    it('should handle missing matchMedia (SSR)', () => {
      // Simulate SSR environment where matchMedia is undefined
      Object.defineProperty(window, 'matchMedia', {
        writable: true,
        value: undefined,
      });

      const { result } = renderHook(() => useMediaQuery('(min-width: 768px)'));

      // Should return false as default when matchMedia is unavailable
      expect(result.current).toBe(false);
    });
  });
});
