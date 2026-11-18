import assert from 'node:assert/strict';
import test from 'node:test';
import {
  resolveTimelineRenderWindow,
  timelineWindowMember,
} from '/tmp/agistack-desktop-test-dist/src/features/chat/timelineRenderWindow.js';

const messages = count => Array.from({ length: count }, (_, i) => ({ item: { id: String(i) } }));

test('crossing the window threshold keeps the first mounted row while reading', () => {
  const before = messages(150);
  const initial = resolveTimelineRenderWindow(before, before.length, 0, null);
  const memberId = timelineWindowMember(before[initial.startIndex]);
  const after = messages(151);
  assert.deepEqual(resolveTimelineRenderWindow(after, 151, 0, { memberId, allowance: 0 }),
    { startIndex: 0, hiddenCount: 0 });
  assert.deepEqual(resolveTimelineRenderWindow(after, 151, 0, null),
    { startIndex: 51, hiddenCount: 51 });
});

test('revealing older rows still advances a full page after additional events arrived', () => {
  const rows = messages(420);
  rows.splice(150, 3, { items: [{ id: '150' }, { id: 'canonical', renderId: '151' }, { id: '152' }] });
  const retained = { memberId: '151', allowance: 0 };
  assert.deepEqual(resolveTimelineRenderWindow(rows, 420, 0, retained),
    { startIndex: 150, hiddenCount: 150 });
  assert.deepEqual(resolveTimelineRenderWindow(rows, 420, 100, retained),
    { startIndex: 50, hiddenCount: 50 });
  assert.deepEqual(resolveTimelineRenderWindow(rows, 420, 0, { memberId: 'deleted', allowance: 0 }),
    { startIndex: 318, hiddenCount: 320 });
});
