import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');

test('desktop shell mounts only the prototype sidebar and page-owned headers', () => {
  assert.doesNotMatch(appSource, /className="titlebar"/);
  assert.doesNotMatch(appSource, /className="copilot-sidebar"/);
  assert.equal((appSource.match(/<DesktopSidebar\b/g) ?? []).length, 1);
});
