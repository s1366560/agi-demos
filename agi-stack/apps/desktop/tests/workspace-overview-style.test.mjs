import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const stylesheet = readFileSync(
  new URL('../src/features/workspace/WorkspaceOverview.css', import.meta.url),
  'utf8'
);
const source = readFileSync(
  new URL('../src/features/workspace/WorkspaceOverview.tsx', import.meta.url),
  'utf8'
);

test('workspace overview keeps the prototype flat canvas without an invented gradient', () => {
  const overviewRule = stylesheet.match(/\.workspace-design-overview\s*\{([\s\S]*?)\}/)?.[1] ?? '';

  assert.doesNotMatch(overviewRule, /gradient\(/);
  assert.match(overviewRule, /background:\s*#090e15\s*;/);
});

test('workspace overview localizes governed office states instead of exposing raw values', () => {
  assert.match(source, /conversationTreeStatusPresentation\(status\)/);
  assert.match(source, /t\(officeStatusPresentation\.labelKey\)/);
  assert.doesNotMatch(source, /workspaceStatusLabel\(model\.officeStatus/);
  assert.match(source, /t\(statusPresentation\.labelKey\)/);
  assert.doesNotMatch(source, /return status;/);
  assert.match(stylesheet, /em\[data-status='offline'\]/);
});

test('workspace overview reserves completion icons for completed or review-ready sessions', () => {
  const iconMapping =
    source.match(/function sessionStatusIcon\([\s\S]*?\n\}/)?.[0] ?? '';

  assert.match(iconMapping, /tone === 'ready' \|\| tone === 'completed'/);
  assert.match(iconMapping, /return ActivityLogIcon/);
});
