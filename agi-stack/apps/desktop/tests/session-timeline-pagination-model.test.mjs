import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  compareSessionTimelineCursors,
  failEarlierTimelinePage,
  resolveEarlierTimelinePage,
} = require('/tmp/agistack-desktop-test-dist/src/features/session/sessionTimelinePaginationModel.js');

test('earlier timeline cursors compare time before the event counter', () => {
  assert.equal(
    compareSessionTimelineCursors(
      { timeUs: 100, counter: 9 },
      { timeUs: 101, counter: 0 },
    ) < 0,
    true,
  );
  assert.equal(
    compareSessionTimelineCursors(
      { timeUs: 100, counter: 2 },
      { timeUs: 100, counter: 3 },
    ) < 0,
    true,
  );
  assert.equal(
    compareSessionTimelineCursors(
      { timeUs: 100, counter: 3 },
      { timeUs: 100, counter: 3 },
    ),
    0,
  );
});

test('an earlier page advances only when it adds items and moves the cursor backward', () => {
  assert.deepEqual(
    resolveEarlierTimelinePage({
      requestedCursor: { timeUs: 100, counter: 4 },
      previousItemCount: 50,
      nextItemCount: 100,
      nextFirstCursor: { timeUs: 80, counter: 2 },
      responseHasMore: true,
    }),
    {
      kind: 'accepted',
      firstCursor: { timeUs: 80, counter: 2 },
      hasMore: true,
    },
  );
  assert.deepEqual(
    resolveEarlierTimelinePage({
      requestedCursor: { timeUs: 100, counter: 4 },
      previousItemCount: 50,
      nextItemCount: 51,
      nextFirstCursor: { timeUs: 100, counter: 3 },
      responseHasMore: true,
    }),
    {
      kind: 'accepted',
      firstCursor: { timeUs: 100, counter: 3 },
      hasMore: true,
    },
  );
});

test('the final earlier page preserves the authoritative exhausted state', () => {
  assert.deepEqual(
    resolveEarlierTimelinePage({
      requestedCursor: { timeUs: 100, counter: 4 },
      previousItemCount: 50,
      nextItemCount: 70,
      nextFirstCursor: { timeUs: 70, counter: 1 },
      responseHasMore: false,
    }),
    {
      kind: 'accepted',
      firstCursor: { timeUs: 70, counter: 1 },
      hasMore: false,
    },
  );
});

test('a repeated page fails closed even when the server keeps reporting more history', () => {
  assert.deepEqual(
    resolveEarlierTimelinePage({
      requestedCursor: { timeUs: 100, counter: 4 },
      previousItemCount: 50,
      nextItemCount: 50,
      nextFirstCursor: { timeUs: 100, counter: 4 },
      responseHasMore: true,
    }),
    { kind: 'stalled', reason: 'no_new_items', hasMore: false },
  );
});

test('a non-monotonic or missing cursor fails closed after adding items', () => {
  for (const nextFirstCursor of [
    null,
    { timeUs: 100, counter: 4 },
    { timeUs: 100, counter: 5 },
    { timeUs: 101, counter: 0 },
  ]) {
    assert.deepEqual(
      resolveEarlierTimelinePage({
        requestedCursor: { timeUs: 100, counter: 4 },
        previousItemCount: 50,
        nextItemCount: 51,
        nextFirstCursor,
        responseHasMore: true,
      }),
      { kind: 'stalled', reason: 'cursor_not_earlier', hasMore: false },
    );
  }
});

test('a failed earlier page preserves the loaded window and disables automatic pagination', () => {
  const items = [{ id: 'event-1' }, { id: 'event-2' }];
  const firstCursor = { timeUs: 100, counter: 4 };
  const lastCursor = { timeUs: 120, counter: 1 };
  const current = {
    conversationId: 'conversation-1',
    items,
    approvalRequests: [],
    artifactVersions: [],
    artifactDeliveries: [],
    toolInvocations: [],
    loading: false,
    loadingEarlier: true,
    error: null,
    hasMore: true,
    firstCursor,
    lastCursor,
  };

  const failed = failEarlierTimelinePage(current, 'History did not advance');

  assert.notEqual(failed, current);
  assert.equal(failed.items, items);
  assert.equal(failed.firstCursor, firstCursor);
  assert.equal(failed.lastCursor, lastCursor);
  assert.equal(failed.loadingEarlier, false);
  assert.equal(failed.hasMore, false);
  assert.equal(failed.error, 'History did not advance');
});
