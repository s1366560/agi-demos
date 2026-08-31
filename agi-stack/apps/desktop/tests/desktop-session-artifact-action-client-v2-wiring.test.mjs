import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const provider = source(
  'src/features/session/desktopSessionArtifactActionClientProviderV2.ts',
);
const stableProviderPattern = new RegExp(
  [
    'const desktopSessionArtifactActionClientProviderV2 = useMemo\\(',
    '[\\s\\S]*?createDesktopSessionArtifactActionClientProviderV2\\(\\)',
    '[\\s\\S]*?\\[\\],[\\s\\S]*?\\);',
  ].join(''),
  'u',
);
const exactMethodOwnershipPattern = new RegExp(
  [
    'type DesktopSessionArtifactActionMethod =',
    "\\s*\\| 'reviewArtifactVersion'",
    "\\s*\\| 'deliverArtifactVersion'",
  ].join(''),
  'u',
);
const forbiddenProviderOwnershipPattern = new RegExp(
  [
    'artifactVersionActions',
    'artifactReviewRequest',
    'artifactDeliveryRequest',
    'setArtifactActionPending',
    'invalidateSessionAuthority',
  ].join('|'),
  'u',
);

test('App publishes one stable V2 session artifact action client Provider', () => {
  assert.match(app, /createDesktopSessionArtifactActionClientProviderV2/u);
  assert.match(app, stableProviderPattern);
  assert.match(app, /desktopSessionArtifactActionClientProviderV2\.publish\(\{ config \}\)/u);
});

test('artifact actions bind one submitted-scope V2 client', () => {
  const action = callbackSource(app, 'handleArtifactAction', 'hasWorkspaceScope');

  assert.match(action, /const requestConfig = configRef\.current;/u);
  assert.match(
    action,
    /const client = desktopSessionArtifactActionClientV2\.bindOperation\(requestConfig\);/u,
  );
  assert.match(action, /await client\.deliverArtifactVersion\(/u);
  assert.match(action, /await client\.reviewArtifactVersion\(/u);
  assert.match(action, /formatConnectionError\(caught, requestConfig\.apiBaseUrl\)/u);
  assert.match(action, /desktopSessionArtifactActionClientV2/u);
  assert.doesNotMatch(action, /api\.(?:deliver|review)ArtifactVersion/u);
});

test('session artifact action Provider owns only review and delivery transport', () => {
  assert.match(provider, exactMethodOwnershipPattern);
  assert.match(provider, /reviewArtifactVersion:/u);
  assert.match(provider, /deliverArtifactVersion:/u);
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
