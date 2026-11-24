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
