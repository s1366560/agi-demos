/**
 * Unified date utility functions
 *
 * All formatting functions output in the user's local timezone.
 * Backend sends ISO 8601 UTC strings; `new Date()` auto-converts to local TZ.
 *
 * Format convention: ISO style (YYYY-MM-DD HH:mm)
 */

import i18n from '@/i18n/config';

import { formatRelativeTime, formatTimeOnly, pad, toDate, type DateInput } from '../../../sdk/memstack-plugin-sdk/ui/localDate';
export {
  formatDateTime,
  formatDateTimeFull,
  formatDateOnly,
  formatDuration,
  formatDurationVerbose,
} from '../../../sdk/memstack-plugin-sdk/ui/localDate';

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
  return formatRelativeTime(input, (key, options) => i18n.t(key, options ?? {}));
}

/**
 * @deprecated Use {@link formatDistanceToNow}; it now follows the active i18n
 * locale automatically and produces the same Chinese output when zh-CN is
 * active.
 */
export function formatDistanceToNowCN(input: DateInput): string {
  return formatDistanceToNow(input);
}
