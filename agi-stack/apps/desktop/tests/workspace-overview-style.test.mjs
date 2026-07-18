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
const prototypeStylesheet = readFileSync(
  new URL(
    '../../../../design-prototype/memstack-desktop-agent-mission-control/src/styles.css',
    import.meta.url
  ),
  'utf8'
);
const qaStylesheet = readFileSync(
  new URL('../src/qa/workspaceExecutionQa.css', import.meta.url),
  'utf8'
);
const qaSource = readFileSync(
  new URL('../src/qa/WorkspaceExecutionQa.tsx', import.meta.url),
  'utf8'
);

function cssRule(selector) {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return stylesheet.match(new RegExp(`${escapedSelector}\\s*\\{([\\s\\S]*?)\\}`))?.[1] ?? '';
}

test('workspace overview keeps the prototype flat canvas without an invented gradient', () => {
  const overviewRule = cssRule('.workspace-design-overview');

  assert.doesNotMatch(overviewRule, /gradient\(/);
  assert.match(overviewRule, /background:\s*#090e15\s*;/);
});

test('workspace overview QA canvas uses the production prototype sidebar width', () => {
  assert.match(
    qaStylesheet,
    /\.workspace-execution-qa-shell\s*\{[\s\S]*?grid-template-columns:\s*220px\s+minmax\(0,\s*1fr\)\s*;/,
  );
});

test('workspace overview QA renders the production hierarchy sidebar', () => {
  assert.match(qaSource, /import \{ DesktopSidebar \}/);
  assert.match(qaSource, /<DesktopSidebar/);
  assert.doesNotMatch(qaSource, /workspace-execution-qa-sidebar/);
});

test('workspace overview locks the approved prototype geometry', () => {
  assert.match(
    cssRule('.workspace-design-overview'),
    /padding:\s*34px\s+clamp\(28px,\s*4\.5vw,\s*64px\)\s+46px\s*;/,
  );
  assert.match(cssRule('.workspace-design-overview'), /font-size:\s*16px\s*;/);
  assert.match(cssRule('.workspace-design-overview'), /line-height:\s*normal\s*;/);
  assert.match(cssRule('.workspace-design-header'), /max-width:\s*1120px\s*;/);
  assert.match(cssRule('.workspace-design-header'), /align-items:\s*flex-end\s*;/);
  assert.match(cssRule('.workspace-design-header'), /padding:\s*0\s*;/);
  assert.match(cssRule('.workspace-design-content'), /max-width:\s*1120px\s*;/);
  assert.match(cssRule('.workspace-design-content'), /margin:\s*24px\s+0\s+0\s*;/);
  assert.match(cssRule('.workspace-design-content'), /padding:\s*0\s*;/);
  assert.match(cssRule('.workspace-design-title-line h1'), /font-size:\s*28px\s*;/);
  assert.match(cssRule('.workspace-design-title-line h1'), /line-height:\s*normal\s*;/);
  assert.match(cssRule('.workspace-design-header p'), /font-size:\s*11px\s*;/);
  assert.match(
    cssRule('.workspace-design-summary-grid'),
    /grid-template-columns:\s*minmax\(0,\s*1\.18fr\)\s+minmax\(370px,\s*0\.82fr\)\s*;/,
  );

  assert.match(cssRule('.workspace-design-goal-card'), /min-height:\s*178px\s*;/);
  assert.match(cssRule('.workspace-design-goal-card > p'), /font-size:\s*15px\s*;/);
  assert.match(cssRule('.workspace-design-metric'), /min-height:\s*84px\s*;/);
  assert.match(cssRule('.workspace-design-metric b'), /font-size:\s*24px\s*;/);

  assert.match(
    cssRule('.workspace-design-system-grid'),
    /grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)\s*;/,
  );
  assert.match(
    cssRule('.workspace-design-lower-grid'),
    /grid-template-columns:\s*minmax\(0,\s*1\.35fr\)\s+minmax\(270px,\s*0\.65fr\)\s*;/,
  );
  assert.match(
    cssRule('.workspace-design-activity-card > div'),
    /padding:\s*6px\s+12px\s+10px\s*;/,
  );
  assert.match(
    cssRule('.workspace-design-activity-card > div > div:not(.workspace-design-empty)'),
    /grid-template-columns:\s*24px\s+minmax\(0,\s*1fr\)\s*;/,
  );
  assert.match(
    cssRule('.workspace-design-activity-card > div > div:not(.workspace-design-empty)'),
    /padding:\s*10px\s+0\s*;/,
  );
  assert.match(stylesheet, /@media\s*\(max-width:\s*1180px\)/);
});

test('workspace overview keeps readable text in both the prototype and implementation', () => {
  const prototypeOverview =
    prototypeStylesheet.match(
      /\.workspace-overview\s*\{[\s\S]*?(?=\/\* Conversation detail:)/
    )?.[0] ?? '';
  const subTenPixelText = /font-size:\s*(?:[0-9](?:\.\d+)?)px\s*;/;

  assert.ok(prototypeOverview, 'prototype workspace overview styles must exist');
  assert.doesNotMatch(prototypeOverview, subTenPixelText);
  assert.doesNotMatch(stylesheet, subTenPixelText);
  assert.doesNotMatch(prototypeOverview, /color:\s*#(?:5c6b7e|5e6d7f|5f6f81|59687b)\s*;/i);
  assert.doesNotMatch(stylesheet, /color:\s*var\(--desktop-faint\)\s*;/);
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
