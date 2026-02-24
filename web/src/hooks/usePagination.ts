/**
 * usePagination Hook
 *
 * A custom hook that provides pagination logic including page navigation,
 * boundary checking, and index calculations for displaying a subset
 * of items.
 *
 * @example
 * const { currentPage, totalPages, startIndex, endIndex, goToPage, nextPage, prevPage, canGoNext, canGoPrev } =
 *   usePagination({
 *     totalItems: 100,
 *     itemsPerPage: 10,
 *     onPageChange: (page) => console.log('Page changed to', page),
 *   });
 */

import { useMemo, useState, useCallback, useEffect } from 'react';

export interface UsePaginationOptions {
  totalItems: number;
  itemsPerPage?: number | undefined;
  initialPage?: number | undefined;
  onPageChange?: ((page: number) => void) | undefined;
}

export interface UsePaginationReturn {
  currentPage: number;
  totalPages: number;
  startIndex: number;
  endIndex: number;
  goToPage: (page: number) => void;
  nextPage: () => void;
  prevPage: () => void;
  canGoNext: boolean;
  canGoPrev: boolean;
}

export function usePagination({
  totalItems,
  itemsPerPage = 10,
  initialPage = 1,
  onPageChange,
}: UsePaginationOptions): UsePaginationReturn {
  // Calculate total pages
  const totalPages = useMemo(() => {
    return Math.max(1, Math.ceil(totalItems / itemsPerPage));
  }, [totalItems, itemsPerPage]);

  // Clamp initial page to valid range
  const clampedInitialPage = Math.max(1, Math.min(initialPage, totalPages));

  const [currentPage, setCurrentPage] = useState(clampedInitialPage);

  // Reset to page 1 when itemsPerPage or totalItems changes significantly
  useEffect(() => {
    const newTotalPages = Math.max(1, Math.ceil(totalItems / itemsPerPage));
    if (currentPage > newTotalPages) {
      // Queue state update to avoid synchronous setState in effect
      setTimeout(() => {
        setCurrentPage(newTotalPages);
        onPageChange?.(newTotalPages);
      }, 0);
    }
  }, [totalItems, itemsPerPage, currentPage, onPageChange]);

  // Calculate start and end indices (0-based)
  const startIndex = useMemo(() => {
    return (currentPage - 1) * itemsPerPage;
  }, [currentPage, itemsPerPage]);

  const endIndex = useMemo(() => {
    const end = startIndex + itemsPerPage - 1;
    return Math.min(end, totalItems - 1);
  }, [startIndex, itemsPerPage, totalItems]);

  // Navigation state flags
  const canGoNext = currentPage < totalPages;
  const canGoPrev = currentPage > 1;

  // Navigation handlers
  const goToPage = useCallback(
    (page: number) => {
      const newPage = Math.max(1, Math.min(page, totalPages));
      if (newPage !== currentPage) {
        setCurrentPage(newPage);
        onPageChange?.(newPage);
      } else {
        // Still call onPageChange even if same page
        onPageChange?.(newPage);
      }
    },
    [currentPage, totalPages, onPageChange]
  );

  const nextPage = useCallback(() => {
    if (canGoNext) {
      const newPage = currentPage + 1;
      setCurrentPage(newPage);
      onPageChange?.(newPage);
    }
  }, [currentPage, canGoNext, onPageChange]);

  const prevPage = useCallback(() => {
    if (canGoPrev) {
      const newPage = currentPage - 1;
      setCurrentPage(newPage);
      onPageChange?.(newPage);
    }
  }, [currentPage, canGoPrev, onPageChange]);

  return {
    currentPage,
    totalPages,
    startIndex,
    endIndex,
    goToPage,
    nextPage,
    prevPage,
    canGoNext,
    canGoPrev,
  };
}
