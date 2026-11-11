import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  NEW_THREAD_SCOPE_STORAGE_KEY,
  readNewThreadScopePreference,
  writeNewThreadScopePreference,
} from '/tmp/agistack-desktop-test-dist/src/features/task/newThreadPreferenceModel.js';

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key) => (values.has(key) ? values.get(key) : null),
    setItem: (key, value) => values.set(key, value),
    values,
  };
}

const conversationThreadsSource = readFileSync(
  new URL('../src/hooks/useConversationThreads.ts', import.meta.url),
  'utf8',
);

test('new-thread creation reads and writes the remembered workspace scope', () => {
  assert.match(conversationThreadsSource, /readNewThreadScopePreference\(config\.projectId\)/);
  assert.match(
    conversationThreadsSource,
    /writeNewThreadScopePreference\(config\.projectId, nextWorkspaceId\)/,
  );
});

test('remembers the explicit workspace per project, including the no-workspace choice', () => {
  const storage = memoryStorage();
  assert.equal(readNewThreadScopePreference('project-a', storage), null);
  writeNewThreadScopePreference('project-a', 'workspace-a', storage);
  assert.deepEqual(readNewThreadScopePreference('project-a', storage), {
    workspaceId: 'workspace-a',
  });
  assert.equal(readNewThreadScopePreference('project-b', storage), null);

  writeNewThreadScopePreference('project-a', '', storage);
  assert.deepEqual(readNewThreadScopePreference('project-a', storage), {
    workspaceId: '',
  });
});

test('ignores malformed or inaccessible preferences and writes valid envelopes', () => {
  const malformed = memoryStorage({
    [NEW_THREAD_SCOPE_STORAGE_KEY]: '{not-json',
  });
  assert.equal(readNewThreadScopePreference('project-a', malformed), null);

  const wrongShape = memoryStorage({
    [NEW_THREAD_SCOPE_STORAGE_KEY]: JSON.stringify({
      version: 1,
      projectId: 'project-a',
    }),
  });
  assert.equal(readNewThreadScopePreference('project-a', wrongShape), null);

  const throwing = {
    getItem: () => {
      throw new Error('blocked');
    },
    setItem: () => {
      throw new Error('blocked');
    },
  };
  assert.equal(readNewThreadScopePreference('project-a', throwing), null);
  assert.doesNotThrow(() =>
    writeNewThreadScopePreference('project-a', 'workspace-a', throwing),
  );
});
