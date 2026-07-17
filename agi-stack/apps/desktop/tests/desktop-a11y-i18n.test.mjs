import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const readSource = (path) =>
  readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');

const appSource = readSource('App.tsx');
const flowSource = readSource('features/task/NewTaskFlow.tsx');
const stagesSource = readSource('features/task/NewTaskFlowStages.tsx');
const runtimeSource = readSource('features/runtime/RuntimeConfigPanel.tsx');
const i18nSource = readSource('i18n.tsx');

test('session canvas implements an arrow-key navigable tab pattern', () => {
  assert.match(appSource, /role="tablist"/);
  assert.match(appSource, /role="tab"/);
  assert.match(appSource, /aria-selected=\{activeTab === tab\}/);
  assert.match(appSource, /aria-controls=\{panelId\}/);
  assert.match(appSource, /tabIndex=\{activeTab === tab \? 0 : -1\}/);
  assert.match(appSource, /\['ArrowLeft', 'ArrowRight', 'Home', 'End'\]/);
  assert.match(appSource, /role="tabpanel"/);
  assert.match(appSource, /aria-labelledby=\{tabId\(activeTab\)\}/);
});

test('new-task review announces and focuses the newly available plan', () => {
  assert.match(flowSource, /const reviewHeadingRef = useRef<HTMLHeadingElement>/);
  assert.match(flowSource, /phase !== 'review'[\s\S]*reviewHeadingRef\.current\?\.focus\(\)/);
  assert.match(flowSource, /role="status"[\s\S]*aria-live="polite"[\s\S]*task\.reviewReadyAnnouncement/);
  assert.match(flowSource, /headingRef=\{reviewHeadingRef\}/);
  assert.match(stagesSource, /headingRef=\{headingRef\}[\s\S]*headingTabIndex=\{-1\}/);
});

test('plan-step save and cancel restore focus to the originating edit button', () => {
  assert.match(stagesSource, /returnFocusStepIdRef/);
  assert.match(stagesSource, /stepEditButtonRefs\.current\.get\(stepId\)\?\.focus\(\)/);
  assert.match(stagesSource, /onCancel=\{\(\) => \{[\s\S]*returnFocusStepIdRef\.current = step\.id/);
  assert.match(stagesSource, /onSave=\{\(nextStep\) => \{[\s\S]*returnFocusStepIdRef\.current = step\.id/);
  assert.match(stagesSource, /ref=\{editButtonRef\}/);
});

test('runtime connection errors retain their actionable detail', () => {
  assert.match(runtimeSource, /\{wsError \? \(/);
  assert.match(runtimeSource, /role="alert"/);
  assert.match(runtimeSource, /runtime\.liveUpdatesError/);
  assert.match(runtimeSource, /message: wsError/);
});

test('command palette and recovery affordances use localized, accurate copy', () => {
  for (const key of [
    'commandPalette.title',
    'commandPalette.searchPlaceholder',
    'commandPalette.empty',
    'commandPalette.refreshWorkspace',
    'runtime.liveUpdatesError',
    'task.reviewReadyAnnouncement',
  ]) {
    assert.equal((i18nSource.match(new RegExp(`'${key.replaceAll('.', '\\.')}'`, 'g')) ?? []).length, 2);
  }
  assert.match(appSource, /t\('commandPalette\.title'\)/);
  assert.match(appSource, /t\('commandPalette\.searchPlaceholder'\)/);
  assert.match(i18nSource, /Open connection recovery/);
  assert.match(i18nSource, /打开连接恢复/);
  assert.doesNotMatch(appSource, /aria-label="Command palette"/);
  assert.doesNotMatch(appSource, /placeholder="Search commands/);
});
