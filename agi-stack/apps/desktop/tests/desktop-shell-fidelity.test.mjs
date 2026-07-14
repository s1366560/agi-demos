import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const globalStyles = readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8');
const sessionStyles = readFileSync(
  new URL('../src/features/session/SessionWorkspace.css', import.meta.url),
  'utf8'
);

test('desktop shell mounts only the prototype sidebar and page-owned headers', () => {
  assert.doesNotMatch(appSource, /className="titlebar"/);
  assert.doesNotMatch(appSource, /className="copilot-sidebar"/);
  assert.equal((appSource.match(/<DesktopSidebar\b/g) ?? []).length, 1);
});

test('notifications never open a standalone workspace review route', () => {
  assert.doesNotMatch(appSource, /activeSection === 'review'/);
  assert.doesNotMatch(appSource, /switchSection\('review'\)/);
  assert.doesNotMatch(appSource, /WorkspaceReviewPanelVariant/);
  assert.doesNotMatch(appSource, /variant = 'workspace'/);
  assert.match(appSource, /className="workbench-layout"/);
  assert.doesNotMatch(appSource, /review-panel-collapsed/);
  assert.doesNotMatch(globalStyles, /review-panel-collapsed/);
});

test('desktop styles remove standalone workspace drawer and pull-request chrome', () => {
  assert.doesNotMatch(globalStyles, /\.review-panel-stage\b/);
  assert.doesNotMatch(globalStyles, /\.review-panel\.(?:maximized|full-screen)\b/);
  assert.doesNotMatch(globalStyles, /\.review-tab-menu\b/);
  assert.doesNotMatch(globalStyles, /\.review-pr\b/);
  assert.doesNotMatch(globalStyles, /\.pr-summary-panel\b/);
  assert.doesNotMatch(sessionStyles, /\.review-head\b/);
});
