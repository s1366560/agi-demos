/**
 * Unified date utility functions
 *
 * All formatting functions output in the user's local timezone.
 * Backend sends ISO 8601 UTC strings; `new Date()` auto-converts to local TZ.
 *
 * Format convention: ISO style (YYYY-MM-DD HH:mm)
 */

type DateInput = Date | string | number | null | undefined;

function pad(n: number): string {
  return n < 10 ? `0${n}` : `${n}`;
}

function toDate(input: DateInput): Date | null {
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
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/**
 * Format as "YYYY-MM-DD HH:mm:ss" in local timezone.
 * For detail views, logs, precise timestamps.
 */
export function formatDateTimeFull(input: DateInput): string {
  const d = toDate(input);
  if (!d) return '';
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/**
 * Format as "YYYY-MM-DD" in local timezone.
 * For date-only displays.
 */
export function formatDateOnly(input: DateInput): string {
  const d = toDate(input);
  if (!d) return '';
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/**
 * Format as "HH:mm" in local timezone.
 * For time-only displays.
 */
export function formatTimeOnly(input: DateInput): string {
  const d = toDate(input);
  if (!d) return '';
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/**
 * Format as "HH:mm:ss" in local timezone.
 * For precise time displays.
 */
export function formatTimeWithSeconds(input: DateInput): string {
  const d = toDate(input);
  if (!d) return '';
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/** @deprecated Use formatDateOnly */
export function formatDate(date: Date): string {
  return formatDateOnly(date);
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
 * Relative time in English: "just now", "5m ago", "2d ago"
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
    return 'just now';
  } else if (diffMins < 60) {
    return `${diffMins}m ago`;
  } else if (diffHours < 24) {
    return `${diffHours}h ago`;
  } else if (diffDays < 7) {
    return `${diffDays}d ago`;
  } else {
    return formatDateOnly(date);
  }
}

/**
 * Relative time in Chinese
 */
export function formatDistanceToNowCN(input: DateInput): string {
  const date = toDate(input);
  if (!date) return '';
  const now = Date.now();
  const diffMs = now - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSecs < 10) {
    return '刚刚';
  } else if (diffSecs < 60) {
    return `${diffSecs}秒前`;
  } else if (diffMins < 60) {
    return `${diffMins}分钟前`;
  } else if (diffHours < 24) {
    return `${diffHours}小时前`;
  } else if (diffDays === 1) {
    return '昨天';
  } else if (diffDays < 7) {
    return `${diffDays}天前`;
  } else if (diffDays < 30) {
    const weeks = Math.floor(diffDays / 7);
    return `${weeks}周前`;
  } else {
    return formatDateOnly(date);
  }
}
