/**
 * useDateFormatter Hook
 *
 * Memoized date formatting hook using Intl.DateTimeFormat for performance.
 * Caches formatter instances to avoid creating new Intl formatters on every render.
 *
 * @module hooks/useDateFormatter
 */

import { useMemo, useCallback } from 'react';

/**
 * Formatter cache to reuse Intl.DateTimeFormat instances
 * Key: locale string, Value: Intl.DateTimeFormat
 */
const formatterCache = new Map<string, Intl.DateTimeFormat>();

/**
 * Result type for useDateFormatter hook
 */
export interface DateFormatterResult {
  /** Format a date as a date string (e.g., "January 15, 2024") */
  formatDate: (date: Date | string | number | null | undefined) => string;
  /** Format a date as a time string (e.g., "10:30 AM") */
  formatTime: (date: Date | string | number | null | undefined) => string;
  /** Format a date as a date and time string (e.g., "January 15, 2024 at 10:30 AM") */
  formatDateTime: (date: Date | string | number | null | undefined) => string;
  /** Format a date as relative time (e.g., "5m ago", "2h ago", "3d ago") */
  formatRelative: (timestamp: number | string | Date) => string;
}

/**
 * Get or create a cached Intl.DateTimeFormat instance
 *
 * @param locale - The locale string (e.g., 'en-US', 'zh-CN')
 * @param options - Intl.DateTimeFormat options
 * @returns Cached Intl.DateTimeFormat instance
 */
function getCachedFormatter(
  locale: string,
  options: Intl.DateTimeFormatOptions
): Intl.DateTimeFormat {
  const cacheKey = `${locale}-${JSON.stringify(options)}`;

  if (!formatterCache.has(cacheKey)) {
    formatterCache.set(cacheKey, new Intl.DateTimeFormat(locale, options));
  }

  return formatterCache.get(cacheKey)!;
}

/**
 * Parse a date input into a Date object
 *
 * @param date - Date input (Date, string, number, null, undefined)
 * @returns Date object or undefined if invalid
 */
function parseDate(date: Date | string | number | null | undefined): Date | undefined {
  if (!date) return undefined;
  if (date instanceof Date) return date;
  return new Date(date);
}

/**
 * Hook for memoized date formatting with Intl.DateTimeFormat caching
 *
 * @param locale - The locale for formatting (default: 'en-US')
 * @returns Object containing formatting functions
 *
 * @example
 * ```tsx
 * const { formatDate, formatRelative } = useDateFormatter('en-US')
 * const formatted = formatDate(new Date()) // "January 15, 2024"
 * const relative = formatRelative(Date.now() - 3600000) // "1h ago"
 * ```
 */
export function useDateFormatter(locale: string = 'en-US'): DateFormatterResult {
  // Memoize formatter instances with stable options
  const dateFormatter = useMemo(
    () =>
      getCachedFormatter(locale, {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      }),
    [locale]
  );

  const timeFormatter = useMemo(
    () =>
      getCachedFormatter(locale, {
        hour: '2-digit',
        minute: '2-digit',
      }),
    [locale]
  );

  const dateTimeFormatter = useMemo(
    () =>
      getCachedFormatter(locale, {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      }),
    [locale]
  );

  // Memoize format functions to maintain stable references
  const formatDate = useCallback(
    (date: Date | string | number | null | undefined): string => {
      const parsed = parseDate(date);
      if (!parsed || isNaN(parsed.getTime())) {
        return '';
      }
      return dateFormatter.format(parsed);
    },
    [dateFormatter]
  );

  const formatTime = useCallback(
    (date: Date | string | number | null | undefined): string => {
      const parsed = parseDate(date);
      if (!parsed || isNaN(parsed.getTime())) {
        return '';
      }
      return timeFormatter.format(parsed);
    },
    [timeFormatter]
  );

  const formatDateTime = useCallback(
    (date: Date | string | number | null | undefined): string => {
      const parsed = parseDate(date);
      if (!parsed || isNaN(parsed.getTime())) {
        return '';
      }
      return dateTimeFormatter.format(parsed);
    },
    [dateTimeFormatter]
  );

  const formatRelative = useCallback(
    (timestamp: number | string | Date): string => {
      const date = typeof timestamp === 'object' ? timestamp : new Date(timestamp);
      const now = Date.now();
      const diffMs = now - date.getTime();
      const diffSecs = Math.floor(diffMs / 1000);
      const diffMins = Math.floor(diffSecs / 60);
      const diffHours = Math.floor(diffMins / 60);
      const diffDays = Math.floor(diffHours / 24);

      if (diffSecs < 60) {
        return 'just now';
      } else if (diffMins < 60) {
        return `${diffMins}m ago`;
      } else if (diffHours < 24) {
        return `${diffHours}h ago`;
      } else if (diffDays < 7) {
        return `${diffDays}d ago`;
      } else {
        // For older dates, return absolute date
        return formatDate(date);
      }
    },
    [formatDate]
  );

  // Memoize the entire result object to maintain stable reference
  return useMemo(
    () => ({
      formatDate,
      formatTime,
      formatDateTime,
      formatRelative,
    }),
    [formatDate, formatTime, formatDateTime, formatRelative]
  );
}

/**
 * Utility function to format storage size in human-readable format
 * Moved outside component to avoid recreation on each render
 *
 * @param bytes - Size in bytes
 * @returns Formatted string (e.g., "5.0 GB", "150 MB", "800 KB")
 */
export function formatStorage(bytes: number): string {
  const gb = bytes / (1024 * 1024 * 1024);
  if (gb >= 1) {
    return `${gb.toFixed(1)} GB`;
  }
  const mb = bytes / (1024 * 1024);
  if (mb >= 1) {
    return `${mb.toFixed(1)} MB`;
  }
  const kb = bytes / 1024;
  return `${kb.toFixed(1)} KB`;
}
