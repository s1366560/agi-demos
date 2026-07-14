import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const stylesheet = readFileSync(
  new URL('../src/features/workspace/WorkspaceOverview.css', import.meta.url),
  'utf8'
);

test('workspace overview keeps the prototype flat canvas without an invented gradient', () => {
  const overviewRule = stylesheet.match(/\.workspace-design-overview\s*\{([\s\S]*?)\}/)?.[1] ?? '';

  assert.doesNotMatch(overviewRule, /gradient\(/);
  assert.match(overviewRule, /background:\s*#090e15\s*;/);
});
