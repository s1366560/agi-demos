import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const chatPanelSource = readFileSync(
  new URL('../src/features/chat/ChatPanel.tsx', import.meta.url),
  'utf8',
);
const chatTimelineSource = readFileSync(
  new URL('../src/features/chat/ChatTimeline.tsx', import.meta.url),
  'utf8',
);
const appSource = readFileSync(
  new URL('../src/App.tsx', import.meta.url),
  'utf8',
);

test('a stopped run leaves a visible, retryable notice', () => {
  assert.match(chatPanelSource, /session-stop-notice/);
  assert.match(chatPanelSource, /session\.responseStopped/);
  assert.match(chatPanelSource, /session\.retryStoppedResponse/);
  assert.match(chatPanelSource, /stopRequest\.status === 'stopped'/);
  assert.match(chatPanelSource, /retryStoppedTurn\(stoppedVisibleMessage\)/);
});

test('the stop control and composer gate follow canonical run activity', () => {
  assert.match(chatPanelSource, /runActive &&\s*\n\s*stopResponseAvailable/);
  assert.match(chatPanelSource, /!runActive/);
  assert.match(chatPanelSource, /runActive=\{runActive\}/);
});

test('legacy plan-ready assistant messages are localized at render time', () => {
  assert.match(
    chatTimelineSource,
    /localizePlanReadyMessage\(item\.content, t\)/,
  );
});

test('slow session authority escalates to a retryable notice', () => {
  assert.match(appSource, /sessionProjectionSlow/);
  assert.match(appSource, /10_000/);
  assert.match(appSource, /session\.authoritySlowTitle/);
  assert.match(appSource, /sessionProjectionSlow\s*\n\s*\? invalidateSessionAuthority/);
});

test('runtime-conflict rows expose a retry action', () => {
  assert.match(chatTimelineSource, /errorCode === 'runtime_conflict'/);
  assert.match(chatTimelineSource, /onRetryFailedTurn\(\)/);
  assert.match(chatPanelSource, /onRetryFailedTurn=\{retryFailedTimelineTurn\}/);
});
