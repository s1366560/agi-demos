/**
 * Unit tests for usePagination hook.
 *
 * TDD Phase 1 (RED): Tests written before implementation.
 *
 * These tests verify that:
 * 1. Initial page is set correctly
 * 2. Total pages are calculated correctly
 * 3. Page navigation works (goToPage, nextPage, prevPage)
 * 4. Boundary conditions are respected (min/max pages)
 * 5. startIndex and endIndex are calculated correctly
 * 6. onPageChange callback is invoked
 * 7. Edge cases (zero items, single page, large data)
 */

import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { usePagination } from '../../hooks/usePagination';

describe('usePagination', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Initial State', () => {
    it('should start at initial page if provided', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
          initialPage: 3,
        })
      );

      expect(result.current.currentPage).toBe(3);
    });

    it('should start at page 1 if no initial page provided', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
        })
      );

      expect(result.current.currentPage).toBe(1);
    });

    it('should use itemsPerPage default of 10 if not provided', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
        })
      );

      expect(result.current.totalPages).toBe(10);
    });

    it('should calculate total pages correctly', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
        })
      );

      expect(result.current.totalPages).toBe(10);
    });

    it('should calculate total pages with remainder', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 105,
          itemsPerPage: 10,
        })
      );

      expect(result.current.totalPages).toBe(11);
    });

    it('should have at least 1 page even with zero items', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 0,
          itemsPerPage: 10,
        })
      );

      expect(result.current.totalPages).toBe(1);
    });

    it('should calculate startIndex correctly', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
          initialPage: 3,
        })
      );

      expect(result.current.startIndex).toBe(20);
    });

    it('should calculate endIndex correctly', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
          initialPage: 3,
        })
      );

      expect(result.current.endIndex).toBe(29);
    });

    it('should handle last page endIndex correctly', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 95,
          itemsPerPage: 10,
          initialPage: 10,
        })
      );

      expect(result.current.endIndex).toBe(94);
    });
  });

  describe('Page Navigation', () => {
    it('should navigate to specific page with goToPage', () => {
      const onPageChange = vi.fn();
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
          initialPage: 1,
          onPageChange,
        })
      );

      act(() => {
        result.current.goToPage(5);
      });

      expect(result.current.currentPage).toBe(5);
      expect(onPageChange).toHaveBeenCalledWith(5);
    });

    it('should go to next page with nextPage', () => {
      const onPageChange = vi.fn();
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
          initialPage: 1,
          onPageChange,
        })
      );

      act(() => {
        result.current.nextPage();
      });

      expect(result.current.currentPage).toBe(2);
      expect(onPageChange).toHaveBeenCalledWith(2);
    });

    it('should go to previous page with prevPage', () => {
      const onPageChange = vi.fn();
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
          initialPage: 5,
          onPageChange,
        })
      );

      act(() => {
        result.current.prevPage();
      });

      expect(result.current.currentPage).toBe(4);
      expect(onPageChange).toHaveBeenCalledWith(4);
    });

    it('should update startIndex after page change', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
          initialPage: 1,
        })
      );

      expect(result.current.startIndex).toBe(0);

      act(() => {
        result.current.goToPage(5);
      });

      expect(result.current.startIndex).toBe(40);
    });

    it('should update endIndex after page change', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
          initialPage: 1,
        })
      );

      expect(result.current.endIndex).toBe(9);

      act(() => {
        result.current.goToPage(5);
      });

      expect(result.current.endIndex).toBe(49);
    });
  });

  describe('Boundary Conditions', () => {
    it('should not go below page 1', () => {
      const onPageChange = vi.fn();
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
          initialPage: 1,
          onPageChange,
        })
      );

      act(() => {
        result.current.prevPage();
      });

      expect(result.current.currentPage).toBe(1);
      expect(onPageChange).not.toHaveBeenCalled();
    });

    it('should not go above total pages', () => {
      const onPageChange = vi.fn();
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
          initialPage: 10,
          onPageChange,
        })
      );

      act(() => {
        result.current.nextPage();
      });

      expect(result.current.currentPage).toBe(10);
      expect(onPageChange).not.toHaveBeenCalled();
    });

    it('should clamp goToPage to valid range', () => {
      const onPageChange = vi.fn();
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
          initialPage: 5,
          onPageChange,
        })
      );

      act(() => {
        result.current.goToPage(0);
      });

      expect(result.current.currentPage).toBe(1);

      act(() => {
        result.current.goToPage(100);
      });

      expect(result.current.currentPage).toBe(10);
    });

    it('should handle goToPage with same page', () => {
      const onPageChange = vi.fn();
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
          initialPage: 5,
          onPageChange,
        })
      );

      act(() => {
        result.current.goToPage(5);
      });

      expect(result.current.currentPage).toBe(5);
      expect(onPageChange).toHaveBeenCalledWith(5);
    });
  });

  describe('Navigation State Flags', () => {
    it('should return canGoNext as false on last page', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
          initialPage: 10,
        })
      );

      expect(result.current.canGoNext).toBe(false);
    });

    it('should return canGoNext as true when not on last page', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
          initialPage: 5,
        })
      );

      expect(result.current.canGoNext).toBe(true);
    });

    it('should return canGoPrev as false on first page', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
          initialPage: 1,
        })
      );

      expect(result.current.canGoPrev).toBe(false);
    });

    it('should return canGoPrev as true when not on first page', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
          initialPage: 5,
        })
      );

      expect(result.current.canGoPrev).toBe(true);
    });

    it('should update canGoNext after page change', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 50,
          itemsPerPage: 10,
          initialPage: 1,
        })
      );

      expect(result.current.canGoNext).toBe(true);

      act(() => {
        result.current.goToPage(5);
      });

      expect(result.current.canGoNext).toBe(false);
    });

    it('should update canGoPrev after page change', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 50,
          itemsPerPage: 10,
          initialPage: 5,
        })
      );

      expect(result.current.canGoPrev).toBe(true);

      act(() => {
        result.current.goToPage(1);
      });

      expect(result.current.canGoPrev).toBe(false);
    });
  });

  describe('Edge Cases', () => {
    it('should handle single page correctly', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 5,
          itemsPerPage: 10,
        })
      );

      expect(result.current.totalPages).toBe(1);
      expect(result.current.canGoNext).toBe(false);
      expect(result.current.canGoPrev).toBe(false);
    });

    it('should handle zero items', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 0,
          itemsPerPage: 10,
        })
      );

      expect(result.current.totalPages).toBe(1);
      expect(result.current.currentPage).toBe(1);
      expect(result.current.startIndex).toBe(0);
      expect(result.current.endIndex).toBe(-1);
    });

    it('should handle itemsPerPage of 1', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 5,
          itemsPerPage: 1,
          initialPage: 3,
        })
      );

      expect(result.current.totalPages).toBe(5);
      expect(result.current.startIndex).toBe(2);
      expect(result.current.endIndex).toBe(2);
    });

    it('should handle large itemsPerPage', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 10,
          itemsPerPage: 100,
        })
      );

      expect(result.current.totalPages).toBe(1);
      expect(result.current.startIndex).toBe(0);
      expect(result.current.endIndex).toBe(9);
    });

    it('should handle very large totalItems', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 1000000,
          itemsPerPage: 100,
          initialPage: 5000,
        })
      );

      expect(result.current.totalPages).toBe(10000);
      expect(result.current.currentPage).toBe(5000);
      expect(result.current.startIndex).toBe(499900);
      expect(result.current.endIndex).toBe(499999);
    });

    it('should handle decimal page size calculations', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 99,
          itemsPerPage: 10,
        })
      );

      expect(result.current.totalPages).toBe(10);
    });

    it('should handle itemsPerPage change', () => {
      const { result, rerender } = renderHook(
        ({ totalItems, itemsPerPage }) => usePagination({ totalItems, itemsPerPage }),
        {
          initialProps: { totalItems: 100, itemsPerPage: 10 },
        }
      );

      expect(result.current.totalPages).toBe(10);
      expect(result.current.currentPage).toBe(1);

      rerender({ totalItems: 100, itemsPerPage: 20 });

      expect(result.current.totalPages).toBe(5);
      // Current page should reset to 1 when itemsPerPage changes
      expect(result.current.currentPage).toBe(1);
    });

    it('should handle totalItems change', () => {
      const { result, rerender } = renderHook(
        ({ totalItems }) => usePagination({ totalItems, itemsPerPage: 10 }),
        {
          initialProps: { totalItems: 100 },
        }
      );

      expect(result.current.totalPages).toBe(10);

      rerender({ totalItems: 50 });

      expect(result.current.totalPages).toBe(5);
      // Current page should be clamped to new total
      expect(result.current.currentPage).toBe(1);
    });

    it('should handle totalItems decrease while on later page', () => {
      const { result, rerender } = renderHook(
        ({ totalItems }) => usePagination({ totalItems, itemsPerPage: 10, initialPage: 8 }),
        {
          initialProps: { totalItems: 100 },
        }
      );

      expect(result.current.currentPage).toBe(8);

      rerender({ totalItems: 25 });

      // Should clamp to last page
      expect(result.current.currentPage).toBe(3);
    });
  });

  describe('Callback Behavior', () => {
    it('should call onPageChange on goToPage', () => {
      const onPageChange = vi.fn();
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
          onPageChange,
        })
      );

      act(() => {
        result.current.goToPage(5);
      });

      expect(onPageChange).toHaveBeenCalledTimes(1);
      expect(onPageChange).toHaveBeenCalledWith(5);
    });

    it('should call onPageChange on nextPage', () => {
      const onPageChange = vi.fn();
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
          initialPage: 1,
          onPageChange,
        })
      );

      act(() => {
        result.current.nextPage();
      });

      expect(onPageChange).toHaveBeenCalledTimes(1);
      expect(onPageChange).toHaveBeenCalledWith(2);
    });

    it('should call onPageChange on prevPage', () => {
      const onPageChange = vi.fn();
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
          initialPage: 5,
          onPageChange,
        })
      );

      act(() => {
        result.current.prevPage();
      });

      expect(onPageChange).toHaveBeenCalledTimes(1);
      expect(onPageChange).toHaveBeenCalledWith(4);
    });

    it('should not call onPageChange when boundary is hit', () => {
      const onPageChange = vi.fn();
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
          initialPage: 1,
          onPageChange,
        })
      );

      act(() => {
        result.current.prevPage();
      });

      expect(onPageChange).not.toHaveBeenCalled();
    });

    it('should not call onPageChange when same page is selected', () => {
      const onPageChange = vi.fn();
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
          initialPage: 5,
          onPageChange,
        })
      );

      act(() => {
        result.current.goToPage(5);
      });

      // onPageChange IS called even for same page (design decision)
      expect(onPageChange).toHaveBeenCalledWith(5);
    });
  });

  describe('Index Calculations', () => {
    it('should calculate correct indices for all pages', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 100,
          itemsPerPage: 10,
        })
      );

      const pages: Array<{ page: number; start: number; end: number }> = [];

      // Use goToPage to navigate through pages instead of rerender with different initialPage
      for (let page = 1; page <= 10; page++) {
        act(() => {
          result.current.goToPage(page);
        });
        pages.push({
          page: result.current.currentPage,
          start: result.current.startIndex,
          end: result.current.endIndex,
        });
      }

      expect(pages).toEqual([
        { page: 1, start: 0, end: 9 },
        { page: 2, start: 10, end: 19 },
        { page: 3, start: 20, end: 29 },
        { page: 4, start: 30, end: 39 },
        { page: 5, start: 40, end: 49 },
        { page: 6, start: 50, end: 59 },
        { page: 7, start: 60, end: 69 },
        { page: 8, start: 70, end: 79 },
        { page: 9, start: 80, end: 89 },
        { page: 10, start: 90, end: 99 },
      ]);
    });

    it('should handle last page with incomplete items', () => {
      const { result } = renderHook(() =>
        usePagination({
          totalItems: 95,
          itemsPerPage: 10,
          initialPage: 10,
        })
      );

      expect(result.current.startIndex).toBe(90);
      expect(result.current.endIndex).toBe(94);
    });
  });
});
