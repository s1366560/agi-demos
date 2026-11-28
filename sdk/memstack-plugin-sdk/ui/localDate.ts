export type DateInput = Date | string | number | null | undefined;

export function pad(n: number): string {
  return n < 10 ? `0${String(n)}` : String(n);
}

export function toDate(input: DateInput): Date | null {
  if (!input) return null;
  if (input instanceof Date) return isNaN(input.getTime()) ? null : input;
  if (typeof input === 'string') {
    // Backend sends naive ISO strings (no Z or offset) that are actually UTC.
    // Append 'Z' so JavaScript parses them as UTC instead of local time.
    const s = input.match(/^\d{4}-\d{2}-\d{2}T[\d:.]+$/) ? input + 'Z' : input;
    const d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
  }
  const d = new Date(input);
  return isNaN(d.getTime()) ? null : d;
}

/**
 * Format as "YYYY-MM-DD HH:mm" in local timezone.
 * Primary format for lists, tables, general display.
 */
export function formatDateTime(input: DateInput): string {
  const d = toDate(input);
  if (!d) return '';
  return `${String(d.getFullYear())}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/**
 * Format as "YYYY-MM-DD HH:mm:ss" in local timezone.
 * For detail views, logs, precise timestamps.
 */
export function formatDateTimeFull(input: DateInput): string {
  const d = toDate(input);
  if (!d) return '';
  return `${String(d.getFullYear())}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/**
 * Format as "YYYY-MM-DD" in local timezone.
 * For date-only displays.
 */
export function formatDateOnly(input: DateInput): string {
  const d = toDate(input);
  if (!d) return '';
  return `${String(d.getFullYear())}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function formatTimeOnly(input: DateInput): string {
  const d = toDate(input);
  if (!d) return '';
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/**
 * Relative time in the words of the page that shows it.
 *
 * Buckets: under a minute, minutes, hours, yesterday, days, weeks, then the
 * absolute date. `t` supplies the labels of the active language.
 */
export function formatRelativeTime(
  input: DateInput,
  t: (key: string, options?: { count?: number }) => string
): string {
  const date = toDate(input);
  if (!date) return '';
  const diffSecs = Math.floor((Date.now() - date.getTime()) / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSecs < 60) return t('common.time.justNow');
  if (diffMins < 60) return t('common.time.minutesAgo', { count: diffMins });
  if (diffHours < 24) return t('common.time.hoursAgo', { count: diffHours });
  if (diffDays === 1) return t('common.time.yesterday');
  if (diffDays < 7) return t('common.time.daysAgo', { count: diffDays });
  if (diffDays < 30) return t('common.time.weeksAgo', { count: Math.floor(diffDays / 7) });
  return formatDateOnly(date);
}

/**
 * Format a duration in milliseconds for timeline steps.
 */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${String(Math.round(ms))}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.round((ms % 60000) / 1000);
  return seconds > 0 ? `${String(minutes)}m ${String(seconds)}s` : `${String(minutes)}m`;
}

/**
 * Verbose duration for detailed execution logs.
 */
export function formatDurationVerbose(ms: number): string {
  if (ms < 1000) return `${String(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}
