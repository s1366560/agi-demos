import assert from 'node:assert/strict';
import test from 'node:test';

import {
  resolvePickerMenuPlacement,
} from '/tmp/agistack-desktop-test-dist/src/features/chat/pickerMenuPlacement.js';

const viewport = { width: 1728, height: 1024 };

test('prefers the side of the anchor when the menu fits', () => {
  assert.equal(
    resolvePickerMenuPlacement({
      anchor: { top: 279, right: 987, bottom: 311, left: 783 },
      viewport,
      menuWidth: 264,
      menuHeight: 350,
    }),
    'right',
  );
  assert.equal(
    resolvePickerMenuPlacement({
      anchor: { top: 962, right: 943, bottom: 994, left: 840 },
      viewport,
      menuWidth: 264,
      menuHeight: 350,
    }),
    'right',
  );
});

test('falls back to vertical placement near the right edge', () => {
  assert.equal(
    resolvePickerMenuPlacement({
      anchor: { top: 600, right: 1700, bottom: 632, left: 1600 },
      viewport,
      menuWidth: 264,
      menuHeight: 350,
    }),
    'left',
  );
  assert.equal(
    resolvePickerMenuPlacement({
      anchor: { top: 500, right: 100, bottom: 532, left: 20 },
      viewport: { width: 300, height: 900 },
      menuWidth: 264,
      menuHeight: 350,
    }),
    'up',
  );
});

test('never returns a placement that clips the titlebar when a side fits', () => {
  const placement = resolvePickerMenuPlacement({
    anchor: { top: 2, right: 500, bottom: 34, left: 400 },
    viewport,
    menuWidth: 264,
    menuHeight: 350,
  });
  assert.notEqual(placement, 'up');
});
