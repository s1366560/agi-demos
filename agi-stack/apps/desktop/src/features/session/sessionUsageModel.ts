import type { AgentTimelineItem } from '../../types';
import { buildSessionContextWindow } from './sessionContextWindowModel';

// Pure derivation of session usage signals (context-token waterline, run
// duration) from data the desktop client truthfully holds: context_status /
// context_compressed timeline events and authoritative run timestamps. The
// session projection contract carries no per-run token counters or cost
// fields today, so occupancy and duration are the only usage signals shown;
// nothing is fabricated beyond what these sources provide.

export type SessionUsageSummary = {
  currentTokens: number;
  tokenBudget: number;
  occupancyPct: number;
};

/**
 * Latest context-window occupancy reported by the runtime, or null when the
 * timeline carries no context_status / context_compressed events yet.
 */
export function deriveSessionUsage(
  items: readonly AgentTimelineItem[],
): SessionUsageSummary | null {
  const current = buildSessionContextWindow(items).current;
  if (!current) return null;
  return {
    currentTokens: current.currentTokens,
    tokenBudget: current.tokenBudget,
    occupancyPct: current.occupancyPct,
  };
}

/** Compact token count: 999 → "999", 12_300 → "12.3k", 2_400_000 → "2.4M". */
export function formatTokenCount(tokens: number): string {
  if (!Number.isFinite(tokens) || tokens < 0) return '';
  if (tokens < 1_000) return String(Math.round(tokens));
  if (tokens < 1_000_000) return `${compactScaled(tokens / 1_000)}k`;
  return `${compactScaled(tokens / 1_000_000)}M`;
}

/**
 * Milliseconds between two ISO-8601 run timestamps. Returns null when either
 * endpoint is missing, unparseable, or out of order so the caller omits the
 * duration rather than showing a bogus value.
 */
export function runDurationMs(
  startedAt: string | null | undefined,
  completedAt: string | null | undefined,
): number | null {
  if (!startedAt || !completedAt) return null;
  const startedMs = Date.parse(startedAt);
  const completedMs = Date.parse(completedAt);
  if (!Number.isFinite(startedMs) || !Number.isFinite(completedMs)) return null;
  const durationMs = completedMs - startedMs;
  return durationMs >= 0 ? durationMs : null;
}

function compactScaled(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
}
