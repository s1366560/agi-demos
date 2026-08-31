import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const provider = source(
  'src/features/session/desktopSessionRunControlClientProviderV2.ts',
);
const ownedMethods = [
  'pauseRun',
  'resumeRun',
  'forkRecoveryRun',
  'cancelRun',
  'reviewRun',
];
const stableProviderPattern = new RegExp(
  [
    'const desktopSessionRunControlClientProviderV2 = useMemo\\(',
    '[\\s\\S]*?createDesktopSessionRunControlClientProviderV2\\(\\)',
    '[\\s\\S]*?\\[\\],[\\s\\S]*?\\);',
  ].join(''),
  'u',
);
const exactMethodOwnershipPattern = new RegExp(
  [
    'type DesktopSessionRunControlMethod =',
    "[\\s\\S]*?'pauseRun'",
    "[\\s\\S]*?'resumeRun'",
    "[\\s\\S]*?'forkRecoveryRun'",
    "[\\s\\S]*?'cancelRun'",
    "[\\s\\S]*?'reviewRun'",
  ].join(''),
  'u',
);
const forbiddenProviderOwnershipPattern = new RegExp(
  [
    'sessionDetailViewModel',
    'runActions',
    'desktop-recovery-fork',
    'applyAuthoritativeRun',
    'invalidateSessionAuthority',
    'showToast',
    'setError',
  ].join('|'),
  'u',
);

test('App publishes one stable V2 session run-control client Provider', () => {
  assert.match(app, /createDesktopSessionRunControlClientProviderV2/u);
  assert.match(app, stableProviderPattern);
  assert.match(
    app,
    /desktopSessionRunControlClientProviderV2\.publish\(\{ config \}\)/u,
  );
});

test('session run actions bind one submitted-scope V2 client without moving policy', () => {
  const action = callbackSource(app, 'handleSessionRunAction', 'handleArtifactAction');

  assert.match(action, /const requestConfig = configRef\.current;/u);
  assert.match(
    action,
    /const client = desktopSessionRunControlClientV2\.bindOperation\(requestConfig\);/u,
  );
  for (const method of ownedMethods) {
    assert.match(action, new RegExp(`await client\\.${method}\\(`, 'u'));
  }
  assert.doesNotMatch(
    action,
    /api\.(?:pauseRun|resumeRun|forkRecoveryRun|cancelRun|reviewRun)/u,
  );
  assert.match(action, /!runId \|\| revision === null \|\| revision === undefined/u);
  assert.match(action, /!sessionDetailViewModel\.runActions\.includes\(action\)/u);
  assert.match(action, /`desktop-recovery-fork:\$\{runId\}:\$\{revision\}`/u);
  assert.match(action, /action: action === 'approve' \? 'approve' : 'request_changes'/u);
  assert.match(action, /\.\.\.\(feedback \? \{ feedback \} : \{\}\)/u);
  assert.match(action, /applyAuthoritativeRun\(outcome\.run\)/u);
  assert.match(action, /invalidateSessionAuthority\(\)/u);
  assert.match(action, /toast\.sessionRunActionSuccess/u);
});

test('session run-control Provider owns exactly five transport methods', () => {
  assert.match(provider, exactMethodOwnershipPattern);
  for (const method of ownedMethods) {
    assert.match(provider, new RegExp(`${method}:`, 'u'));
  }
  assert.match(provider, /bindOperation/u);
  assert.doesNotMatch(provider, forbiddenProviderOwnershipPattern);
});

function callbackSource(sourceText, name, nextName) {
  const start = sourceText.indexOf(`const ${name} = useCallback(`);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf(`\n  const ${nextName}`, start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
