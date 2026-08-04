import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  deriveSessionUsage,
  formatTokenCount,
  runDurationMs,
} = require('/tmp/agistack-desktop-test-dist/src/features/session/sessionUsageModel.js');

let idSequence = 0;

function item(overrides) {
  idSequence += 1;
  return {
    id: overrides.id ?? `item-${idSequence}`,
    type: 'act',
    eventTimeUs: 1_000_000 + idSequence * 1_000,
    eventCounter: idSequence,
    ...overrides,
  };
}

function contextStatus(overrides = {}) {
  const { payload: payloadOverrides, ...rest } = overrides;
  return item({
    type: 'context_status',
    payload: {
      current_tokens: 12_300,
      token_budget: 200_000,
      occupancy_pct: 6.15,
      compression_level: 'none',
      ...(payloadOverrides ?? {}),
    },
    ...rest,
  });
}

test('returns null when the timeline carries no context window events', () => {
  assert.equal(deriveSessionUsage([]), null);
  assert.equal(deriveSessionUsage([item({ type: 'thought', content: 'hi' })]), null);
});

test('derives the latest context occupancy from context_status events', () => {
  const older = contextStatus({ payload: { current_tokens: 4_000, occupancy_pct: 2 } });
  const newer = contextStatus();
  const usage = deriveSessionUsage([older, newer]);
  assert.deepEqual(usage, {
    currentTokens: 12_300,
    tokenBudget: 200_000,
    occupancyPct: 6.15,
  });
});

test('ignores malformed context_status payloads', () => {
  const malformed = item({ type: 'context_status', payload: { current_tokens: 5 } });
  assert.equal(deriveSessionUsage([malformed]), null);
});

test('formats token counts compactly', () => {
  assert.equal(formatTokenCount(0), '0');
  assert.equal(formatTokenCount(999), '999');
  assert.equal(formatTokenCount(1_000), '1k');
  assert.equal(formatTokenCount(1_500), '1.5k');
  assert.equal(formatTokenCount(12_300), '12.3k');
  assert.equal(formatTokenCount(1_000_000), '1M');
  assert.equal(formatTokenCount(2_400_000), '2.4M');
  assert.equal(formatTokenCount(-5), '');
  assert.equal(formatTokenCount(Number.NaN), '');
});

test('computes run durations from ISO timestamps truthfully', () => {
  assert.equal(
    runDurationMs('2026-01-01T00:00:00Z', '2026-01-01T00:03:12Z'),
    192_000,
  );
  assert.equal(runDurationMs('2026-01-01T00:00:00Z', null), null);
  assert.equal(runDurationMs(null, '2026-01-01T00:00:00Z'), null);
  assert.equal(runDurationMs(undefined, undefined), null);
  assert.equal(runDurationMs('garbage', '2026-01-01T00:00:00Z'), null);
  // Out-of-order timestamps yield no duration rather than a negative value.
  assert.equal(runDurationMs('2026-01-01T00:03:12Z', '2026-01-01T00:00:00Z'), null);
});
