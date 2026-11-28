import { describe, expect, it } from 'vitest';

import {
  formatDuration,
  formatDurationVerbose,
  formatRelativeTime,
} from '../../../../sdk/memstack-plugin-sdk/ui/localDate';
import {
  formatDuration as hostFormatDuration,
  formatDurationVerbose as hostFormatDurationVerbose,
} from '@/utils/date';

const minute = 60_000;
const hour = 60 * minute;
const labels = (key: string, options?: { count?: number }) =>
  `${key}${options?.count === undefined ? '' : `:${String(options.count)}`}`;

describe('duration formatting', () => {
  it('formats timeline step durations', () => {
    expect(formatDuration(204)).toBe('204ms');
    expect(formatDuration(1500)).toBe('1.5s');
    expect(formatDuration(150000)).toBe('2m 30s');
    expect(formatDuration(120000)).toBe('2m');
    expect(formatDurationVerbose(204)).toBe('204ms');
    expect(formatDurationVerbose(1500)).toBe('1.50s');
  });

  it('is the same implementation for the host shell and isolated signed pages', () => {
    expect(hostFormatDuration).toBe(formatDuration);
    expect(hostFormatDurationVerbose).toBe(formatDurationVerbose);
  });

  it('names relative time with the words of the page that shows it', () => {
    const now = Date.now();

    expect(formatRelativeTime(now - 5 * minute, labels)).toBe('common.time.minutesAgo:5');
    expect(formatRelativeTime(now - 3 * hour, labels)).toBe('common.time.hoursAgo:3');
    expect(formatRelativeTime(now - 26 * hour, labels)).toBe('common.time.yesterday');
    expect(formatRelativeTime(now - 20 * 24 * hour, labels)).toBe('common.time.weeksAgo:2');
    expect(formatRelativeTime('not a date', labels)).toBe('');
  });
});
