/** Older device snapshots used Unix seconds; new snapshots use RFC3339. */
export function computerUseTimestamp(value: unknown): string | null {
  if (typeof value === 'number') {
    const milliseconds = value * 1000;
    if (!Number.isFinite(milliseconds) || !Number.isFinite(new Date(milliseconds).getTime()))
      return null;
    return new Date(milliseconds).toISOString();
  }
  if (
    typeof value !== 'string' ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/u.test(value) ||
    !Number.isFinite(Date.parse(value))
  )
    return null;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(5, 7));
  const day = Number(value.slice(8, 10));
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth =
    [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1] ?? 0;
  if (day < 1 || day > daysInMonth || Number(value.slice(11, 13)) > 23) return null;
  return value;
}
