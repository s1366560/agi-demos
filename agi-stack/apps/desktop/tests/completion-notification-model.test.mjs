import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  completionNotificationAllowed,
  detectCompletionTransitions,
  quietHoursActive,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/activity/completionNotificationModel.js',
);
const {
  DEFAULT_NOTIFICATION_PREFERENCES,
  parseNotificationPreferences,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/settings/notificationPreferences.js',
);

function entry(id, category, overrides = {}) {
  return {
    id,
    conversationId: `conversation-${id}`,
    title: `Session ${id}`,
    category,
    ...overrides,
  };
}

const quietHoursOff = { enabled: false, start: '22:00', end: '08:00' };

test('initial sync is baseline and never fires (storm suppression)', () => {
  const { triggers, snapshot } = detectCompletionTransitions(null, [
    entry('a', 'needs_input'),
    entry('b', 'ready_for_review'),
    entry('c', 'attention'),
  ]);
  assert.deepEqual(triggers, []);
  assert.equal(snapshot.get('a'), 'needs_input');
  assert.equal(snapshot.get('b'), 'ready_for_review');
  assert.equal(snapshot.get('c'), 'attention');

  // A second identical projection still fires nothing.
  const followUp = detectCompletionTransitions(snapshot, [
    entry('a', 'needs_input'),
    entry('b', 'ready_for_review'),
    entry('c', 'attention'),
  ]);
  assert.deepEqual(followUp.triggers, []);
});

test('entry transitioning into needs_input or ready_for_review fires once', () => {
  const baseline = detectCompletionTransitions(null, [entry('a', 'attention')]).snapshot;
  const { triggers, snapshot } = detectCompletionTransitions(baseline, [
    entry('a', 'needs_input'),
    entry('b', 'ready_for_review'),
  ]);
  assert.deepEqual(
    triggers.map(({ entryId, kind, conversationId, title }) => ({
      entryId,
      kind,
      conversationId,
      title,
    })),
    [
      {
        entryId: 'a',
        kind: 'needs_input',
        conversationId: 'conversation-a',
        title: 'Session a',
      },
      {
        entryId: 'b',
        kind: 'ready_for_review',
        conversationId: 'conversation-b',
        title: 'Session b',
      },
    ],
  );
  // Remaining in the same state across polls does not re-fire.
  const repeat = detectCompletionTransitions(snapshot, [
    entry('a', 'needs_input'),
    entry('b', 'ready_for_review'),
  ]);
  assert.deepEqual(repeat.triggers, []);
});

test('category flips between notifiable states fire again; attention never fires', () => {
  const first = detectCompletionTransitions(null, [entry('a', 'needs_input')]);
  assert.deepEqual(first.triggers, []);
  const flip = detectCompletionTransitions(first.snapshot, [
    entry('a', 'ready_for_review'),
    entry('b', 'attention'),
  ]);
  assert.deepEqual(
    flip.triggers.map((trigger) => [trigger.entryId, trigger.kind]),
    [['a', 'ready_for_review']],
  );
  // Leaving a notifiable state and returning later counts as a fresh transition.
  const cleared = detectCompletionTransitions(flip.snapshot, []);
  const returned = detectCompletionTransitions(cleared.snapshot, [entry('a', 'needs_input')]);
  assert.deepEqual(
    returned.triggers.map((trigger) => [trigger.entryId, trigger.kind]),
    [['a', 'needs_input']],
  );
});

test('mode gating honors off, window focus, and always', () => {
  const base = {
    delivery: 'desktop_and_in_app',
    reviewAlerts: true,
    quietHours: quietHoursOff,
  };
  assert.equal(
    completionNotificationAllowed({ ...base, mode: 'off', windowFocused: false }),
    false,
  );
  assert.equal(
    completionNotificationAllowed({ ...base, mode: 'window_not_focused', windowFocused: true }),
    false,
  );
  assert.equal(
    completionNotificationAllowed({ ...base, mode: 'window_not_focused', windowFocused: false }),
    true,
  );
  assert.equal(
    completionNotificationAllowed({ ...base, mode: 'always', windowFocused: true }),
    true,
  );
});

test('master switch, delivery channel, and quiet hours suppress OS notifications', () => {
  const base = { mode: 'always', windowFocused: true, quietHours: quietHoursOff };
  assert.equal(
    completionNotificationAllowed({ ...base, delivery: 'in_app', reviewAlerts: true }),
    false,
  );
  assert.equal(
    completionNotificationAllowed({
      ...base,
      delivery: 'desktop_and_in_app',
      reviewAlerts: false,
    }),
    false,
  );
  assert.equal(
    completionNotificationAllowed({
      ...base,
      delivery: 'desktop',
      reviewAlerts: true,
      quietHours: { enabled: true, start: '22:00', end: '08:00' },
      now: new Date(2026, 6, 13, 23, 30),
    }),
    false,
  );
  assert.equal(
    completionNotificationAllowed({
      ...base,
      delivery: 'desktop',
      reviewAlerts: true,
      quietHours: { enabled: true, start: '22:00', end: '08:00' },
      now: new Date(2026, 6, 13, 12, 0),
    }),
    true,
  );
});

test('quiet hours handle overnight ranges, boundaries, and degenerate values', () => {
  const overnight = { enabled: true, start: '22:00', end: '08:00' };
  assert.equal(quietHoursActive(overnight, new Date(2026, 6, 13, 22, 0)), true);
  assert.equal(quietHoursActive(overnight, new Date(2026, 6, 13, 7, 59)), true);
  assert.equal(quietHoursActive(overnight, new Date(2026, 6, 13, 8, 0)), false);
  assert.equal(quietHoursActive(overnight, new Date(2026, 6, 13, 21, 59)), false);
  const daytime = { enabled: true, start: '12:00', end: '14:00' };
  assert.equal(quietHoursActive(daytime, new Date(2026, 6, 13, 13, 0)), true);
  assert.equal(quietHoursActive(daytime, new Date(2026, 6, 13, 15, 0)), false);
  assert.equal(
    quietHoursActive({ enabled: true, start: '10:00', end: '10:00' }, new Date(2026, 6, 13, 10, 0)),
    false,
  );
  assert.equal(
    quietHoursActive({ enabled: false, start: '00:00', end: '23:59' }, new Date(2026, 6, 13, 12, 0)),
    false,
  );
  assert.equal(
    quietHoursActive({ enabled: true, start: 'night', end: 'morning' }, new Date(2026, 6, 13, 12, 0)),
    false,
  );
});

test('completion mode persists through the versioned preference contract', () => {
  assert.equal(DEFAULT_NOTIFICATION_PREFERENCES.completionMode, 'window_not_focused');
  // Snapshots stored before the mode existed fall back to the default.
  const legacy = parseNotificationPreferences(
    JSON.stringify({
      version: 1,
      reviewAlerts: true,
      delivery: 'desktop',
      quietHours: { enabled: false, start: '22:00', end: '08:00' },
    }),
  );
  assert.equal(legacy.completionMode, 'window_not_focused');
  const explicit = parseNotificationPreferences(
    JSON.stringify({
      version: 1,
      reviewAlerts: true,
      delivery: 'desktop',
      completionMode: 'always',
      quietHours: { enabled: false, start: '22:00', end: '08:00' },
    }),
  );
  assert.equal(explicit.completionMode, 'always');
  // Invalid values fail closed to the full defaults.
  const invalid = parseNotificationPreferences(
    JSON.stringify({
      version: 1,
      reviewAlerts: true,
      delivery: 'desktop',
      completionMode: 'sometimes',
      quietHours: { enabled: false, start: '22:00', end: '08:00' },
    }),
  );
  assert.deepEqual(invalid, DEFAULT_NOTIFICATION_PREFERENCES);
});
