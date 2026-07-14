import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  buildSessionInvocationLedger,
  sessionInvocationLedgerSummary,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/sessionInvocationLedgerModel.js'
);

function timelineItem(overrides = {}) {
  return {
    id: 'timeline-1',
    type: 'act',
    eventTimeUs: 1,
    eventCounter: 1,
    ...overrides,
  };
}

test('pairs structural act and observe records without inventing authorization metadata', () => {
  const entries = buildSessionInvocationLedger(
    [
      timelineItem({
        id: 'act-1',
        toolName: 'write_file',
        toolInput: { path: 'src/app.ts' },
      }),
      timelineItem({
        id: 'observe-1',
        type: 'observe',
        eventTimeUs: 2,
        eventCounter: 2,
        toolName: 'write_file',
        toolInput: { path: 'src/app.ts' },
        toolOutput: { ok: true },
      }),
    ],
    { runId: 'run-current', revision: 7 },
  );

  assert.equal(entries.length, 1);
  assert.equal(entries[0].status, 'completed');
  assert.equal(entries[0].toolName, 'write_file');
  assert.equal(entries[0].invocationId, 'act-1');
  assert.equal(entries[0].invocationIdSource, 'timeline');
  assert.equal(entries[0].runId, 'run-current');
  assert.equal(entries[0].revision, 7);
  assert.equal(entries[0].scopeSource, 'session');
  assert.equal(entries[0].authorizationId, null);
  assert.deepEqual(entries[0].sourceEventIds, ['act-1', 'observe-1']);
});

test('preserves explicit invocation, run, revision, authorization, and all ledger statuses', () => {
  const statuses = ['prepared', 'executing', 'completed', 'failed', 'unknown_outcome'];
  const entries = buildSessionInvocationLedger(
    statuses.map((status, index) =>
      timelineItem({
        id: `event-${status}`,
        type: 'tool_invocation',
        eventTimeUs: index + 1,
        eventCounter: index + 1,
        payload: {
          invocation_id: `invocation-${status}`,
          tool_name: `tool-${status}`,
          status,
          run_id: `run-${status}`,
          run_revision: index + 3,
          authorization_id: `grant-${status}`,
        },
      }),
    ),
    { runId: 'run-current', revision: 99 },
  );

  assert.deepEqual(
    entries.map((entry) => entry.status).sort(),
    [...statuses].sort(),
  );
  const unknown = entries.find((entry) => entry.status === 'unknown_outcome');
  assert.equal(unknown.invocationId, 'invocation-unknown_outcome');
  assert.equal(unknown.invocationIdSource, 'event');
  assert.equal(unknown.runId, 'run-unknown_outcome');
  assert.equal(unknown.revision, 7);
  assert.equal(unknown.scopeSource, 'event');
  assert.equal(unknown.authorizationId, 'grant-unknown_outcome');
});

test('keeps unknown outcomes blocking even when other calls completed', () => {
  const entries = buildSessionInvocationLedger([
    timelineItem({
      id: 'completed-1',
      type: 'tool_invocation',
      payload: {
        invocation_id: 'invocation-completed',
        tool_name: 'read_file',
        status: 'completed',
      },
    }),
    timelineItem({
      id: 'unknown-1',
      type: 'tool_invocation',
      eventTimeUs: 2,
      payload: {
        invocation_id: 'invocation-unknown',
        tool_name: 'bash',
        status: 'unknown_outcome',
      },
    }),
  ]);
  const summary = sessionInvocationLedgerSummary(entries);

  assert.deepEqual(summary, {
    total: 2,
    prepared: 0,
    executing: 0,
    completed: 1,
    failed: 0,
    unknownOutcome: 1,
    blocked: true,
  });
});

test('does not turn unrelated timeline messages into tool ledger entries', () => {
  const entries = buildSessionInvocationLedger([
    timelineItem({ id: 'user-1', type: 'user_message', role: 'user', content: 'Run tests' }),
    timelineItem({
      id: 'assistant-1',
      type: 'assistant_message',
      role: 'assistant',
      content: 'I will inspect the code.',
    }),
  ]);

  assert.deepEqual(entries, []);
  assert.deepEqual(sessionInvocationLedgerSummary(entries), {
    total: 0,
    prepared: 0,
    executing: 0,
    completed: 0,
    failed: 0,
    unknownOutcome: 0,
    blocked: false,
  });
});

test('prefers the Rust authority ledger over inferred timeline tool activity', () => {
  const entries = buildSessionInvocationLedger(
    [timelineItem({ id: 'legacy-act', toolName: 'write' })],
    { runId: 'run-1', revision: 9 },
    [
      {
        invocation_id: 'invocation-authority-1',
        grant_id: 'grant-1',
        run_id: 'run-1',
        plan_version_id: 'plan-2',
        run_revision: 9,
        environment_id: 'environment-1',
        tool_name: 'write',
        target: { input_digest: 'digest-1' },
        effect: 'mutate',
        input_digest: 'digest-1',
        redacted_input: { path: 'src/app.ts', api_key: '[REDACTED]' },
        status: 'unknown_outcome',
        prepared_at_ms: 100,
        started_at_ms: 110,
        finished_at_ms: 120,
      },
    ],
  );

  assert.equal(entries.length, 1);
  assert.equal(entries[0].invocationId, 'invocation-authority-1');
  assert.equal(entries[0].authorizationId, 'grant-1');
  assert.equal(entries[0].status, 'unknown_outcome');
  assert.equal(entries[0].updatedAtUs, 120_000);
  assert.deepEqual(entries[0].sourceEventIds, []);
});
