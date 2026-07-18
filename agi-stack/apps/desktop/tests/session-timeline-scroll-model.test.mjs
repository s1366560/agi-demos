import assert from 'node:assert/strict';
import test from 'node:test';

import {
  classifySessionTimelineWindowChange,
  isSessionTimelinePinnedToLatest,
  shouldFollowSessionTimeline,
} from '/tmp/agistack-desktop-test-dist/src/features/session/sessionTimelineScrollModel.js';

const windowState = (overrides = {}) => ({
  conversationId: 'conversation-a',
  firstId: 'event-1',
  lastId: 'event-5',
  tailRevision: 'complete response',
  count: 5,
  ...overrides,
});

test('timeline window changes distinguish replacement, prepend, append, and stable updates', () => {
  assert.equal(classifySessionTimelineWindowChange(null, windowState()), 'initial');
  assert.equal(
    classifySessionTimelineWindowChange(
      windowState(),
      windowState({ conversationId: 'conversation-b' }),
    ),
    'replaced',
  );
  assert.equal(
    classifySessionTimelineWindowChange(
      windowState(),
      windowState({ firstId: 'event-minus-5', count: 10 }),
    ),
    'prepended',
  );
  assert.equal(
    classifySessionTimelineWindowChange(
      windowState(),
      windowState({ lastId: 'event-6', count: 6 }),
    ),
    'appended',
  );
  assert.equal(
    classifySessionTimelineWindowChange(
      windowState(),
      windowState({ tailRevision: 'streamed response grew' }),
    ),
    'updated',
  );
  assert.equal(classifySessionTimelineWindowChange(windowState(), windowState()), 'stable');
});

test('timeline follows initial or replaced sessions and only follows appends while pinned', () => {
  assert.equal(shouldFollowSessionTimeline('initial', false), true);
  assert.equal(shouldFollowSessionTimeline('replaced', false), true);
  assert.equal(shouldFollowSessionTimeline('appended', true), true);
  assert.equal(shouldFollowSessionTimeline('appended', false), false);
  assert.equal(shouldFollowSessionTimeline('updated', true), true);
  assert.equal(shouldFollowSessionTimeline('updated', false), false);
  assert.equal(shouldFollowSessionTimeline('prepended', true), false);
  assert.equal(shouldFollowSessionTimeline('stable', true), false);
});

test('timeline pinned state uses a practical bottom tolerance', () => {
  assert.equal(
    isSessionTimelinePinnedToLatest({ scrollTop: 920, scrollHeight: 1_000, clientHeight: 40 }),
    true,
  );
  assert.equal(
    isSessionTimelinePinnedToLatest({ scrollTop: 700, scrollHeight: 1_000, clientHeight: 200 }),
    false,
  );
});
