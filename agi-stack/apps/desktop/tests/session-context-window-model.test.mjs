import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { buildSessionContextWindow, isSessionContextWindowEvent } = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/sessionContextWindowModel.js'
);

const event = (id, type, payload, counter) => ({
  id,
  type,
  payload,
  eventTimeUs: 1_900_000_000 + counter,
  eventCounter: counter,
});

const history = {
  total_compressions: 2,
  total_tokens_saved: 28_000,
  average_compression_ratio: 0.64,
  average_savings_pct: 36,
  recent_records: [
    {
      timestamp: '2026-07-22T08:10:00Z',
      level: 'l2_summarize',
      tokens_before: 72_000,
      tokens_after: 54_000,
      tokens_saved: 18_000,
      compression_ratio: 0.75,
      savings_pct: 25,
      messages_before: 42,
      messages_after: 26,
      duration_ms: 46,
    },
  ],
};

test('projects context status, distribution, cache evidence, and compression history', () => {
  const model = buildSessionContextWindow([
    event(
      'status',
      'context_status',
      {
        current_tokens: 61_000,
        token_budget: 128_000,
        occupancy_pct: 47.7,
        compression_level: 'l2_summarize',
        token_distribution: {
          system: 8_000,
          user: 10_000,
          assistant: 18_000,
          tool: 15_000,
          summary: 10_000,
        },
        compression_history_summary: history,
        from_cache: true,
        messages_in_summary: 16,
      },
      1
    ),
  ]);

  assert.deepEqual(model.current, {
    currentTokens: 61_000,
    tokenBudget: 128_000,
    occupancyPct: 47.7,
    compressionLevel: 'l2_summarize',
    tokenDistribution: {
      system: 8_000,
      user: 10_000,
      assistant: 18_000,
      tool: 15_000,
      summary: 10_000,
      total: 61_000,
    },
    compressionHistory: {
      totalCompressions: 2,
      totalTokensSaved: 28_000,
      averageCompressionRatio: 0.64,
      averageSavingsPct: 36,
      recentRecords: [
        {
          id: '2026-07-22T08:10:00Z:0',
          timestamp: '2026-07-22T08:10:00Z',
          level: 'l2_summarize',
          tokensBefore: 72_000,
          tokensAfter: 54_000,
          tokensSaved: 18_000,
          compressionRatio: 0.75,
          savingsPct: 25,
          messagesBefore: 42,
          messagesAfter: 26,
          durationMs: 46,
        },
      ],
    },
    fromCache: true,
    messagesInSummary: 16,
    updatedAtUs: 1_900_000_001,
  });
  assert.deepEqual(model.summary, {
    updates: 1,
    compressions: 0,
    totalTokensSaved: 28_000,
  });
});

test('applies compression evidence then preserves its distribution and history on sparse status', () => {
  const model = buildSessionContextWindow([
    event(
      'compressed',
      'context_compressed',
      {
        was_compressed: true,
        compression_strategy: 'summarize',
        compression_level: 'l2_summarize',
        original_message_count: 42,
        final_message_count: 26,
        estimated_tokens: 54_000,
        token_budget: 128_000,
        budget_utilization_pct: 42.2,
        summarized_message_count: 16,
        tokens_saved: 18_000,
        compression_ratio: 0.75,
        pruned_tool_outputs: 4,
        duration_ms: 46,
        token_distribution: {
          system: 8_000,
          user: 8_000,
          assistant: 16_000,
          tool: 12_000,
          summary: 10_000,
        },
        compression_history_summary: history,
      },
      1
    ),
    event(
      'status',
      'context_status',
      {
        current_tokens: 61_000,
        token_budget: 128_000,
        occupancy_pct: 47.7,
        compression_level: 'l2_summarize',
        token_distribution: {},
        compression_history_summary: {},
        from_cache: true,
        messages_in_summary: 16,
      },
      2
    ),
  ]);

  assert.equal(model.current?.currentTokens, 61_000);
  assert.equal(model.current?.fromCache, true);
  assert.equal(model.current?.tokenDistribution.total, 54_000);
  assert.equal(model.current?.compressionHistory.totalCompressions, 2);
  assert.deepEqual(model.compressions, [
    {
      id: 'compressed',
      eventTimeUs: 1_900_000_001,
      wasCompressed: true,
      strategy: 'summarize',
      compressionLevel: 'l2_summarize',
      originalMessageCount: 42,
      finalMessageCount: 26,
      estimatedTokens: 54_000,
      tokenBudget: 128_000,
      budgetUtilizationPct: 42.2,
      summarizedMessageCount: 16,
      tokensSaved: 18_000,
      compressionRatio: 0.75,
      prunedToolOutputs: 4,
      durationMs: 46,
    },
  ]);
  assert.deepEqual(model.summary, {
    updates: 2,
    compressions: 1,
    totalTokensSaved: 28_000,
  });
});

test('fails closed for malformed, duplicate, and unrelated context events', () => {
  const model = buildSessionContextWindow([
    event('bad-status', 'context_status', { current_tokens: -1, token_budget: 128_000 }, 1),
    event(
      'valid-status',
      'context_status',
      {
        current_tokens: 12_000,
        token_budget: 128_000,
        occupancy_pct: 9.4,
        compression_level: 'none',
        token_distribution: {},
        compression_history_summary: {},
      },
      2
    ),
    event(
      'valid-status',
      'context_status',
      {
        current_tokens: 99_000,
        token_budget: 128_000,
        occupancy_pct: 77.3,
        compression_level: 'none',
      },
      3
    ),
    event(
      'bad-compressed',
      'context_compressed',
      {
        was_compressed: true,
        compression_strategy: 'invented',
        compression_level: 'l2_summarize',
      },
      4
    ),
    event('unrelated', 'cost_update', { input_tokens: 100 }, 5),
  ]);

  assert.equal(model.current?.currentTokens, 12_000);
  assert.equal(model.compressions.length, 0);
  assert.equal(model.summary.updates, 1);
});

test('recognizes only the exact context window event protocol', () => {
  assert.equal(isSessionContextWindowEvent({ type: 'context_status' }), true);
  assert.equal(isSessionContextWindowEvent({ event_type: 'context_compressed' }), true);
  assert.equal(isSessionContextWindowEvent({ type: 'context_compacted' }), false);
  assert.equal(isSessionContextWindowEvent({ type: 'context_status_extra' }), false);
});

test('Desktop exposes a dynamic Context canvas with distribution and selectable history', () => {
  const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
  const canvasSource = readFileSync(
    new URL('../src/features/session/SessionContextWindowCanvas.tsx', import.meta.url),
    'utf8'
  );
  const qaSource = readFileSync(new URL('../src/qa/SessionSteeringQa.tsx', import.meta.url), 'utf8');

  assert.match(appSource, /buildSessionContextWindow\(timelineItems\)/);
  assert.match(appSource, /tab: 'context'/);
  assert.match(appSource, /activeTab === 'context'/);
  assert.match(canvasSource, /session-context-window-canvas/);
  assert.match(canvasSource, /aria-pressed=\{selected\}/);
  assert.match(canvasSource, /tokenDistributionSegments\.map/);
  assert.match(canvasSource, /recentRecords\.map/);
  assert.match(qaSource, /context-window-canvas/);
});
