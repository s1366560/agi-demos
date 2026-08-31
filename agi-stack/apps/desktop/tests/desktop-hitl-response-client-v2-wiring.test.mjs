import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const provider = source('src/features/session/desktopHitlResponseClientProviderV2.ts');
const socket = source('src/hooks/useAgentSocket.ts');
const stableProviderPattern = new RegExp(
  [
    'const desktopHitlResponseClientProviderV2 = useMemo\\(',
    '[\\s\\S]*?createDesktopHitlResponseClientProviderV2\\(\\)',
    '[\\s\\S]*?\\[\\],[\\s\\S]*?\\);',
  ].join(''),
  'u',
);
const exactMethodOwnershipPattern =
  /type DesktopHitlResponseMethod = 'respondToHitl';/u;
const forbiddenProviderOwnershipPattern = new RegExp(
  [
    'respondableHitlRequestIdSet',
    'classifyHitlAuthorityRecovery',
    'invalidateSessionAuthority',
    'loadConversationTimeline',
    'sessionProjection',
  ].join('|'),
  'u',
);

test('App publishes one stable V2 HITL response client Provider', () => {
  assert.match(app, /createDesktopHitlResponseClientProviderV2/u);
  assert.match(app, stableProviderPattern);
  assert.match(app, /desktopHitlResponseClientProviderV2\.publish\(\{ config \}\)/u);
});

test('HITL responses bind one submitted-scope V2 client', () => {
  const response = callbackSource(app, 'respondToHitl', 'presetAutoApprovalAttemptsRef');

  assert.match(response, /const requestConfig = configRef\.current;/u);
  assert.match(
    response,
    /const client = desktopHitlResponseClientV2\.bindOperation\(requestConfig\);/u,
  );
  assert.match(response, /await client\.respondToHitl\(submission\);/u);
  assert.match(response, /formatConnectionError\(caught, requestConfig\.apiBaseUrl\)/u);
  assert.match(response, /request\.status !== 'pending'/u);
  assert.match(response, /request\.kind !== submission\.hitlType/u);
  assert.match(response, /request\?\.authority_revision === submission\.expectedRevision/u);
  assert.match(response, /respondableHitlRequestIdSet\.has\(submission\.requestId\)/u);
  assert.match(response, /classifyHitlAuthorityRecovery\(caught\)/u);
  assert.doesNotMatch(response, /api\.respondToHitl/u);
});

test('manual and preset approval paths share the Provider-backed response coordinator', () => {
  assert.match(app, /void respondToHitl\(submission\)/u);
  assert.match(app, /await respondToHitl\(submission\);/u);
});

test('HITL response Provider owns only the response transport', () => {
  assert.match(provider, exactMethodOwnershipPattern);
  assert.match(provider, /respondToHitl:/u);
  assert.match(provider, /bindOperation/u);
  assert.doesNotMatch(provider, forbiddenProviderOwnershipPattern);
});

test('Desktop socket no longer exposes a second HITL response authority', () => {
  assert.doesNotMatch(socket, /respondToHitl/u);
  assert.doesNotMatch(socket, /buildHitlSocketMessage/u);
  assert.doesNotMatch(socket, /HitlResponseSubmission/u);
});

function callbackSource(sourceText, name, nextName) {
  const start = sourceText.indexOf(`const ${name} = useCallback(`);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf(`\n  const ${nextName}`, start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
