import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  filterShortcutGroups,
  keypressCombo,
  shortcutChordCombos,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/navigation/keyboardShortcutSearchModel.js',
);
const { KEYBOARD_SHORTCUTS, SHORTCUT_GROUPS } = require(
  '/tmp/agistack-desktop-test-dist/src/features/navigation/keyboardShortcutModel.js',
);

const labelFor = (definition) => `label:${definition.id}`;

function press(key, modifiers = {}) {
  return keypressCombo({
    key,
    metaKey: Boolean(modifiers.meta),
    ctrlKey: Boolean(modifiers.ctrl),
    altKey: Boolean(modifiers.alt),
    shiftKey: Boolean(modifiers.shift),
  });
}

test('shortcutChordCombos parses modifier combos and alternative keys', () => {
  assert.deepEqual(shortcutChordCombos('⌘ K'), ['meta+k']);
  assert.deepEqual(shortcutChordCombos('Ctrl K'), ['ctrl+k']);
  assert.deepEqual(shortcutChordCombos('⌘ ⌥ U'), ['meta+alt+u']);
  assert.deepEqual(shortcutChordCombos('Ctrl Alt U'), ['ctrl+alt+u']);
  assert.deepEqual(shortcutChordCombos('⇧ Enter'), ['shift+enter']);
  assert.deepEqual(shortcutChordCombos('↑ ↓'), ['arrowup', 'arrowdown']);
  assert.deepEqual(shortcutChordCombos('Home End'), ['home', 'end']);
  assert.deepEqual(shortcutChordCombos('⌘ /'), ['meta+/']);
  assert.deepEqual(shortcutChordCombos('Esc'), ['escape']);
  assert.deepEqual(shortcutChordCombos('/'), ['/']);
});

test('keypressCombo normalizes live key events and skips pure modifiers', () => {
  assert.equal(press('k', { meta: true }), 'meta+k');
  assert.equal(press('K', { meta: true, shift: true }), 'meta+shift+k');
  assert.equal(press('u', { ctrl: true, alt: true }), 'ctrl+alt+u');
  assert.equal(press('Enter', { shift: true }), 'shift+enter');
  assert.equal(press('Escape'), 'escape');
  assert.equal(press('/'), '/');
  assert.equal(press('ArrowUp'), 'arrowup');
  assert.equal(press(' '), 'space');
  assert.equal(press('Meta', { meta: true }), null);
  assert.equal(press('Control', { ctrl: true }), null);
  assert.equal(press('Alt', { alt: true }), null);
  assert.equal(press('Shift', { shift: true }), null);
});

test('text search matches localized labels, label keys, and chord text', () => {
  const all = filterShortcutGroups({
    query: '',
    combo: null,
    platform: 'other',
    resolveLabel: labelFor,
  });
  assert.deepEqual(
    all.map(({ group }) => group),
    [...SHORTCUT_GROUPS],
  );
  assert.equal(
    all.flatMap(({ shortcuts }) => shortcuts).length,
    KEYBOARD_SHORTCUTS.length,
  );

  const byLabel = filterShortcutGroups({
    query: 'activity-inbox',
    combo: null,
    platform: 'other',
    resolveLabel: labelFor,
  });
  assert.deepEqual(
    byLabel.flatMap(({ shortcuts }) => shortcuts.map(({ id }) => id)),
    ['activity-inbox'],
  );

  const byChordText = filterShortcutGroups({
    query: 'ctrl alt u',
    combo: null,
    platform: 'other',
    resolveLabel: labelFor,
  });
  assert.deepEqual(
    byChordText.flatMap(({ shortcuts }) => shortcuts.map(({ id }) => id)),
    ['activity-inbox'],
  );

  const empty = filterShortcutGroups({
    query: 'no-such-shortcut',
    combo: null,
    platform: 'other',
    resolveLabel: labelFor,
  });
  assert.deepEqual(empty, []);
});

test('keypress search matches the platform-resolved binding', () => {
  const macCombo = filterShortcutGroups({
    query: '',
    combo: 'meta+k',
    platform: 'mac',
    resolveLabel: labelFor,
  });
  assert.deepEqual(
    macCombo.flatMap(({ shortcuts }) => shortcuts.map(({ id }) => id)),
    ['command-palette'],
  );
  const otherCombo = filterShortcutGroups({
    query: '',
    combo: 'ctrl+k',
    platform: 'other',
    resolveLabel: labelFor,
  });
  assert.deepEqual(
    otherCombo.flatMap(({ shortcuts }) => shortcuts.map(({ id }) => id)),
    ['command-palette'],
  );
  // The same physical combo does not match cross-platform bindings.
  const crossPlatform = filterShortcutGroups({
    query: '',
    combo: 'meta+k',
    platform: 'other',
    resolveLabel: labelFor,
  });
  assert.deepEqual(crossPlatform, []);
  // Alternative keys of one action both match.
  const arrowDown = filterShortcutGroups({
    query: '',
    combo: 'arrowdown',
    platform: 'other',
    resolveLabel: labelFor,
  });
  assert.deepEqual(
    arrowDown.flatMap(({ shortcuts }) => shortcuts.map(({ id }) => id)),
    ['palette-move'],
  );
});

test('text query and keypress combo compose as an AND filter', () => {
  const combined = filterShortcutGroups({
    query: 'palette',
    combo: 'ctrl+k',
    platform: 'other',
    resolveLabel: labelFor,
  });
  assert.deepEqual(
    combined.flatMap(({ shortcuts }) => shortcuts.map(({ id }) => id)),
    ['command-palette'],
  );
  const contradictory = filterShortcutGroups({
    query: 'composer',
    combo: 'ctrl+k',
    platform: 'other',
    resolveLabel: labelFor,
  });
  assert.deepEqual(contradictory, []);
});
