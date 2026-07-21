/**
 * useDateFormatter Hook
 *
 * React hook wrapper around unified date utility functions.
 * Delegates to `utils/date.ts` for consistent ISO-style formatting.
 *
 * @module hooks/useDateFormatter
 */

import { useMemo } from 'react';

import {
  formatDateOnly,
  formatTimeOnly,
  formatDateTime as utilFormatDateTime,
  formatDistanceToNow,
} from '@/utils/date';

/**
 * Result type for useDateFormatter hook
 */
export interface DateFormatterResult {
  /** Format as "YYYY-MM-DD" */
  formatDate: (date: Date | string | number | null | undefined) => string;
  /** Format as "HH:mm" */
  formatTime: (date: Date | string | number | null | undefined) => string;
  /** Format as "YYYY-MM-DD HH:mm" */
  formatDateTime: (date: Date | string | number | null | undefined) => string;
  /** Format as relative time (e.g., "5m ago", "2d ago") */
  formatRelative: (timestamp: number | string | Date) => string;
}

/**
 * Hook for date formatting using unified utility functions.
 *
 * @param _locale - Deprecated, ignored. Kept for backward compatibility.
 * @returns Object containing formatting functions
 *
 * @example
 * ```tsx
 * const { formatDate, formatRelative } = useDateFormatter()
 * const formatted = formatDate(new Date()) // "2024-01-15"
 * const relative = formatRelative(Date.now() - 3600000) // "1h ago"
 * ```
 */
export function useDateFormatter(_locale?: string): DateFormatterResult {
  return useMemo(
    () => ({
      formatDate: formatDateOnly,
      formatTime: formatTimeOnly,
      formatDateTime: utilFormatDateTime,
      formatRelative: (timestamp: number | string | Date) => formatDistanceToNow(timestamp),
    }),
    []
  );
}

/**
 * Utility function to format storage size in human-readable format
 * Moved outside component to avoid recreation on each render
 *
 * @param bytes - Size in bytes
 * @returns Formatted string (e.g., "5 GB", "1.5 GB", "150 MB", "800 KB", "512 B")
 */
export function formatStorage(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const unitIndex = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1);
  const sizeLabel = sizes[unitIndex] ?? 'TB';
  const value = Number.parseFloat((bytes / Math.pow(k, unitIndex)).toFixed(1));
  return `${String(value)} ${sizeLabel}`;
}
