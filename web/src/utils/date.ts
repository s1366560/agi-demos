/**
 * Unified date utility functions
 *
 * All formatting functions output in the user's local timezone.
 * Backend sends ISO 8601 UTC strings; `new Date()` auto-converts to local TZ.
 *
 * Format convention: ISO style (YYYY-MM-DD HH:mm)
 */

import i18n from '@/i18n/config';

import { formatTimeOnly, pad, toDate, formatDateOnly, type DateInput } from '../../../sdk/memstack-plugin-sdk/ui/localDate';
export { formatDateTime, formatDateTimeFull, formatDateOnly } from '../../../sdk/memstack-plugin-sdk/ui/localDate';

/**
 * Format as "HH:mm" in local timezone.
 * For time-only displays.
 */
export { formatTimeOnly } from '../../../sdk/memstack-plugin-sdk/ui/localDate';

/**
 * Format as "HH:mm:ss" in local timezone.
 * For precise time displays.
 */
export function formatTimeWithSeconds(input: DateInput): string {
  const d = toDate(input);
  if (!d) return '';
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/**
 * Format duration from milliseconds to human readable string.
 * Unified utility for all timeline components.
 *
 * @param ms - Duration in milliseconds
 * @returns Formatted string like "500ms", "1.5s", "2m 30s"
 */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${String(Math.round(ms))}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.round((ms % 60000) / 1000);
  return seconds > 0 ? `${String(minutes)}m ${String(seconds)}s` : `${String(minutes)}m`;
}

/**
 * Format duration from milliseconds to human readable string (verbose).
 * Used for detailed execution logs.
 *
 * @param ms - Duration in milliseconds
 * @returns Formatted string like "500ms", "1.50s", "2m 30s"
 */
export function formatDurationVerbose(ms: number): string {
  if (ms < 1000) return `${String(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

/** @deprecated Use formatTimeOnly */
export function formatTime(date: Date): string {
  return formatTimeOnly(date);
}

/** @deprecated Use formatTimeOnly */
export function formatReadableTime(timestamp: number): string {
  return formatTimeOnly(timestamp);
}

/**
 * Locale-aware relative time.
 *
 * Buckets:
 *   < 60s  -> "just now"
 *   < 60m  -> "{n}m ago"
 *   < 24h  -> "{n}h ago"
 *   = 1d   -> "yesterday"
 *   < 7d   -> "{n}d ago"
 *   < 30d  -> "{n}w ago"
 *   else   -> absolute date
 *
 * Output language follows `i18next` so it switches with the user's locale.
 */
export function formatDistanceToNow(input: DateInput): string {
  const date = toDate(input);
  if (!date) return '';
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSecs < 60) {
    return i18n.t('common.time.justNow');
  }
  if (diffMins < 60) {
    return i18n.t('common.time.minutesAgo', { count: diffMins });
  }
  if (diffHours < 24) {
    return i18n.t('common.time.hoursAgo', { count: diffHours });
  }
  if (diffDays === 1) {
    return i18n.t('common.time.yesterday');
  }
  if (diffDays < 7) {
    return i18n.t('common.time.daysAgo', { count: diffDays });
  }
  if (diffDays < 30) {
    return i18n.t('common.time.weeksAgo', { count: Math.floor(diffDays / 7) });
  }
  return formatDateOnly(date);
}

/**
 * @deprecated Use {@link formatDistanceToNow}; it now follows the active i18n
 * locale automatically and produces the same Chinese output when zh-CN is
 * active.
 */
export function formatDistanceToNowCN(input: DateInput): string {
  return formatDistanceToNow(input);
}
