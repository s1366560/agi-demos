import assert from 'node:assert/strict';
import test from 'node:test';

import {
  queuedRunInputHandoffState,
  visibleQueuedRunInputs,
} from '/tmp/agistack-desktop-test-dist/src/features/session/sessionRunInputModel.js';

const input = (delivery, status, id = status) => ({ id, delivery, status });

test('queue handoff state exposes only authoritative queue lifecycle phases', () => {
  assert.equal(queuedRunInputHandoffState(input('queue_next', 'queued')), 'waiting');
  assert.equal(queuedRunInputHandoffState(input('queue_next', 'ready')), 'ready');
  assert.equal(queuedRunInputHandoffState(input('queue_next', 'blocked')), 'blocked');
  assert.equal(queuedRunInputHandoffState(input('queue_next', 'promoted_to_plan')), 'promoted');
  assert.equal(queuedRunInputHandoffState(input('steer_now', 'applied')), null);
});

test('visible queue inputs preserve FIFO order and omit steering records', () => {
  assert.deepEqual(
    visibleQueuedRunInputs([
      input('steer_now', 'applied', 'steer'),
      input('queue_next', 'queued', 'first'),
      input('queue_next', 'ready', 'second'),
    ]).map((item) => item.id),
    ['first', 'second'],
  );
});
