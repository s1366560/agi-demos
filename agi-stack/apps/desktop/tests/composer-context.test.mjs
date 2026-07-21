import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import test from 'node:test';

const plusMenuUrl = new URL('../src/features/chat/ComposerPlusMenu.tsx', import.meta.url);
const pickerUrl = new URL('../src/features/chat/PickerMenu.tsx', import.meta.url);
const newThreadSource = readFileSync(
  new URL('../src/features/task/NewThreadComposer.tsx', import.meta.url),
  'utf8',
);
const chatPanelSource = readFileSync(
  new URL('../src/features/chat/ChatPanel.tsx', import.meta.url),
  'utf8',
);
const apiSource = readFileSync(new URL('../src/api/client.ts', import.meta.url), 'utf8');
const typesSource = readFileSync(new URL('../src/types.ts', import.meta.url), 'utf8');

test('both composers use the shared six-category context menu and removable chips', () => {
  assert.equal(existsSync(plusMenuUrl), true);
  if (!existsSync(plusMenuUrl)) return;
  const plusMenuSource = readFileSync(plusMenuUrl, 'utf8');
  assert.match(plusMenuSource, /kind: 'attachment'/);
  for (const category of ['agent', 'skill', 'plugin', 'command', 'thread']) {
    assert.match(plusMenuSource, new RegExp(`resourceItem\\(\\s*'${category}'`));
  }
  assert.match(newThreadSource, /<ComposerPlusMenu/);
  assert.match(newThreadSource, /composer-context-chips/);
  assert.match(chatPanelSource, /<ComposerPlusMenu/);
  assert.match(chatPanelSource, /composer-context-chips/);
});

test('model and effort controls use described picker menus without cycling values', () => {
  assert.equal(existsSync(pickerUrl), true);
  if (!existsSync(pickerUrl)) return;
  const pickerSource = readFileSync(pickerUrl, 'utf8');
  assert.match(pickerSource, /role="menuitemradio"/);
  assert.match(pickerSource, /option\.description/);
  assert.match(pickerSource, /option\.meta/);
  assert.match(newThreadSource, /<PickerMenu/);
  assert.doesNotMatch(newThreadSource, /<select/);
  assert.doesNotMatch(newThreadSource, /cycle\(/);
});

test('composer context travels through task-session, workspace-message, and run-input requests', () => {
  assert.match(typesSource, /export type ComposerContextItem/);
  assert.match(typesSource, /context_items\?: ComposerContextItem\[\]/);
  assert.match(apiSource, /context_items: input\.contextItems/);
  assert.match(apiSource, /context_items: contextItems/);
});
